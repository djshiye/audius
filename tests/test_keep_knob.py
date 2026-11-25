import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from audius import bootstate

spec = importlib.util.spec_from_file_location("keep_knob", ROOT / "tools" / "keep-knob-volumes.py")
keep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keep)


def control(n, name, value, index=False):
    idx = "\t\tindex 0\n" if index else ""
    return f"\tcontrol.{n} {{\n\t\tiface MIXER\n\t\tname '{name}'\n{idx}\t\tvalue {value}\n\t}}\n"


STATE = (
    "state.Generic {\n" + control(1, "Main-Out PH3", 8045) + control(2, "Master Playback Volume", 40) + "}\n"
    "state.Pro73000526 {\n"
    + control(51, "Mic-AN1-PH3 Playback Volume", 65536)
    + control(291, "Main-Out AN1", 1)
    + control(292, "Main-Out AN2", 1)
    + control(293, "Main-Out PH3", 8045)
    + control(294, "Main-Out PH4", 8045, index=True)
    + control(295, "Main-Out AS1", 32769)
    + control(303, "Mic-AN1 Gain", 27)
    + "}\n"
)


class KeepKnob(unittest.TestCase):
    def run_on(self, text, mode=0o644):
        d = tempfile.mkdtemp()
        path = Path(d) / "asound.state"
        path.write_text(text)
        os.chmod(path, mode)
        rc = keep.main([str(path)], flag=Path(d) / "flag")
        return rc, path

    def test_resets_only_babyface_main_outs(self):
        rc, path = self.run_on(STATE, 0o600)
        self.assertEqual(rc, 0)
        out = path.read_text()
        bf = out[out.index("state.Pro73000526"):]
        generic = out[:out.index("state.Pro73000526")]
        for name in ("Main-Out AN1", "Main-Out AN2", "Main-Out PH3", "Main-Out PH4", "Main-Out AS1"):
            self.assertRegex(bf, rf"name '{name}'\n(\t\tindex 0\n)?\t\tvalue 1\n")
        expected = STATE.replace("value 8045", "value 1").replace("value 32769", "value 1")
        expected = generic + expected[expected.index("state.Pro73000526"):]
        self.assertEqual(out, expected)
        self.assertIn(control(1, "Main-Out PH3", 8045), generic)   # another card's control alone
        self.assertIn("value 65536", out)                   # crosspoints alone
        self.assertIn("value 27", out)                      # gain alone
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)   # mode kept
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()),
                         ["asound.state", "asound.state.audius-backup"])           # no temp left
        self.assertEqual((path.parent / "asound.state.audius-backup").read_text(), STATE)

    def test_leaves_a_clean_file_untouched(self):
        clean, _ = bootstate.reset(STATE)
        rc, path = self.run_on(clean)
        before = path.stat().st_mtime_ns
        self.assertEqual(keep.main([str(path)], flag=path.parent / "flag"), 0)
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertEqual(path.read_text(), clean)

    def test_missing_or_foreign_files_are_harmless(self):
        d = Path(tempfile.mkdtemp())
        self.assertEqual(keep.main([str(d / "nope")], flag=d / "flag"), 0)
        text = "state.Generic {\n" + control(1, "Main-Out PH3", 8045) + "}\n"
        rc, path = self.run_on(text)
        self.assertEqual(path.read_text(), text)

    def test_changes_are_reported(self):
        _, changes = bootstate.reset(STATE)
        self.assertEqual(changes, ["Main-Out PH3: 8045 -> 1", "Main-Out PH4: 8045 -> 1", "Main-Out AS1: 32769 -> 1"])


    def test_boot_mode_runs_once_per_boot(self):
        # A second restore in the same boot (alsa-state restarted on an upgrade) must find the
        # real level still saved: the driver holds it, so restoring 1 would really write near-silence.
        d = Path(tempfile.mkdtemp())
        path, flag = d / "asound.state", d / "run" / "flag"
        flag.parent.mkdir()
        path.write_text(STATE)
        keep.main(["--boot", str(path)], flag=flag)
        self.assertTrue(flag.exists())
        self.assertEqual(bootstate.saved_volumes(path.read_text()), {})
        path.write_text(STATE)                       # saved again mid-session
        keep.main(["--boot", str(path)], flag=flag)
        self.assertEqual(path.read_text(), STATE)    # untouched

    def test_boot_mode_does_nothing_without_its_flag(self):
        d = Path(tempfile.mkdtemp())
        path = d / "asound.state"
        path.write_text(STATE)
        keep.main(["--boot", str(path)], flag=d / "missing-dir" / "flag")   # /run not writable
        self.assertEqual(path.read_text(), STATE)


class Notice(unittest.TestCase):
    def test_tells_once_what_to_do(self):
        d = Path(tempfile.mkdtemp())
        state, dropin = d / "asound.state", d / "dropin.conf"
        self.assertIsNone(bootstate.notice(state, dropin))            # no file
        state.write_text(bootstate.reset(STATE)[0])
        self.assertIsNone(bootstate.notice(state, dropin))            # clean
        state.write_text(STATE)
        self.assertIn("README", bootstate.notice(state, dropin))      # no drop-in (install.sh)
        dropin.write_text("")
        self.assertIn("Restart once", bootstate.notice(state, dropin))
        self.assertEqual(bootstate.saved_volumes(STATE),
                         {"Main-Out PH3": 8045, "Main-Out PH4": 8045, "Main-Out AS1": 32769})


if __name__ == "__main__":
    unittest.main()
