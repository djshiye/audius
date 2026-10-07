"""The mix model the interface talks to.

Raw ALSA controls are crosspoints (one source channel to one output channel). This
module presents them the way people think about a mixer: stereo outputs, sources
that are mono or linked stereo pairs, a level and a pan per send, outputs that can
be switched off and on again, scenes, and undo.

Pan uses a balance law: the louder side carries the level, the other side is
attenuated. Any L/R pair decodes exactly, and a mono mic sent equally to both
ears reads as "centred at its level".
"""
import copy
import math
import time
import uuid

from . import babyface as bf

TAKEOVER_WINDOW = 45.0      # s without an Audius write before the knob may have moved a volume
TAKEOVER_FADE = 0.7         # s fade-in from TAKEOVER_FLOOR_DB
TAKEOVER_FLOOR_DB = -60.0
AUDIBLE_DB = -60.0          # below this an output counts as silent
SWITCH_FADE = 0.15          # s for on/off, mutes and DIM
RECALL_FADE = 0.35          # s for scenes and undo
GAIN_STEP_TIME = 0.012      # s per gain step when gain jumps

OUT_PAIRS = {p[0]: p for p in bf.OUTPUT_PAIRS}
CHANNEL_NUMBER = {ch: i + 1 for i, ch in enumerate(bf.OUTPUTS)}
IN_NAMES = {"AN1": "Mic 1", "AN2": "Mic 2", "IN3": "Instrument 3", "IN4": "Instrument 4",
            "AS1": "Optical 1", "AS2": "Optical 2", "ADAT3": "Optical 3", "ADAT4": "Optical 4",
            "ADAT5": "Optical 5", "ADAT6": "Optical 6", "ADAT7": "Optical 7", "ADAT8": "Optical 8"}
IN_PAIR_NAMES = {"AN1": "Mic 1/2", "IN3": "Instrument 3/4", "AS1": "Optical 1/2",
                 "ADAT3": "Optical 3/4", "ADAT5": "Optical 5/6", "ADAT7": "Optical 7/8"}


def balance(left, right):
    """Pan in [-1, 1] for an L/R pair of linear gains, or None for silence."""
    m = max(left, right)
    if m <= 0:
        return None
    if left >= right:
        return -(1.0 - right / m)
    return 1.0 - left / m


def unbalance(level, pan):
    """Linear gains (left, right) for a level and a pan in [-1, 1]."""
    pan = max(-1.0, min(1.0, pan or 0.0))
    left = level * (1.0 - pan) if pan > 0 else level
    right = level * (1.0 + pan) if pan < 0 else level
    return int(round(left)), int(round(right))


def db_or_none(raw):
    return None if raw <= 0 else round(bf.raw_to_db(raw), 2)


class Strip:
    __slots__ = ("id", "kind", "channels", "stereo")

    def __init__(self, id_, kind, channels):
        self.id, self.kind, self.channels = id_, kind, tuple(channels)
        self.stereo = len(self.channels) == 2

    def src(self, i=0):
        return f"{self.kind}:{self.channels[i]}"


class Mixer:
    def __init__(self, device, config, clock=time.monotonic):
        self.dev = device
        self.cfg = config
        self.clock = clock
        self.listener = None            # callback(patch dict)
        self.toast = None               # callback(text)
        self._vol_confirmed = {}        # outpair -> clock() of last Audius volume write
        self._fade_until = {}           # outpair -> clock() when a takeover fade ends
        self._undo, self._redo = [], []
        self._gesture = None            # (id, label, snapshot before)
        self._dirty = set()
        self._send_index = {}
        for src in bf.ALL_SOURCES:
            for out in bf.OUTPUTS:
                self._send_index[bf.send_ctl(src, out)] = (src, out)
        self._out_of = {ch: pair[0] for pair in bf.OUTPUT_PAIRS for ch in pair}
        device.on_change = self.on_device_change

    # ------------------------------------------------------------------ structure
    @property
    def prefs(self):
        return self.cfg["prefs"]

    def strips(self):
        out = []
        for kind, pairs in (("in", bf.INPUT_PAIRS), ("pb", bf.OUTPUT_PAIRS)):
            for a, b in pairs:
                if self.cfg["links"].get(f"{kind}:{a}", False):
                    out.append(Strip(f"{kind}:{a}", kind, (a, b)))
                else:
                    out.append(Strip(f"{kind}:{a}", kind, (a,)))
                    out.append(Strip(f"{kind}:{b}", kind, (b,)))
        return out

    def strip(self, sid):
        for s in self.strips():
            if s.id == sid:
                return s
        raise KeyError(sid)

    def strip_of_channel(self, src):
        """The strip currently holding a source channel ('in:AN2' may live in 'in:AN1')."""
        kind, ch = src.split(":")
        for s in self.strips():
            if s.kind == kind and ch in s.channels:
                return s
        raise KeyError(src)

    def default_name(self, s):
        if s.kind == "in":
            return IN_PAIR_NAMES[s.channels[0]] if s.stereo else IN_NAMES[s.channels[0]]
        n = CHANNEL_NUMBER[s.channels[0]]
        if s.stereo:
            return "Computer" if n == 1 else f"Computer {n}/{n + 1}"
        return f"Computer {n}"

    def name_of(self, s):
        return self.cfg["names"].get(s.id) or self.default_name(s)

    def optical_is_spdif(self):
        return bool(self.dev.values.get(bf.OPTICAL_SPDIF, 0))

    def output_defaults(self, out):
        spdif = self.optical_is_spdif()
        return {
            "AN1": ("Speakers", "Outputs 1/2 · XLR", "speakers"),
            "PH3": ("Headphones", "Phones 3/4", "headphones"),
            "AS1": ("S/PDIF" if spdif else "ADAT 1/2", "Optical out", "optical"),
            "ADAT3": ("ADAT 3/4", "Optical out", "optical"),
            "ADAT5": ("ADAT 5/6", "Optical out", "optical"),
            "ADAT7": ("ADAT 7/8", "Optical out", "optical"),
        }[out]

    def output_visible(self, out):
        if out in ("AN1", "PH3"):
            return True
        if not self.prefs.get("show_optical"):
            return False
        return out == "AS1" or not self.optical_is_spdif()

    def strip_visible(self, s):
        ch = s.channels[0]
        if s.kind == "in":
            return ch in ("AN1", "AN2", "IN3", "IN4") or bool(self.prefs.get("show_optical"))
        return ch == "AN1" or ch == "AN2" or bool(self.prefs.get("show_all_playback"))

    # ------------------------------------------------------------------ logical values
    def _logical(self, ctl, out):
        """What a send is set to, looking through 'output off' and DIM memory."""
        mem = self.cfg["output_off"].get(out)
        if mem is None:
            mem = self.cfg["dim"].get(out)
        if mem is not None:
            return int(mem.get(ctl, 0))
        return int(self.dev.values.get(ctl, 0))

    def _logical_ctl(self, ctl):
        _, o = self._send_index[ctl]
        return self._logical(ctl, self._out_of[o])

    def _send_ctls(self, s, out):
        """(direct L, direct R, cross L->R, cross R->L) controls for a strip into an output pair."""
        o_l, o_r = OUT_PAIRS[out]
        if s.stereo:
            a, b = s.src(0), s.src(1)
            return (bf.send_ctl(a, o_l), bf.send_ctl(b, o_r), bf.send_ctl(a, o_r), bf.send_ctl(b, o_l))
        a = s.src(0)
        return (bf.send_ctl(a, o_l), bf.send_ctl(a, o_r))

    def _key(self, s, out):
        return f"{s.id}>{out}"

    def _send_raw(self, s, out):
        """(level raw, pan, muted) of a send, looking through mute and 'off' memory."""
        ctls = self._send_ctls(s, out)
        key = self._key(s, out)
        muted = self.cfg["send_mute"].get(key)
        if muted is not None:
            left, right = int(muted.get(ctls[0], 0)), int(muted.get(ctls[1], 0))
        else:
            left, right = self._logical(ctls[0], out), self._logical(ctls[1], out)
        pan = balance(left, right)
        if pan is None:
            pan = self.cfg["pan_memory"].get(key, 0.0)
        return max(left, right), pan, muted is not None

    def send_state(self, s, out):
        level, pan, muted = self._send_raw(s, out)
        return {"db": db_or_none(level), "pan": round(pan, 3), "muted": muted}

    def _undimmed(self, ctl):
        """A send's hardware value, as it would be without DIM (scenes and undo store these)."""
        _, o = self._send_index[ctl]
        mem = self.cfg["dim"].get(self._out_of[o])
        return int(mem.get(ctl, 0)) if mem is not None else int(self.dev.values.get(ctl, 0))

    def output_on(self, out):
        return out not in self.cfg["output_off"]

    def dimmed(self, out):
        return out in self.cfg["dim"]

    def _dim_factor(self):
        return 10 ** (float(self.prefs.get("dim_db", -20.0)) / 20)

    def _dim_value(self, raw):
        return bf.even(int(round(int(raw) * self._dim_factor())))

    def volume_raw(self, out):
        o_l, o_r = OUT_PAIRS[out]
        return self.dev.values[bf.volume_ctl(o_l)], self.dev.values[bf.volume_ctl(o_r)]

    def volume_known(self, out):
        """Whether Audius knows the output volume: it set it, and the driver still holds
        that value. A volume that was never written this boot reads 0 and lives only on
        the device (its knob and its own memory)."""
        mem = self.cfg["volumes"].get(out)
        if mem is None:
            return False
        left, right = self.volume_raw(out)
        return max(left, right) > 0 and abs(max(left, right) - bf.even(bf.db_to_raw(mem))) <= 2

    def volume_db(self, out):
        if not self.volume_known(out):
            return None
        return db_or_none(max(self.volume_raw(out)))

    def volume_fresh(self, out):
        t = self._vol_confirmed.get(out)
        return t is not None and self.clock() - t <= TAKEOVER_WINDOW

    def audible(self, out):
        if not self.output_on(out):
            return False
        if out in self.prefs.get("knob_outputs", ["PH3"]) and not self.volume_known(out):
            return True  # its volume lives on the device knob
        db = self.volume_db(out)
        return db is not None and db > AUDIBLE_DB

    def listen_mode(self):
        ph, sp = self.audible("PH3"), self.audible("AN1")
        return "both" if ph and sp else "headphones" if ph else "speakers" if sp else "none"

    # ------------------------------------------------------------------ writing
    def _apply(self, targets, out, s=None, fade=0.0, start=None):
        """Route send writes to mute memory, 'off' memory or the hardware."""
        key = self._key(s, out) if s is not None else None
        muted = self.cfg["send_mute"].get(key) if key else None
        off = self.cfg["output_off"].get(out)
        dim = self.cfg["dim"].get(out)
        for ctl, value in targets.items():
            if ctl in self.dev.poisoned:
                continue
            value = bf.even(max(0, min(bf.MAX_RAW, int(value))))
            if muted is not None and ctl in muted:
                muted[ctl] = value
            elif off is not None:
                if value:
                    off[ctl] = value
                else:
                    off.pop(ctl, None)
            else:
                if dim is not None:
                    if value:
                        dim[ctl] = value
                    else:
                        dim.pop(ctl, None)
                    value = self._dim_value(value)
                if fade > 0:
                    self.dev.ramp(ctl, value, fade, start=start)
                else:
                    self.dev.set(ctl, value)
            self._dirty.add(ctl)
        self.cfg.changed()

    def set_send(self, sid, out, db=None, pan=None, gesture=None, keep_db=False):
        """Set a send's level (dB, None for -inf) and/or pan. keep_db changes only the pan."""
        s = self.strip(sid)
        self._begin(gesture, f"{self.name_of(s)} level")
        cur_level, cur_pan, _ = self._send_raw(s, out)
        key = self._key(s, out)
        level = cur_level if keep_db else bf.db_to_raw(db)
        if pan is None:
            pan = cur_pan
        pan = max(-1.0, min(1.0, float(pan)))
        left, right = unbalance(level, pan)
        ctls = self._send_ctls(s, out)
        targets = {ctls[0]: left, ctls[1]: right}
        if level == 0:
            self.cfg["pan_memory"][key] = pan
        else:
            self.cfg["pan_memory"].pop(key, None)
        # A short ramp smooths large jumps (keyboard steps, typed values) without lag on drags.
        self._apply(targets, out, s, fade=0.03)
        self._emit()

    def set_send_mute(self, sid, out, muted, gesture=None):
        s = self.strip(sid)
        self._begin(gesture, f"Mute {self.name_of(s)}")
        key = self._key(s, out)
        ctls = self._send_ctls(s, out)
        mem = self.cfg["send_mute"]
        if muted and key not in mem:
            mem[key] = {c: self._logical(c, out) for c in ctls}
            self._apply({c: 0 for c in ctls}, out, None, fade=SWITCH_FADE)
        elif not muted and key in mem:
            stored = mem.pop(key)
            self._apply(stored, out, None, fade=SWITCH_FADE, start=0)
        self.cfg.changed()
        self._emit()

    def set_crosspoint(self, ctl, db, gesture=None):
        """Routing grid: one source channel into one output channel."""
        src, o = self._send_index[ctl]
        out = self._out_of[o]
        self._begin(gesture, "Routing")
        self._drop_mute_memory_for(ctl, out)
        self._apply({ctl: bf.db_to_raw(db)}, out, None, fade=0.03)
        self._emit()

    def _drop_mute_memory_for(self, ctl, out):
        for key, mem in list(self.cfg["send_mute"].items()):
            if key.endswith(f">{out}") and ctl in mem:
                del self.cfg["send_mute"][key]

    def set_output_on(self, out, on, gesture=None, emit=True):
        self._begin(gesture, "Switch output")
        o_l, o_r = OUT_PAIRS[out]
        ctls = [bf.send_ctl(src, o) for src in bf.ALL_SOURCES for o in (o_l, o_r)]
        mem = self.cfg["output_off"]
        ctls = [c for c in ctls if c not in self.dev.poisoned]
        if not on and out not in mem:
            dim = self.cfg["dim"].pop(out, None)     # off ends DIM; on comes back undimmed
            if dim is not None:
                mem[out] = {c: v for c, v in dim.items() if c in ctls}
            else:
                mem[out] = {c: self.dev.values[c] for c in ctls if self.dev.values[c] > 0}
            for c in ctls:
                if self.dev.values[c] > 0:
                    self.dev.ramp(c, 0, SWITCH_FADE)
                    self._dirty.add(c)
        elif on and out in mem:
            stored = mem.pop(out)
            dims = self.cfg["dim"]
            if dims and self.output_visible(out):     # DIM covers what you start hearing
                dims[out] = dict(stored)
            for c, v in stored.items():
                self.dev.ramp(c, self._dim_value(v) if out in dims else int(v), SWITCH_FADE, start=0)
                self._dirty.add(c)
        self._dirty.add("outputs")
        self.cfg.changed()
        if emit:
            self._emit()

    def set_dim(self, out, on, emit=True):
        """Lower an output by prefs.dim_db through its sends, like the device's DIM key.
        Not an undo step and not part of scenes: it's a monitoring state, like mute on a desk."""
        dim = self.cfg["dim"]
        o_l, o_r = OUT_PAIRS[out]
        ctls = [bf.send_ctl(src, o) for src in bf.ALL_SOURCES for o in (o_l, o_r)]
        if on and out not in dim and self.output_on(out):
            dim[out] = {c: self.dev.values[c] for c in ctls if self.dev.values[c] > 0}
            targets = {c: self._dim_value(v) for c, v in dim[out].items()}
        elif not on and out in dim:
            targets = dim.pop(out)
        else:
            return
        for c, v in targets.items():
            if c not in self.dev.poisoned:
                self.dev.ramp(c, int(v), SWITCH_FADE)
                self._dirty.add(c)
        self._dirty.add("outputs")
        self.cfg.changed()
        if emit:
            self._emit()

    def set_dim_all(self, on):
        """DIM what you hear: every visible output that's on, or undim them all."""
        for out in OUT_PAIRS:
            if not on or self.output_visible(out):
                self.set_dim(out, on, emit=False)
        self._emit()

    def _redim(self):
        """dim_db changed: move dimmed outputs to the new depth."""
        for mem in self.cfg["dim"].values():
            for c, v in mem.items():
                if c not in self.dev.poisoned:
                    self.dev.ramp(c, self._dim_value(v), SWITCH_FADE)
                    self._dirty.add(c)

    def set_listen(self, mode, gesture=None):
        """Listen on 'headphones', 'speakers' or 'both'."""
        want_ph = mode in ("headphones", "both")
        want_sp = mode in ("speakers", "both")
        gesture = gesture or "listen-" + uuid.uuid4().hex
        self._begin(gesture, "Listen on")
        self.set_output_on("PH3", want_ph, gesture=gesture, emit=False)
        self.set_output_on("AN1", want_sp, gesture=gesture, emit=False)
        if want_sp:
            db = self.volume_db("AN1")      # None when unknown (never set from Audius)
            if db is None or db <= AUDIBLE_DB:
                start = float(self.prefs.get("speaker_start_db", -40.0))
                self.set_volume("AN1", start, force_fade=True, emit=False)
                if self.toast:
                    self.toast(f"Speakers start at {start:.0f} dB. Raise them slowly.")
        self._emit()

    def set_volume(self, out, db, gesture=None, force_fade=False, emit=True):
        """Output volume. Safe against the hardware knob: unless Audius set this output
        recently, the change fades in from quiet instead of jumping."""
        limit = float(self.cfg["limits"].get(out, 0.0))
        if db is not None:
            db = min(float(db), limit)
        o_l, o_r = OUT_PAIRS[out]
        cur_l, cur_r = self.volume_raw(out)
        pan = (balance(cur_l, cur_r) or 0.0) if self.volume_known(out) else 0.0
        left, right = unbalance(bf.db_to_raw(db), pan)
        self.cfg["volumes"][out] = db if db is not None else -120.0
        self.cfg.changed()
        now = self.clock()
        fading = now < self._fade_until.get(out, 0.0)
        takeover = force_fade or (self.prefs.get("takeover_fade", True) and not self.volume_fresh(out))
        names = (bf.volume_ctl(o_l), bf.volume_ctl(o_r))
        if fading:
            remaining = self._fade_until[out] - now
            for n, v in zip(names, (left, right)):
                self.dev.ramp(n, v, remaining)
        elif takeover:
            floor = bf.db_to_raw(TAKEOVER_FLOOR_DB)
            for n, v in zip(names, (left, right)):
                self.dev.ramp(n, v, TAKEOVER_FADE, start=min(floor, v))
            self._fade_until[out] = now + TAKEOVER_FADE
        else:
            for n, v in zip(names, (left, right)):
                self.dev.ramp(n, v, 0.04)
        self._vol_confirmed[out] = now
        self._dirty.update(names)
        self._dirty.add("outputs")
        if emit:
            self._emit()

    def forget_volumes(self):
        """The window was away: the knob may have moved any volume."""
        if self._vol_confirmed:
            self._vol_confirmed.clear()
            self._dirty.add("outputs")
            self._emit()

    def expire(self):
        """Called periodically: report volumes whose takeover window ran out."""
        stale = [o for o, t in self._vol_confirmed.items() if self.clock() - t > TAKEOVER_WINDOW]
        for o in stale:
            del self._vol_confirmed[o]
        if stale:
            self._dirty.add("outputs")
            self._emit()

    def set_limit(self, out, db):
        self.cfg["limits"][out] = max(-40.0, min(bf.MAX_DB, float(db)))
        self.cfg.changed()
        self._dirty.add("outputs")
        self._emit()

    # ---- inputs
    def set_gain(self, ch, db, gesture=None):
        self._begin(gesture, "Gain")
        name = bf.gain_ctl(ch)
        new = bf.db_to_gain(ch, db)
        old = self.dev.values[name]
        steps = abs(new - old)
        if steps > 2:
            # Walk there: a sudden +30 dB on a monitored mic hurts.
            self.dev.ramp_linear(name, new, steps * GAIN_STEP_TIME)
        else:
            self.dev.set(name, new)
        self._dirty.add(name)
        self._emit()

    def set_switch(self, name, on, gesture=None, label="Setting"):
        allowed = {bf.p48_ctl(c) for c in bf.MIC_INPUTS} | {bf.pad_ctl(c) for c in bf.MIC_INPUTS} | {
            bf.OPTICAL_SPDIF, bf.SPDIF_PRO, bf.SPDIF_EMPHASIS}
        if name not in allowed:
            raise KeyError(name)
        if "48V" not in name and name.startswith("Mic"):
            self._begin(gesture, label)
        self.dev.set(name, 1 if on else 0)
        self._dirty.add(name)
        self._dirty.add("outputs")
        self._emit()

    def set_enum(self, name, index, gesture=None):
        allowed = {bf.sens_ctl(c) for c in bf.LINE_INPUTS} | {bf.CLOCK}
        if name not in allowed:
            raise KeyError(name)
        if name != bf.CLOCK:
            self._begin(gesture, "Input level")
        self.dev.set(name, int(index))
        self._dirty.add(name)
        self._emit()

    # ---- structure
    def set_link(self, pair_id, linked, gesture=None):
        kind, a = pair_id.split(":")
        pairs = bf.INPUT_PAIRS if kind == "in" else bf.OUTPUT_PAIRS
        pair = next(p for p in pairs if p[0] == a)
        if bool(self.cfg["links"].get(pair_id, False)) == bool(linked):
            return
        self._begin(gesture, "Stereo link")
        before = {o: (self._send_raw(self.strip_of_channel(f"{kind}:{pair[0]}"), o)[0],
                      self._send_raw(self.strip_of_channel(f"{kind}:{pair[1]}"), o)[0]) for o in OUT_PAIRS}
        self._clear_memories_for([f"{kind}:{pair[0]}", f"{kind}:{pair[1]}"])
        self.cfg["links"][pair_id] = bool(linked)
        if linked:
            s = self.strip(pair_id)
            for out, (level_a, level_b) in before.items():
                level = max(level_a, level_b)
                ctls = self._send_ctls(s, out)
                self._apply({ctls[0]: level, ctls[1]: level, ctls[2]: 0, ctls[3]: 0}, out, None, fade=SWITCH_FADE)
        # Unlinking needs no change: the stereo sends are exactly two hard-panned monos.
        self._dirty.add("strips")
        self.cfg.changed()
        self._emit()

    def _clear_memories_for(self, ids):
        for mem_name in ("send_mute", "pan_memory"):
            mem = self.cfg[mem_name]
            for key in list(mem):
                if key.split(">")[0] in ids:
                    del mem[key]

    def rename(self, ident, name):
        name = (name or "").strip()[:40]
        if name:
            self.cfg["names"][ident] = name
        else:
            self.cfg["names"].pop(ident, None)
        self.cfg.changed()
        self._dirty.add("strips")
        self._dirty.add("outputs")
        self._emit()

    def set_overview_sources(self, out, ids):
        valid = {s.id for s in self.strips()}
        self.cfg["overview_sources"][out] = [i for i in ids if i in valid][:8]
        self.cfg.changed()
        self._dirty.add("overview")
        self._emit()

    def set_pref(self, key, value):
        if key not in self.prefs and key not in ("knob_outputs",):
            raise KeyError(key)
        if key == "dim_db":
            value = max(-60.0, min(-3.0, float(value)))
        self.prefs[key] = value
        if key == "dim_db":
            self._redim()
        self.cfg.changed()
        self._dirty.update({"prefs", "strips", "outputs"})
        self._emit()

    # ------------------------------------------------------------------ scenes
    def _mix_state(self):
        return {
            "sends": {c: self._undimmed(c) for c in bf.SEND_CTLS},
            "links": copy.deepcopy(self.cfg["links"]),
            "output_off": copy.deepcopy(self.cfg["output_off"]),
            "send_mute": copy.deepcopy(self.cfg["send_mute"]),
            "pan_memory": copy.deepcopy(self.cfg["pan_memory"]),
        }

    def _restore_mix(self, state, fade=RECALL_FADE):
        dims = self.cfg["dim"]
        for out in [o for o in dims if o in state["output_off"]]:
            del dims[out]          # coming back switched off: its sends go to 0 below
        if dims:                   # coming back on while DIM is active: dimmed too
            for out in self.cfg["output_off"]:
                if out not in state["output_off"] and self.output_visible(out):
                    dims[out] = {}
        for c, v in state["sends"].items():
            v = int(v)
            _, o = self._send_index[c]
            dim = dims.get(self._out_of[o])
            if dim is not None:    # DIM stays on through recall and undo
                if v:
                    dim[c] = v
                else:
                    dim.pop(c, None)
                v = self._dim_value(v)
            if self.dev.values.get(c) != v:
                self.dev.ramp(c, v, fade, start=0 if self.dev.values.get(c, 0) == 0 else None)
                self._dirty.add(c)
        for k in ("links", "output_off", "send_mute", "pan_memory"):
            self.cfg.data[k] = copy.deepcopy(state[k])
        self._dirty.update({"strips", "outputs"})
        self.cfg.changed()

    def save_scene(self, name):
        name = (name or "").strip()[:40] or f"Scene {len(self.cfg['scenes']) + 1}"
        scene = {"id": uuid.uuid4().hex[:8], "name": name, "created": int(time.time()), "mix": self._mix_state()}
        self.cfg["scenes"].append(scene)
        self.cfg.changed()
        self._dirty.add("scenes")
        self._emit()
        return scene["id"]

    def update_scene(self, sid):
        for sc in self.cfg["scenes"]:
            if sc["id"] == sid:
                sc["mix"] = self._mix_state()
        self.cfg.changed()
        self._dirty.add("scenes")
        self._emit()

    def recall_scene(self, sid):
        scene = next((sc for sc in self.cfg["scenes"] if sc["id"] == sid), None)
        if scene is None:
            return
        self._begin(None, f"Recall “{scene['name']}”")
        self._restore_mix(scene["mix"])
        self._commit()
        self._emit()

    def rename_scene(self, sid, name):
        for sc in self.cfg["scenes"]:
            if sc["id"] == sid and (name or "").strip():
                sc["name"] = name.strip()[:40]
        self.cfg.changed()
        self._dirty.add("scenes")
        self._emit()

    def delete_scene(self, sid):
        self.cfg.data["scenes"] = [sc for sc in self.cfg["scenes"] if sc["id"] != sid]
        self.cfg.changed()
        self._dirty.add("scenes")
        self._emit()

    # ------------------------------------------------------------------ undo
    def _undo_state(self):
        st = self._mix_state()
        st["inputs"] = {n: self.dev.values[n] for n in
                        [bf.gain_ctl(c) for c in bf.MIC_INPUTS + bf.LINE_INPUTS]
                        + [bf.pad_ctl(c) for c in bf.MIC_INPUTS] + [bf.sens_ctl(c) for c in bf.LINE_INPUTS]}
        return st

    def _begin(self, gesture, label):
        """Start an undo step. Calls sharing a gesture id merge into one step."""
        if gesture is not None and self._gesture is not None and self._gesture[0] == gesture:
            return
        self._commit()
        self._gesture = (gesture, label, self._undo_state())
        if gesture is None:
            # Discrete action: commit after the caller's changes, on the next begin/undo.
            self._gesture = ("once-" + uuid.uuid4().hex, label, self._gesture[2])

    def _commit(self):
        if self._gesture is None:
            return
        _, label, before = self._gesture
        self._gesture = None
        if before != self._undo_state():
            self._undo.append((label, before))
            del self._undo[:-100]
            self._redo.clear()
            self._dirty.add("undo")

    def end_gesture(self):
        self._commit()
        self._emit()

    def _restore_undo_state(self, st):
        self._restore_mix(st, fade=0.12)
        for n, v in st["inputs"].items():
            if self.dev.values.get(n) != v:
                self.dev.set(n, v)
                self._dirty.add(n)

    def undo(self):
        self._commit()
        if not self._undo:
            return
        label, before = self._undo.pop()
        self._redo.append((label, self._undo_state()))
        self._restore_undo_state(before)
        self._dirty.add("undo")
        if self.toast:
            self.toast(f"Undone: {label}")
        self._emit()

    def redo(self):
        self._commit()
        if not self._redo:
            return
        label, after = self._redo.pop()
        self._undo.append((label, self._undo_state()))
        self._restore_undo_state(after)
        self._dirty.add("undo")
        self._emit()

    # ------------------------------------------------------------------ resync
    def resend_all(self, include_volumes=False):
        names = list(bf.SEND_CTLS) + [bf.gain_ctl(c) for c in bf.MIC_INPUTS + bf.LINE_INPUTS] + [
            bf.pad_ctl(c) for c in bf.MIC_INPUTS] + [bf.sens_ctl(c) for c in bf.LINE_INPUTS] + [
            bf.CLOCK, bf.OPTICAL_SPDIF, bf.SPDIF_PRO, bf.SPDIF_EMPHASIS]
        if include_volumes:
            names += list(bf.VOLUME_CTLS)
        self.dev.resend(names)
        return len(names)

    # ------------------------------------------------------------------ external changes
    def on_device_change(self, changed):
        for ctl, value in changed.items():
            self._dirty.add(ctl)
            if ctl not in self._send_index:
                continue
            _, o = self._send_index[ctl]
            out = self._out_of[o]
            dim = self.cfg["dim"].get(out)
            if dim is not None:
                # Set elsewhere while dimmed: keep it, as a dimmed level.
                logical = bf.even(min(bf.MAX_RAW, int(round(value / self._dim_factor()))))
                if logical:
                    dim[ctl] = logical
                else:
                    dim.pop(ctl, None)
            if value > 0:
                if out in self.cfg["output_off"]:
                    del self.cfg["output_off"][out]      # someone switched it on elsewhere
                    self._dirty.add("outputs")
                self._drop_mute_memory_for(ctl, out)
        self.cfg.changed()
        self._emit()

    # ------------------------------------------------------------------ views
    def view(self):
        return {
            "device": self.device_view(),
            "inputs": self.inputs_view(),
            "outputs": self.outputs_view(),
            "listen": self.listen_mode(),
            "strips": self.strips_view(),
            "sends": {s.id: {o: self.send_state(s, o) for o in OUT_PAIRS} for s in self.strips()},
            "raw": {c: self._logical_ctl(c) for c in bf.SEND_CTLS},   # through "output off" memory
            "overview_sources": self.cfg["overview_sources"],
            "scenes": [{"id": sc["id"], "name": sc["name"], "created": sc["created"]} for sc in self.cfg["scenes"]],
            "prefs": self.prefs,
            "undo": self.undo_view(),
            "locked": sorted(self.dev.poisoned),
        }

    def device_view(self):
        v = self.dev.values
        return {
            "connected": True, "demo": self.dev.demo, "name": self.dev.name, "serial": self.dev.serial,
            "rate": self.dev.stream_rate(),
            "clock": "internal" if v.get(bf.CLOCK) else "autosync",
            "optical_out": "spdif" if v.get(bf.OPTICAL_SPDIF) else "adat",
            "spdif_pro": bool(v.get(bf.SPDIF_PRO)), "spdif_emphasis": bool(v.get(bf.SPDIF_EMPHASIS)),
        }

    def inputs_view(self):
        v = self.dev.values
        out = []
        for ch in bf.MIC_INPUTS + bf.LINE_INPUTS:
            mic = ch in bf.MIC_INPUTS
            item = {"ch": ch, "id": f"in:{ch}", "kind": "mic" if mic else "line",
                    "name": self.cfg["names"].get(f"in:{ch}") or IN_NAMES[ch],
                    "gain_db": bf.gain_to_db(ch, v[bf.gain_ctl(ch)]),
                    "gain_max": bf.MIC_GAIN_MAX if mic else bf.LINE_GAIN_MAX / 2, "gain_step": 1 if mic else 0.5}
            if mic:
                item["p48"] = bool(v[bf.p48_ctl(ch)])
                item["pad"] = bool(v[bf.pad_ctl(ch)])
            else:
                item["sens"] = "+4dBu" if v[bf.sens_ctl(ch)] else "-10dBV"
            out.append(item)
        return out

    def outputs_view(self):
        out = []
        for pair in bf.OUTPUT_PAIRS:
            o = pair[0]
            name, detail, kind = self.output_defaults(o)
            left, right = self.volume_raw(o)
            out.append({
                "id": o, "channels": list(pair), "name": self.cfg["names"].get(o) or name, "default_name": name,
                "detail": detail, "kind": kind, "visible": self.output_visible(o), "on": self.output_on(o),
                "audible": self.audible(o), "dimmed": self.dimmed(o),
                "volume_db": self.volume_db(o), "volume_known": self.volume_known(o),
                "balance": round(balance(left, right) or 0.0, 3), "volume_fresh": self.volume_fresh(o),
                "limit_db": float(self.cfg["limits"].get(o, 0.0)),
                "knob": o in self.prefs.get("knob_outputs", ["PH3"]),
            })
        return out

    def strips_view(self):
        res = []
        for s in self.strips():
            res.append({"id": s.id, "kind": s.kind, "channels": list(s.channels), "stereo": s.stereo,
                        "name": self.name_of(s), "default_name": self.default_name(s),
                        "visible": self.strip_visible(s), "pair": f"{s.kind}:{self._pair_first(s)}",
                        "meters": [f"{s.kind}:{c}" for c in s.channels]})
        return res

    def _pair_first(self, s):
        pairs = bf.INPUT_PAIRS if s.kind == "in" else bf.OUTPUT_PAIRS
        return next(p[0] for p in pairs if s.channels[0] in p)

    def undo_view(self):
        return {"can_undo": bool(self._undo), "can_redo": bool(self._redo),
                "undo_label": self._undo[-1][0] if self._undo else None,
                "redo_label": self._redo[-1][0] if self._redo else None}

    def _emit(self):
        if not self._dirty:
            return
        dirty, self._dirty = self._dirty, set()
        patch = {}
        sends_ctls = [c for c in dirty if c in self._send_index]
        if sends_ctls:
            patch["raw"] = {c: self._logical_ctl(c) for c in sends_ctls}
        structural = dirty & {"strips", "prefs"}
        if structural:
            patch["strips"] = self.strips_view()
            patch["sends"] = {s.id: {o: self.send_state(s, o) for o in OUT_PAIRS} for s in self.strips()}
            patch["prefs"] = self.prefs
        elif sends_ctls:
            touched = {}
            for c in sends_ctls:
                src, o = self._send_index[c]
                s = self.strip_of_channel(src)
                touched.setdefault(s.id, (s, set()))[1].add(self._out_of[o])
            patch["sends"] = {sid: {o: self.send_state(s, o) for o in outs} for sid, (s, outs) in touched.items()}
        input_names = {bf.gain_ctl(c) for c in bf.MIC_INPUTS + bf.LINE_INPUTS} | {
            bf.p48_ctl(c) for c in bf.MIC_INPUTS} | {bf.pad_ctl(c) for c in bf.MIC_INPUTS} | {
            bf.sens_ctl(c) for c in bf.LINE_INPUTS}
        if dirty & input_names or "strips" in dirty:
            patch["inputs"] = self.inputs_view()
        if dirty & set(bf.VOLUME_CTLS) or dirty & {"outputs", "strips", "prefs"} or sends_ctls:
            patch["outputs"] = self.outputs_view()
            patch["listen"] = self.listen_mode()
        if sends_ctls:
            patch["locked"] = sorted(self.dev.poisoned)
        if dirty & {bf.CLOCK, bf.OPTICAL_SPDIF, bf.SPDIF_PRO, bf.SPDIF_EMPHASIS}:
            patch["device"] = self.device_view()
            patch["outputs"] = self.outputs_view()
        if "scenes" in dirty:
            patch["scenes"] = [{"id": sc["id"], "name": sc["name"], "created": sc["created"]}
                               for sc in self.cfg["scenes"]]
        if "overview" in dirty:
            patch["overview_sources"] = self.cfg["overview_sources"]
        patch["undo"] = self.undo_view()
        if self.listener:
            self.listener(patch)
