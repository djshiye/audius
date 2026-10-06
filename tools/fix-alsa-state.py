#!/usr/bin/env python3
"""Make the Babyface Pro's saved crosspoint levels even (see docs/KERNEL-BUG.md).

Run as root with alsa-state stopped:
    sudo systemctl stop alsa-state && sudo python3 tools/fix-alsa-state.py && sudo reboot

Only `… Playback Volume` crosspoints of the Babyface card are touched. `Main-Out` values are
left alone on purpose: their stored `1` keeps the boot-time restore from overriding the knob.
"""
import re
import shutil
import sys
import time
from pathlib import Path

STATE = Path("/var/lib/alsa/asound.state")
CROSSPOINT = re.compile(r"^(Mic|Line|PCM)-\w+-\w+ Playback Volume$")


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else STATE
    text = path.read_text()
    m = re.search(r"^state\.Pro\d+ \{$", text, re.M)
    if not m:
        sys.exit("No Babyface Pro card in " + str(path))
    start = m.start()
    end = text.find("\n}\n", start)
    end = len(text) if end < 0 else end
    block = text[start:end]
    changed = []

    def fix(match):
        name, value = match.group(2), int(match.group(4))
        if CROSSPOINT.match(name) and value % 2:
            changed.append(f"{name}: {value} -> {value - 1}")
            return f"{match.group(1)}{value - 1}"
        return match.group(0)

    pattern = re.compile(r"(\tcontrol\.\d+ \{\n\t\tiface MIXER\n\t\tname '([^']+)'\n(\t\tindex \d+\n)?\t\tvalue )(\d+)")
    new_block = pattern.sub(fix, block)
    if not changed:
        print("Nothing to fix: every saved crosspoint is already even.")
        return
    backup = path.with_name(path.name + time.strftime(".audius-%Y%m%d-%H%M%S"))
    shutil.copy2(path, backup)
    path.write_text(text[:start] + new_block + text[end:])
    print(f"Backed up to {backup}")
    print("\n".join(changed))
    print("Now reboot (or replug the Babyface, then `sudo systemctl start alsa-state`).")


if __name__ == "__main__":
    main()
