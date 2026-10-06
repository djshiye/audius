import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fix_alsa_state", ROOT / "tools" / "fix-alsa-state.py")
fix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix)

STATE = """state.Generic {
\tcontrol.1 {
\t\tiface MIXER
\t\tname 'Line-IN3-AN1 Playback Volume'
\t\tvalue 3
\t}
}
state.Pro73000526 {
\tcontrol.3 {
\t\tiface MIXER
\t\tname 'Mic-AN1-AN1 Playback Volume'
\t\tvalue 0
\t}
\tcontrol.51 {
\t\tiface MIXER
\t\tname 'Mic-AN1-PH3 Playback Volume'
\t\tvalue 65536
\t}
\tcontrol.297 {
\t\tiface MIXER
\t\tname 'Line-ADAT8-ADAT8 Playback Volume'
\t\tvalue 1
\t}
\tcontrol.60 {
\t\tiface MIXER
\t\tname 'PCM-AS1-PH3 Playback Volume'
\t\tvalue 20001
\t}
\tcontrol.293 {
\t\tiface MIXER
\t\tname 'Main-Out PH3'
\t\tvalue 1
\t}
\tcontrol.303 {
\t\tiface MIXER
\t\tname 'Mic-AN1 Gain'
\t\tvalue 27
\t}
}
"""


class FixState(unittest.TestCase):
    def test_evens_only_babyface_crosspoints(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "asound.state"
            path.write_text(STATE)
            import sys
            argv = sys.argv
            sys.argv = ["fix", str(path)]
            try:
                fix.main()
            finally:
                sys.argv = argv
            out = path.read_text()
            self.assertIn("name 'Line-ADAT8-ADAT8 Playback Volume'\n\t\tvalue 0", out)
            self.assertIn("name 'PCM-AS1-PH3 Playback Volume'\n\t\tvalue 20000", out)
            self.assertIn("name 'Mic-AN1-PH3 Playback Volume'\n\t\tvalue 65536", out)
            self.assertIn("name 'Main-Out PH3'\n\t\tvalue 1", out)          # deliberately untouched
            self.assertIn("name 'Mic-AN1 Gain'\n\t\tvalue 27", out)           # not a crosspoint
            self.assertIn("name 'Line-IN3-AN1 Playback Volume'\n\t\tvalue 3", out)  # other card
            self.assertEqual(len(list(Path(d).glob("asound.state.audius-*"))), 1)  # backup made


if __name__ == "__main__":
    unittest.main()
