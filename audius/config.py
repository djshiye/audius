"""Audius settings: ~/.config/audius/config.json.

The mixer state itself lives in ALSA (alsa-state.service saves and restores it).
This file only holds what the hardware can't: names, stereo links, the levels to
bring back when something is switched on again, scenes, and preferences.
"""
import copy
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "audius"
CONFIG_PATH = CONFIG_DIR / "config.json"
VERSION = 1

DEFAULTS = {
    "version": VERSION,
    "names": {},            # strip/output id -> custom name
    "links": {              # input/playback pair (by first channel) -> stereo linked
        "in:AN1": False, "in:IN3": False, "in:AS1": True,
        "in:ADAT3": True, "in:ADAT5": True, "in:ADAT7": True,
        "pb:AN1": True, "pb:PH3": True, "pb:AS1": True,
        "pb:ADAT3": True, "pb:ADAT5": True, "pb:ADAT7": True,
    },
    "pan_memory": {},       # "strip>outpair" -> pan, kept when a send is at -inf
    "send_mute": {},        # "strip>outpair" -> {control: raw} to restore on unmute
    "output_off": {},       # outpair -> {control: raw} to restore when switched on
    "dim": {},              # outpair -> {control: raw} undimmed sends while DIM is on
    "limits": {"AN1": 0.0, "PH3": 0.0, "AS1": 0.0, "ADAT3": 0.0, "ADAT5": 0.0, "ADAT7": 0.0},
    "mic_levels": {},       # outpair -> Mic 1 send level (dB) the listening presets bring back
    "volumes": {},          # outpair -> last volume Audius set (dB); the device can't be read back
    "scenes": [],
    "prefs": {
        "meters": True,            # live levels (needs a capture stream)
        "show_optical": False,     # optical/ADAT channels in Mixer and Routing
        "show_all_playback": False,  # computer channels 3-12 (unused with the stereo profile)
        "takeover_fade": True,     # fade in after the hardware knob may have moved a volume
        "speaker_start_db": -40.0,
        "knob_outputs": ["PH3"],   # outputs whose volume usually lives on the device knob
        "dim_db": -20.0,           # how far DIM lowers an output (the device key's default)
    },
    "overview_sources": {          # outpair -> strips shown on the Overview cards
        "PH3": ["pb:AN1", "in:AN1"],
        "AN1": ["pb:AN1", "in:AN1"],
    },
    "window": {"width": 1240, "height": 860, "maximized": False},
    "ui": {"page": "overview", "mixer_output": "PH3", "more_inputs": False},
}


def _merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict) and k not in ("names", "pan_memory",
                                                                               "send_mute", "output_off", "dim",
                                                                               "volumes"):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


class Config:
    def __init__(self, path=CONFIG_PATH, autosave=True):
        self.path = Path(path)
        self.autosave = autosave
        self.data = copy.deepcopy(DEFAULTS)
        self._save_id = None
        try:
            with open(self.path) as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                _merge(self.data, loaded)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning("ignoring unreadable %s: %s", self.path, e)
            try:
                self.path.rename(self.path.with_suffix(".broken"))
            except OSError:
                pass

    def __getitem__(self, key):
        return self.data[key]

    def changed(self):
        """Schedule a save (debounced) after a mutation."""
        if not self.autosave:
            return
        try:
            from gi.repository import GLib
        except ImportError:  # pragma: no cover
            self.save()
            return
        if self._save_id is None:
            self._save_id = GLib.timeout_add(400, self._save_cb)

    def _save_cb(self):
        self._save_id = None
        self.save()
        return False

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("could not save %s: %s", self.path, e)

    def flush(self):
        if self._save_id is not None:
            from gi.repository import GLib
            GLib.source_remove(self._save_id)
            self._save_id = None
            self.save()
