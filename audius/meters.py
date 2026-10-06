"""Live levels from PipeWire.

The Babyface has no meters the computer can read in Class Compliant mode, so
Audius measures the audio streams: the capture node (hardware inputs) and the
playback node's monitor (what the computer sends). The DSP's monitor mix itself
can't be measured. A capture stream lights GNOME's microphone indicator, so the
meters only run while the window is visible.
"""
import logging
import math
import random
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

from . import babyface as bf  # noqa: E402

log = logging.getLogger(__name__)
INTERVAL_NS = 33_333_333     # ~30 updates per second
FLOOR = -100.0


class Meters:
    def __init__(self, on_levels):
        Gst.init(None)
        self.on_levels = on_levels      # callback({channel id: (peak dBFS, rms dBFS)})
        self._pipelines = []
        self._restart_id = None
        self._nodes = None
        self.channels = []

    @property
    def running(self):
        return bool(self._pipelines)

    def start(self, nodes):
        self.stop()
        self._nodes = nodes
        self.channels = []
        for kind, role in (("source", "in"), ("sink", "pb")):
            node = nodes.get(kind)
            if not node or not node.get("name"):
                continue
            n = int(node["channels"])
            table = bf.INPUTS if role == "in" else bf.OUTPUTS
            names = [f"{role}:{table[i]}" for i in range(min(n, len(table)))]
            props = ["node.name=audius-meter-" + role, "media.role=Production", "node.latency=1024/48000",
                     "node.dont-reconnect=true"]
            if role == "pb":
                props += ["stream.capture.sink=true", "node.passive=true"]
            desc = (f'pipewiresrc target-object="{node["name"]}" client-name=Audius '
                    f'stream-properties="props,{",".join(props)}" '
                    f"! audio/x-raw,channels={n} ! audioconvert ! audio/x-raw,format=F32LE "
                    f"! level interval={INTERVAL_NS} post-messages=true ! fakesink sync=false async=false")
            try:
                p = Gst.parse_launch(desc)
            except GLib.Error as e:
                log.warning("meter pipeline: %s", e)
                continue
            bus = p.get_bus()
            bus.add_signal_watch()
            bus.connect("message", self._on_message, names)
            if p.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                log.warning("meter pipeline for %s failed to start", node["name"])
                p.set_state(Gst.State.NULL)
                continue
            self._pipelines.append(p)
            self.channels += names

    def stop(self):
        if self._restart_id:
            GLib.source_remove(self._restart_id)
            self._restart_id = None
        for p in self._pipelines:
            p.get_bus().remove_signal_watch()
            p.set_state(Gst.State.NULL)
        self._pipelines = []

    def _on_message(self, bus, msg, names):
        t = msg.type
        if t == Gst.MessageType.ELEMENT:
            s = msg.get_structure()
            if s is None or s.get_name() != "level":
                return
            peaks, rms = s.get_value("peak"), s.get_value("rms")
            out = {}
            for i, name in enumerate(names):
                if i < len(peaks):
                    out[name] = (max(FLOOR, _finite(peaks[i])), max(FLOOR, _finite(rms[i])))
            self.on_levels(out)
        elif t in (Gst.MessageType.ERROR, Gst.MessageType.EOS):
            if t == Gst.MessageType.ERROR:
                err, _ = msg.parse_error()
                log.info("meter stream ended: %s", err.message)
            if self._restart_id is None and self._nodes:
                self._restart_id = GLib.timeout_add_seconds(3, self._restart)

    def _restart(self):
        self._restart_id = None
        if self._nodes:
            self.start(self._nodes)
        return False


def _finite(v):
    return v if isinstance(v, (int, float)) and math.isfinite(v) else FLOOR


class DemoMeters:
    """Plausible signals for --demo: a voice on Mic 1, music from the computer."""

    def __init__(self, on_levels):
        self.on_levels = on_levels
        self._id = None
        self.channels = ["in:AN1", "in:AN2", "pb:AN1", "pb:AN2"]
        self._t0 = time.monotonic()
        self._voice = -60.0
        self._rng = random.Random(7)

    @property
    def running(self):
        return self._id is not None

    def start(self, nodes=None):
        if self._id is None:
            self._id = GLib.timeout_add(33, self._tick)

    def stop(self):
        if self._id is not None:
            GLib.source_remove(self._id)
            self._id = None

    def _tick(self):
        t = time.monotonic() - self._t0
        r = self._rng
        speaking = math.sin(t * 0.9) + 0.35 * math.sin(t * 2.3) > -0.2
        target = -14 + 6 * math.sin(t * 7.1) * math.sin(t * 3.3) if speaking else -63
        self._voice += (target - self._voice) * (0.55 if target > self._voice else 0.18)
        voice = self._voice + r.uniform(-1.5, 1.5)
        beat = 1.0 if (t * 2.0) % 1.0 < 0.12 else 0.0
        music_l = -17 + 4 * math.sin(t * 0.37) + 7 * beat + r.uniform(-2, 2)
        music_r = music_l - 1.2 + r.uniform(-1.5, 1.5)
        self.on_levels({
            "in:AN1": (voice, voice - 9), "in:AN2": (-104 + r.uniform(-1, 1), -110),
            "pb:AN1": (music_l, music_l - 8), "pb:AN2": (music_r, music_r - 8),
        })
        return True
