import math
import tempfile
import unittest
from pathlib import Path

from audius import babyface as bf
from audius import mixer as mx
from audius.config import Config


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_mixer():
    tmp = tempfile.mkdtemp()
    cfg = Config(Path(tmp) / "config.json", autosave=False)
    dev = bf.DemoDevice()
    clock = Clock()
    m = mx.Mixer(dev, cfg, clock=clock)
    patches = []
    m.listener = patches.append
    toasts = []
    m.toast = toasts.append
    return m, dev, cfg, clock, patches, toasts


class Conversions(unittest.TestCase):
    def test_db_raw(self):
        self.assertEqual(bf.db_to_raw(0), 32768)
        self.assertEqual(bf.db_to_raw(None), 0)
        self.assertEqual(bf.db_to_raw(-math.inf), 0)
        self.assertEqual(bf.db_to_raw(12), bf.MAX_RAW)
        self.assertAlmostEqual(bf.raw_to_db(65536), 6.0206, places=3)
        self.assertEqual(bf.raw_to_db(0), -math.inf)
        for db in (-50, -12.5, -3, 0, 3, 6):
            # one raw step is ~0.08 dB at -50 dB and ~0.0003 dB near 0 dB
            self.assertAlmostEqual(bf.raw_to_db(bf.db_to_raw(db)), db, delta=0.05 if db < -40 else 0.005)

    def test_control_names_match_kernel(self):
        self.assertEqual(bf.send_ctl("in:AN1", "PH3"), "Mic-AN1-PH3 Playback Volume")
        self.assertEqual(bf.send_ctl("in:IN3", "AN1"), "Line-IN3-AN1 Playback Volume")
        self.assertEqual(bf.send_ctl("in:ADAT5", "AS2"), "Line-ADAT5-AS2 Playback Volume")
        self.assertEqual(bf.send_ctl("pb:AN2", "PH4"), "PCM-AN2-PH4 Playback Volume")
        self.assertEqual(bf.gain_ctl("IN4"), "Line-IN4 Gain")
        self.assertEqual(bf.sens_ctl("IN3"), "Line-IN3 Sens.")
        self.assertEqual(len(bf.EXPECTED_CTLS), 314)
        self.assertEqual(len(set(bf.EXPECTED_CTLS)), 314)

    def test_gain(self):
        self.assertEqual(bf.db_to_gain("AN1", 26.4), 26)
        self.assertEqual(bf.db_to_gain("AN1", 99), 65)
        self.assertEqual(bf.db_to_gain("IN3", 4.5), 9)
        self.assertEqual(bf.gain_to_db("IN3", 9), 4.5)
        self.assertEqual(bf.db_to_gain("IN3", 20), 18)

    def test_ramp(self):
        r = bf.Ramp(0, 32768, 0.0, 1.0)
        self.assertEqual(r.value_at(-1), bf.db_to_raw(-60))
        self.assertEqual(r.value_at(1.0), 32768)
        vals = [r.value_at(t / 10) for t in range(11)]
        self.assertEqual(vals, sorted(vals))
        down = bf.Ramp(32768, 0, 0.0, 0.5)
        self.assertEqual(down.value_at(0.5), 0)
        lin = bf.Ramp(10, 40, 0.0, 1.0, linear=True)
        self.assertEqual(lin.value_at(0.5), 25)

    def test_balance_roundtrip(self):
        for level in (1, 1000, 32768, 65536):
            for pan in (-1, -0.5, -0.1, 0, 0.3, 1):
                left, right = mx.unbalance(level, pan)
                self.assertEqual(max(left, right), level)
                self.assertAlmostEqual(mx.balance(left, right), pan, delta=2.0 / level + 1e-9)
        self.assertIsNone(mx.balance(0, 0))


class MixerModel(unittest.TestCase):
    def setUp(self):
        self.m, self.dev, self.cfg, self.clock, self.patches, self.toasts = make_mixer()

    def st(self, sid, out):
        return self.m.send_state(self.m.strip(sid), out)

    def test_initial_state_decodes_users_setup(self):
        comp = self.st("pb:AN1", "PH3")
        self.assertAlmostEqual(comp["db"], 6.02, places=2)
        self.assertEqual(comp["pan"], 0)
        mic = self.st("in:AN1", "PH3")
        self.assertAlmostEqual(mic["db"], 6.02, places=2)
        self.assertEqual(mic["pan"], 0)
        self.assertIsNone(self.st("in:AN1", "AN1")["db"])
        # Speakers sit at -90 dB, headphones are on the knob.
        self.assertEqual(self.m.listen_mode(), "headphones")

    def test_pan_and_memory(self):
        self.m.set_send("in:AN1", "PH3", db=0, pan=0.5)
        left = self.dev.values[bf.send_ctl("in:AN1", "PH3")]
        right = self.dev.values[bf.send_ctl("in:AN1", "PH4")]
        self.assertEqual(right, 32768)
        self.assertEqual(left, 16384)
        self.m.set_send("in:AN1", "PH3", db=None)
        self.assertEqual(self.dev.values[bf.send_ctl("in:AN1", "PH4")], 0)
        self.assertEqual(self.st("in:AN1", "PH3")["pan"], 0.5)
        self.m.set_send("in:AN1", "PH3", db=-6)
        self.assertAlmostEqual(self.st("in:AN1", "PH3")["pan"], 0.5, places=2)

    def test_pan_only(self):
        self.m.set_send("pb:AN1", "AN1", pan=-0.25, keep_db=True)
        st = self.st("pb:AN1", "AN1")
        self.assertAlmostEqual(st["db"], 6.02, places=2)
        self.assertAlmostEqual(st["pan"], -0.25, places=3)

    def test_mute(self):
        c = bf.send_ctl("in:AN1", "PH3")
        self.m.set_send_mute("in:AN1", "PH3", True)
        self.assertEqual(self.dev.values[c], 0)
        self.assertTrue(self.st("in:AN1", "PH3")["muted"])
        self.assertAlmostEqual(self.st("in:AN1", "PH3")["db"], 6.02, places=2)
        # moving a muted fader updates what comes back, like TotalMix
        self.m.set_send("in:AN1", "PH3", db=0)
        self.assertEqual(self.dev.values[c], 0)
        self.m.set_send_mute("in:AN1", "PH3", False)
        self.assertEqual(self.dev.values[c], 32768)

    def test_output_off_memory(self):
        c = bf.send_ctl("pb:AN1", "PH3")
        self.m.set_output_on("PH3", False)
        self.assertEqual(self.dev.values[c], 0)
        self.assertFalse(self.m.output_on("PH3"))
        self.assertAlmostEqual(self.st("pb:AN1", "PH3")["db"], 6.02, places=2)
        self.m.set_send("pb:AN1", "PH3", db=-10)          # adjusted while off
        self.assertEqual(self.dev.values[c], 0)
        self.m.set_output_on("PH3", True)
        self.assertEqual(self.dev.values[c], bf.even(bf.db_to_raw(-10)))

    def test_listen_on_speakers_starts_quiet(self):
        self.m.set_listen("speakers")
        self.assertFalse(self.m.output_on("PH3"))
        self.assertTrue(self.m.output_on("AN1"))
        self.assertAlmostEqual(self.m.volume_db("AN1"), -40, places=1)
        self.assertEqual(self.m.listen_mode(), "speakers")
        self.assertTrue(any("Speakers start" in t for t in self.toasts))
        # the speaker volume went through a fade from the floor
        name, start, end, dur = self.dev.ramps[-1]
        self.assertEqual(start, bf.db_to_raw(mx.TAKEOVER_FLOOR_DB))
        self.m.set_listen("both")
        self.assertEqual(self.m.listen_mode(), "both")
        self.m.undo()
        self.assertEqual(self.m.listen_mode(), "speakers")

    def test_volume_takeover_and_limit(self):
        self.m.set_volume("PH3", -20)
        name, start, end, dur = self.dev.ramps[-1]
        self.assertEqual(dur, mx.TAKEOVER_FADE)
        self.assertEqual(start, bf.db_to_raw(mx.TAKEOVER_FLOOR_DB))
        self.clock.t += 1.0                          # after the fade, within the window
        self.m.set_volume("PH3", -18)
        self.assertLess(self.dev.ramps[-1][3], 0.1)
        self.clock.t += mx.TAKEOVER_WINDOW + 1       # knob may have moved
        self.m.set_volume("PH3", -17)
        self.assertEqual(self.dev.ramps[-1][3], mx.TAKEOVER_FADE)
        self.m.set_volume("PH3", 6)                  # ceiling defaults to 0 dB
        self.assertAlmostEqual(self.m.volume_db("PH3"), 0.0, places=2)

    def test_drag_during_fade_keeps_fading(self):
        self.m.set_volume("PH3", -20)
        self.clock.t += 0.2
        self.m.set_volume("PH3", -15)
        self.assertAlmostEqual(self.dev.ramps[-1][3], mx.TAKEOVER_FADE - 0.2, places=6)

    def test_undo_gesture_merges(self):
        before = self.dev.values[bf.send_ctl("in:AN1", "PH3")]
        for db in (0, -3, -6, -9):
            self.m.set_send("in:AN1", "PH3", db=db, gesture="g1")
        self.m.end_gesture()
        self.assertTrue(self.m.undo_view()["can_undo"])
        self.m.undo()
        self.assertEqual(self.dev.values[bf.send_ctl("in:AN1", "PH3")], before)
        self.assertFalse(self.m.undo_view()["can_undo"])
        self.m.redo()
        self.assertEqual(self.dev.values[bf.send_ctl("in:AN1", "PH3")], bf.even(bf.db_to_raw(-9)))

    def test_scenes(self):
        sid = self.m.save_scene("Listening")
        self.m.set_send("in:AN1", "PH3", db=None)
        self.m.set_output_on("AN1", False)
        self.m.recall_scene(sid)
        self.assertAlmostEqual(self.st("in:AN1", "PH3")["db"], 6.02, places=2)
        self.assertTrue(self.m.output_on("AN1"))
        self.m.undo()
        self.assertIsNone(self.st("in:AN1", "PH3")["db"])
        self.m.rename_scene(sid, "Evening")
        self.assertEqual(self.m.view()["scenes"][0]["name"], "Evening")
        self.m.delete_scene(sid)
        self.assertEqual(self.m.view()["scenes"], [])

    def test_link_mono_pair(self):
        self.m.set_send("in:AN2", "PH3", db=-6)
        self.m.set_link("in:AN1", True)
        st = self.st("in:AN1", "PH3")
        self.assertAlmostEqual(st["db"], 6.02, places=2)
        self.assertEqual(self.dev.values[bf.send_ctl("in:AN1", "PH4")], 0)   # cross term cleared
        self.assertEqual(self.dev.values[bf.send_ctl("in:AN2", "PH4")], bf.MAX_RAW)
        self.m.set_link("in:AN1", False)
        self.assertAlmostEqual(self.st("in:AN1", "PH3")["pan"], -1.0)
        self.assertAlmostEqual(self.st("in:AN2", "PH3")["pan"], 1.0)

    def test_external_change_switches_output_back_on(self):
        self.m.set_output_on("PH3", False)
        c = bf.send_ctl("pb:AN1", "PH3")
        self.dev.values[c] = 1000
        self.m.on_device_change({c: 1000})
        self.assertTrue(self.m.output_on("PH3"))
        self.assertIn("raw", self.patches[-1])

    def test_big_gain_jump_walks(self):
        self.m.set_gain("AN1", 60)
        name, start, end, dur = self.dev.ramps[-1]
        self.assertEqual((name, end), ("Mic-AN1 Gain", 60))
        self.assertAlmostEqual(dur, 34 * mx.GAIN_STEP_TIME)
        self.m.set_gain("AN1", 61)
        self.assertEqual(self.dev.values["Mic-AN1 Gain"], 61)

    def test_view_is_json_safe(self):
        import json
        v = self.m.view()
        json.dumps(v)
        self.assertEqual(len(v["raw"]), 288)
        self.assertEqual(v["listen"], "headphones")
        names = [s["name"] for s in v["strips"] if s["visible"]]
        self.assertEqual(names[:4], ["Mic 1", "Mic 2", "Instrument 3", "Instrument 4"])
        self.assertIn("Computer", names)

    def test_resend_skips_phantom_and_volumes(self):
        n = self.m.resend_all()
        self.assertNotIn("Mic-AN1 48V", self.dev.resent)
        self.assertNotIn("Main-Out PH3", self.dev.resent)
        self.assertEqual(n, len(self.dev.resent))
        self.m.resend_all(include_volumes=True)
        self.assertIn("Main-Out PH3", self.dev.resent)


class KernelBugWorkaround(unittest.TestCase):
    """The driver packs `index | value << 9` with a 10-bit index (see babyface.py)."""

    def setUp(self):
        self.m, self.dev, self.cfg, self.clock, self.patches, self.toasts = make_mixer()

    def test_reads_are_normalized(self):
        self.assertEqual(bf.normalize("Main-Out PH3", 1), (0, False))            # never written
        self.assertEqual(bf.normalize("Main-Out AN1", 20001), (20000, False))
        self.assertEqual(bf.normalize("Mic-AN1-PH3 Playback Volume", 65536), (65536, False))
        self.assertEqual(bf.normalize("Mic-AN1-PH3 Playback Volume", 1), (0, True))   # poisoned
        self.assertEqual(bf.normalize("Mic-AN1 Gain", 27), (27, False))           # other controls untouched

    def test_only_even_values_reach_volume_controls(self):
        for db in (-59.3, -33.1, -6.7, -0.1, 0.0, 3.3, 6.0):
            self.m.set_send("in:AN1", "PH3", db=db, pan=0.37)
            self.m.set_volume("PH3", db)
        self.m.set_listen("speakers")
        self.m.set_listen("both")
        for name in bf.EVEN_ONLY:
            self.assertEqual(self.dev.values[name] % 2, 0, name)
        for name, start, end, dur in self.dev.ramps:
            if name in bf.EVEN_ONLY:
                self.assertEqual(end % 2, 0, name)

    def test_unknown_volumes(self):
        outs = {o["id"]: o for o in self.m.view()["outputs"]}
        self.assertIsNone(outs["PH3"]["volume_db"])
        self.assertFalse(outs["AN1"]["volume_known"])
        self.assertEqual(self.m.listen_mode(), "headphones")   # headphones live on the knob
        self.m.set_volume("PH3", -20)
        self.assertTrue(self.m.volume_known("PH3"))
        self.assertAlmostEqual(self.m.volume_db("PH3"), -20, places=1)
        # someone (alsactl, alsamixer) changed it behind our back -> unknown again
        for ch in ("Main-Out PH3", "Main-Out PH4"):
            self.dev.values[ch] = 2000
        self.assertFalse(self.m.volume_known("PH3"))

    def test_poisoned_crosspoints_are_never_written(self):
        c = bf.send_ctl("in:AN1", "PH3")
        self.dev.poisoned.add(c)
        before = self.dev.values[c]
        self.m.set_crosspoint(c, -20)
        self.m.set_send("in:AN1", "PH3", db=-12)
        self.m.set_output_on("PH3", False)
        self.m.set_output_on("PH3", True)
        self.assertEqual(self.dev.values[c], before)
        self.assertIn(c, self.m.view()["locked"])


if __name__ == "__main__":
    unittest.main()
