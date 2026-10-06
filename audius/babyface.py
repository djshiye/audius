"""RME Babyface Pro FS (Class Compliant mode) device model.

Control names follow the kernel quirk (`snd_bbfpro_controls_create`). The driver
can only write: values it reports are what it last sent, and a write equal to that
cached value never reaches the hardware. Changes made with the device's own keys
and knob are invisible to the computer.
"""
import logging
import math
import threading
import time

from . import alsa

log = logging.getLogger(__name__)

USB_ID = "2a39:3fb0"

INPUTS = ("AN1", "AN2", "IN3", "IN4", "AS1", "AS2",
          "ADAT3", "ADAT4", "ADAT5", "ADAT6", "ADAT7", "ADAT8")
OUTPUTS = ("AN1", "AN2", "PH3", "PH4", "AS1", "AS2",
           "ADAT3", "ADAT4", "ADAT5", "ADAT6", "ADAT7", "ADAT8")
# Stereo pairs, named by their first channel.
INPUT_PAIRS = (("AN1", "AN2"), ("IN3", "IN4"), ("AS1", "AS2"),
               ("ADAT3", "ADAT4"), ("ADAT5", "ADAT6"), ("ADAT7", "ADAT8"))
OUTPUT_PAIRS = (("AN1", "AN2"), ("PH3", "PH4"), ("AS1", "AS2"),
                ("ADAT3", "ADAT4"), ("ADAT5", "ADAT6"), ("ADAT7", "ADAT8"))
MIC_INPUTS = ("AN1", "AN2")
LINE_INPUTS = ("IN3", "IN4")

UNITY = 32768        # 0 dB
MAX_RAW = 65536      # +6.02 dB
MAX_DB = 20 * math.log10(MAX_RAW / UNITY)
MIC_GAIN_MAX = 65    # dB, 1 dB steps
LINE_GAIN_MAX = 18   # 0.5 dB steps (9 dB)

CLOCK = "Sample Clock Source"          # 0 AutoSync, 1 Internal
OPTICAL_SPDIF = "IEC958 Switch"        # 1: optical output carries S/PDIF, 0: ADAT
SPDIF_PRO = "IEC958 Pro Mask"
SPDIF_EMPHASIS = "IEC958 Emphasis"


def raw_to_db(raw):
    return -math.inf if raw <= 0 else 20 * math.log10(raw / UNITY)


def db_to_raw(db):
    if db is None or db == -math.inf or db < -120:
        return 0
    return max(0, min(MAX_RAW, int(round(UNITY * 10 ** (db / 20)))))


def send_ctl(src, out):
    """Control name for a send. `src` is 'in:<input>' or 'pb:<playback channel>'."""
    kind, ch = src.split(":")
    if kind == "pb":
        return f"PCM-{ch}-{out} Playback Volume"
    return f"{'Mic' if ch in MIC_INPUTS else 'Line'}-{ch}-{out} Playback Volume"


def volume_ctl(out):
    return f"Main-Out {out}"


def gain_ctl(ch):
    return f"{'Mic' if ch in MIC_INPUTS else 'Line'}-{ch} Gain"


def p48_ctl(ch):
    return f"Mic-{ch} 48V"


def pad_ctl(ch):
    return f"Mic-{ch} PAD"


def sens_ctl(ch):
    return f"Line-{ch} Sens."


def gain_to_db(ch, raw):
    return float(raw) if ch in MIC_INPUTS else raw / 2.0


def db_to_gain(ch, db):
    if ch in MIC_INPUTS:
        return max(0, min(MIC_GAIN_MAX, int(round(db))))
    return max(0, min(LINE_GAIN_MAX, int(round(db * 2))))


ALL_SOURCES = tuple(f"in:{c}" for c in INPUTS) + tuple(f"pb:{c}" for c in OUTPUTS)
SEND_CTLS = tuple(send_ctl(s, o) for s in ALL_SOURCES for o in OUTPUTS)
VOLUME_CTLS = tuple(volume_ctl(o) for o in OUTPUTS)

# Kernel quirk bug (sound/usb/mixer_quirks.c): the mixer controls cache
# `index | value << 9` while the index is 10 bits wide, so bit 0 of the value lands
# on bit 9 of the index. Writing an odd value to a crosspoint (index < 512) makes
# every later write to that control go to DSP address index+512 until the driver
# re-probes, and the main-out controls (index >= 992) read back as value|1.
# Audius therefore only ever writes even values, reads volumes back with bit 0
# cleared, and leaves crosspoints that already read odd ("poisoned") alone.
EVEN_ONLY = frozenset(SEND_CTLS + VOLUME_CTLS)


def even(v):
    return int(v) & ~1


def normalize(name, raw):
    """(value, poisoned) for a value read from the driver."""
    if name in EVEN_ONLY:
        return raw & ~1, bool(raw & 1) and name not in VOLUME_CTLS
    return raw, False
EXPECTED_CTLS = (SEND_CTLS + VOLUME_CTLS + tuple(gain_ctl(c) for c in MIC_INPUTS + LINE_INPUTS)
                 + tuple(p48_ctl(c) for c in MIC_INPUTS) + tuple(pad_ctl(c) for c in MIC_INPUTS)
                 + tuple(sens_ctl(c) for c in LINE_INPUTS)
                 + (CLOCK, OPTICAL_SPDIF, SPDIF_PRO, SPDIF_EMPHASIS))


class Ramp:
    """A fade between two raw values: dB-linear and eased for volumes, or a plain
    linear walk (used for preamp gain, whose raw values are already in dB)."""
    FLOOR_DB = -60.0

    __slots__ = ("start", "end", "t0", "duration", "linear")

    def __init__(self, start, end, t0, duration, linear=False):
        self.start, self.end, self.t0, self.duration = int(start), int(end), t0, max(0.0, duration)
        self.linear = linear

    def done(self, t):
        return t >= self.t0 + self.duration

    def value_at(self, t):
        if self.duration <= 0 or self.done(t):
            return self.end
        x = max(0.0, (t - self.t0) / self.duration)
        if self.linear:
            return int(round(self.start + (self.end - self.start) * x))
        x = x * x * (3 - 2 * x)  # smoothstep
        a = max(raw_to_db(self.start), self.FLOOR_DB)
        b = max(raw_to_db(self.end), self.FLOOR_DB)
        return db_to_raw(a + (b - a) * x)


class Writer(threading.Thread):
    """Applies writes off the UI thread. Writes to one control coalesce (only the
    newest value is sent) and ramps step every few milliseconds."""
    STEP = 0.006

    def __init__(self, open_ctl, controls, initial, on_gone):
        super().__init__(daemon=True, name="audius-writer")
        self._open_ctl = open_ctl
        self._controls = controls
        self._last = dict(initial)
        self._on_gone = on_gone
        self._cv = threading.Condition()
        self._pending = {}
        self._ramps = {}
        self._sequence = []     # ordered (name, value) writes, used by resync
        self._busy = frozenset()
        self._stopped = False

    def set(self, name, value):
        with self._cv:
            self._ramps.pop(name, None)
            self._pending[name] = int(value)
            self._cv.notify()

    def ramp(self, name, end, duration, start=None, linear=False):
        with self._cv:
            now = time.monotonic()
            current = self._ramps.get(name)
            if start is None:
                if current is not None:
                    start = current.value_at(now)
                else:
                    start = self._pending.get(name, self._last.get(name, end))
            self._pending.pop(name, None)
            self._ramps[name] = Ramp(start, end, now, duration, linear)
            self._cv.notify()

    def sequence(self, writes):
        with self._cv:
            self._sequence.extend(writes)
            self._cv.notify()

    def note(self, name, value):
        """Record a value changed by someone else, so later ramps start from it."""
        with self._cv:
            self._last[name] = int(value)

    def busy(self, name):
        with self._cv:
            return name in self._pending or name in self._ramps or name in self._busy

    def idle(self):
        with self._cv:
            return not (self._pending or self._ramps or self._sequence or self._busy)

    def stop(self):
        with self._cv:
            self._stopped = True
            self._cv.notify()

    def run(self):
        try:
            ctl = self._open_ctl()
        except alsa.AlsaError as e:
            self._on_gone(e)
            return
        try:
            while True:
                with self._cv:
                    while not (self._pending or self._ramps or self._sequence or self._stopped):
                        self._cv.wait()
                    if self._stopped:
                        return
                    now = time.monotonic()
                    batch = list(self._sequence)
                    self._sequence.clear()
                    batch.extend(self._pending.items())
                    self._pending.clear()
                    for name, r in list(self._ramps.items()):
                        batch.append((name, r.value_at(now)))
                        if r.done(now):
                            del self._ramps[name]
                    self._busy = frozenset(n for n, _ in batch)
                    ramping = bool(self._ramps)
                for name, value in batch:
                    # No de-duplication here: the driver already skips unchanged values,
                    # and our idea of "unchanged" may be stale after an external edit.
                    if name in EVEN_ONLY:
                        value = even(value)
                    try:
                        ctl.write(self._controls[name], value)
                        self._last[name] = value
                    except alsa.DeviceGone as e:
                        self._on_gone(e)
                        return
                    except (alsa.AlsaError, ValueError, KeyError) as e:
                        log.warning("write %s=%s failed: %s", name, value, e)
                with self._cv:
                    self._busy = frozenset()
                if ramping:
                    time.sleep(self.STEP)
        finally:
            ctl.close()


class Device:
    """Common interface of the real card and the demo device."""
    name = "Babyface Pro FS"
    demo = False
    card_index = None
    card_id = ""
    serial = ""

    def __init__(self):
        self.values = {}
        self.poisoned = set()   # crosspoints the driver bug has redirected; never written
        self.on_change = None   # callback(dict name -> value) for changes made elsewhere
        self.on_gone = None     # callback() when the card disappears

    def get(self, name):
        return self.values[name]

    def set(self, name, value):
        raise NotImplementedError

    def ramp(self, name, value, duration, start=None):
        raise NotImplementedError

    def ramp_linear(self, name, value, duration):
        raise NotImplementedError

    def resend(self, names):
        raise NotImplementedError

    def busy(self, name):
        return False

    def watch(self):
        pass

    def close(self):
        pass

    def stream_rate(self):
        return None


class Babyface(Device):
    """The real card, found by USB id."""

    def __init__(self):
        super().__init__()
        found = alsa.find_card(USB_ID)
        if not found:
            raise alsa.DeviceGone(19, "Babyface Pro FS (Class Compliant) not found")
        self.card_index, self.card_id = found
        self.serial = self.card_id.removeprefix("Pro")
        self._ctl = alsa.Ctl(self.card_index)
        self.controls = self._ctl.controls()
        missing = [n for n in EXPECTED_CTLS if n not in self.controls]
        if missing:
            self._ctl.close()
            raise alsa.AlsaError(2, f"unexpected control set (missing {missing[:3]}…); is this kernel's "
                                    "Babyface Pro mixer quirk present?")
        self.values = {}
        for n, c in self.controls.items():
            v, bad = normalize(n, self._ctl.read(c))
            self.values[n] = v
            if bad:
                self.poisoned.add(n)
        if self.poisoned:
            log.warning("%d crosspoint(s) locked by the driver bug, left alone (docs/KERNEL-BUG.md): %s",
                        len(self.poisoned), ", ".join(sorted(self.poisoned)))
        self._by_numid = {c.numid: c for c in self.controls.values()}
        self._watch_id = None
        self._gone = False
        self._writer = Writer(lambda: alsa.Ctl(self.card_index), self.controls, self.values, self._writer_gone)
        self._writer.start()

    def _check(self, name, value):
        c = self.controls[name]
        value = int(value)
        if not c.min <= value <= c.max:
            raise ValueError(f"{name}: {value} outside {c.min}..{c.max}")
        return even(value) if name in EVEN_ONLY else value

    def set(self, name, value):
        if name in self.poisoned:
            return
        value = self._check(name, value)
        self.values[name] = value
        self._writer.set(name, value)

    def ramp(self, name, value, duration, start=None):
        if name in self.poisoned:
            return
        value = self._check(name, value)
        self.values[name] = value
        self._writer.ramp(name, value, duration, start)

    def ramp_linear(self, name, value, duration):
        value = self._check(name, value)
        self.values[name] = value
        self._writer.ramp(name, value, duration, linear=True)

    def resend(self, names):
        """Make the driver send values it believes the device already has: write a
        neighbouring value first (the driver skips writes equal to its cache).
        Volume nudges are by 2 so they stay even."""
        writes = []
        for name in names:
            if name in self.poisoned:
                continue
            c = self.controls[name]
            v = self.values[name]
            step = 2 if name in EVEN_ONLY else 1
            nudge = v + step if v + step <= c.max else v - step
            writes += [(name, nudge), (name, v)]
        self._writer.sequence(writes)

    def busy(self, name):
        return self._writer.busy(name)

    def watch(self):
        from gi.repository import GLib
        fd = self._ctl.subscribe()
        self._watch_id = GLib.unix_fd_add_full(
            GLib.PRIORITY_DEFAULT, fd, GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
            self._on_events)

    def _on_events(self, fd, condition):
        try:
            numids = self._ctl.pending_events()
            changed = {}
            for numid in numids:
                c = self._by_numid.get(numid)
                if c is None or self._writer.busy(c.name):
                    continue
                v, bad = normalize(c.name, self._ctl.read(c))
                if bad and c.name not in self.poisoned:
                    log.warning("%s was set to an odd value elsewhere; locked (docs/KERNEL-BUG.md)", c.name)
                    self.poisoned.add(c.name)
                    changed[c.name] = v
                if v != self.values.get(c.name):
                    self.values[c.name] = v
                    self._writer.note(c.name, v)
                    changed[c.name] = v
        except alsa.DeviceGone:
            self._watch_id = None      # this source is ending; close() mustn't remove it again
            self._mark_gone()
            return False
        except alsa.AlsaError as e:
            log.warning("control event: %s", e)
            return True
        if changed and self.on_change:
            self.on_change(changed)
        return True

    def _writer_gone(self, err):
        from gi.repository import GLib
        log.info("writer: device gone (%s)", err)
        GLib.idle_add(self._mark_gone)

    def _mark_gone(self):
        if self._gone:
            return False
        self._gone = True
        if self.on_gone:
            self.on_gone()
        return False

    def stream_rate(self):
        """Current sample rate if the card is streaming, else None."""
        for d in ("pcm0p", "pcm0c"):
            try:
                with open(f"/proc/asound/card{self.card_index}/{d}/sub0/hw_params") as f:
                    for line in f:
                        if line.startswith("rate:"):
                            return int(line.split()[1])
            except (OSError, ValueError, IndexError):
                pass
        return None

    def close(self):
        if self._watch_id:
            from gi.repository import GLib
            GLib.source_remove(self._watch_id)
            self._watch_id = None
        self._writer.stop()
        self._writer.join(timeout=1.0)
        self._ctl.close()


class DemoDevice(Device):
    """In-memory stand-in that mirrors a typical setup; used by --demo and tests."""
    demo = True
    card_id = "Demo"
    serial = "00000000"

    def __init__(self):
        super().__init__()
        self.values = {n: 0 for n in EXPECTED_CTLS}
        for name, value in demo_state().items():
            self.values[name] = value
        self.ramps = []
        self.resent = []

    def set(self, name, value):
        self.values[name] = even(value) if name in EVEN_ONLY else int(value)

    def ramp(self, name, value, duration, start=None):
        value = even(value) if name in EVEN_ONLY else int(value)
        self.ramps.append((name, start, value, duration))
        self.values[name] = value

    def ramp_linear(self, name, value, duration):
        self.ramp(name, value, duration)

    def resend(self, names):
        self.resent.extend(names)

    def stream_rate(self):
        return 48000


def demo_state():
    """The state found on the author's card (2026-10-06): computer to speakers and
    headphones, Mic 1 (condenser, 48V, +26 dB) to both ears."""
    s = {
        send_ctl("pb:AN1", "AN1"): MAX_RAW, send_ctl("pb:AN2", "AN2"): MAX_RAW,
        send_ctl("pb:AN1", "PH3"): MAX_RAW, send_ctl("pb:AN2", "PH4"): MAX_RAW,
        send_ctl("in:AN1", "PH3"): MAX_RAW, send_ctl("in:AN1", "PH4"): MAX_RAW,
        gain_ctl("AN1"): 26, p48_ctl("AN1"): 1,
    }
    return s   # output volumes read as 0: never written this boot, so unknown


def demo_volumes(dev, cfg):
    """--demo: pretend the volumes were set from Audius earlier (headphones -18, speakers -24 dB)."""
    for out, db in (("PH3", -18.0), ("AN1", -24.0)):
        cfg["volumes"].setdefault(out, db)
        pair = ("PH3", "PH4") if out == "PH3" else ("AN1", "AN2")
        for ch in pair:
            dev.values[volume_ctl(ch)] = even(db_to_raw(cfg["volumes"][out]))
