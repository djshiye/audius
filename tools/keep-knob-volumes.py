#!/usr/bin/python3 -I
"""Keep the boot-time sound restore from overriding the Babyface volume knob.

Puts the driver's "never written" placeholder (1) back into every Babyface `Main-Out` value in
the saved sound state, so restores leave the device at its knob level. See audius/bootstate.py.

The RPM runs it from systemd drop-ins right after the state is saved at shutdown:

    keep-knob-volumes --shutdown

Why at shutdown and not before the boot restore: Fedora restores a card twice at boot, first from
a udev rule as soon as the Babyface appears, then again from alsa-state. Resetting between the
two would make the second restore really write 1 (the first one already put a real level into the
driver), and 1 is near silence. After the shutdown save nothing restores until the card is freshly
probed at the next boot, when restoring 1 is skipped.

`--shutdown` does nothing unless the system is actually shutting down (`systemctl
is-system-running` says "stopping"), so an alsa-state restart in the middle of a session (for
example on an alsa-utils upgrade) keeps the real level saved and restores it harmlessly.

By hand (as root, with alsa-state stopped, then reboot so nothing restores in between):

    sudo systemctl stop alsa-state
    sudo /usr/libexec/audius/keep-knob-volumes        # or: sudo python3 tools/keep-knob-volumes.py
    sudo reboot

It never fails the sound service: a missing, unreadable or unexpected file is left alone. When it
changes something, the previous file is kept as asound.state.audius-backup.
"""
import shutil
import subprocess
import sys
from pathlib import Path

# From the source tree, use the code next to this file; installed, use /usr/share/audius.
_tree = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_tree) if (_tree / "audius" / "bootstate.py").is_file() else "/usr/share/audius")
from audius import bootstate  # noqa: E402


def shutting_down():
    """True only while systemd is taking the system down. Anything unexpected counts as no."""
    try:
        out = subprocess.run(["systemctl", "is-system-running"], capture_output=True, text=True,
                             timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    return out == "stopping"


def main(argv=None, stopping=shutting_down):
    argv = sys.argv[1:] if argv is None else list(argv)
    at_shutdown = "--shutdown" in argv
    args = [a for a in argv if a != "--shutdown"]
    path = Path(args[0]) if args else bootstate.STATE
    if at_shutdown and not stopping():
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
