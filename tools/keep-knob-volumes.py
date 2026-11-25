#!/usr/bin/python3 -I
"""Keep the boot-time sound restore from overriding the Babyface volume knob.

Puts the driver's "never written" placeholder (1) back into every Babyface `Main-Out` value in
the saved sound state, so the restore leaves the device at its knob level. See audius/bootstate.py.

The RPM runs it from a systemd drop-in, right before alsa-state (or alsa-restore) restores:

    keep-knob-volumes --boot

`--boot` does the reset at most once per boot (a flag in /run). If alsa-state restarts later in
the session, for example on an alsa-utils upgrade, the driver already holds a real volume, so
restoring the placeholder would really be written, and 1 is near silence. With the flag present,
or if it can't be created, nothing is touched.

By hand (as root, with alsa-state stopped, then reboot):

    sudo systemctl stop alsa-state
    sudo /usr/libexec/audius/keep-knob-volumes        # or: sudo python3 tools/keep-knob-volumes.py
    sudo reboot

It never fails the sound service: a missing, unreadable or unexpected file is left alone. When it
changes something, the previous file is kept as asound.state.audius-backup.
"""
import os
import shutil
import sys
from pathlib import Path

# From the source tree, use the code next to this file; installed, use /usr/share/audius.
_tree = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_tree) if (_tree / "audius" / "bootstate.py").is_file() else "/usr/share/audius")
from audius import bootstate  # noqa: E402

BOOT_FLAG = Path("/run/audius-keep-knob")


def first_time_this_boot(flag):
    try:
        os.close(os.open(flag, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))
        return True
    except OSError:          # already done this boot, or /run unwritable: do nothing
        return False


def main(argv=None, flag=BOOT_FLAG):
    argv = sys.argv[1:] if argv is None else list(argv)
    boot = "--boot" in argv
    args = [a for a in argv if a != "--boot"]
    path = Path(args[0]) if args else bootstate.STATE
    if boot and not first_time_this_boot(flag):
        return 0
    try:
        text = path.read_text()
    except FileNotFoundError:
        return 0
    except (OSError, UnicodeDecodeError) as e:
        print(f"keep-knob-volumes: can't read {path}: {e}", file=sys.stderr)
        return 0
    new, changes = bootstate.reset(text)
    if not changes:
        return 0
    try:
        shutil.copy2(path, path.with_name(path.name + ".audius-backup"))
        bootstate.write_atomically(path, new)
    except OSError as e:
        print(f"keep-knob-volumes: can't write {path}: {e}", file=sys.stderr)
        return 0
    print("keep-knob-volumes: the Babyface keeps its knob volume at startup (" + "; ".join(changes) + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
