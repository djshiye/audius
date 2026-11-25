"""The saved sound-card state that Fedora restores at boot, as far as the Babyface's outputs go.

Fedora saves every card's mixer settings at shutdown (alsa-state / alsa-store) into
/var/lib/alsa/asound.state and restores them at the next start and when a card is plugged in.
The Babyface never reports its volume knob, so once Audius has set an output volume, that level
is what gets saved, and every boot pulls the output back to it, overriding the knob.

A saved `Main-Out` value of 1 is the driver's "never written" placeholder (docs/KERNEL-BUG.md):
on a freshly probed card restoring it is skipped, so the device keeps its knob and memory level.
`reset()` puts that placeholder back. It is only safe when no restore can follow until the card
is freshly probed again: once the driver holds a real value, restoring 1 is really written, and
1 is near silence. So the systemd drop-in runs it right after the shutdown save, never at boot
(Fedora restores twice at boot: udev first, then alsa-state). See tools/keep-knob-volumes.py.

stdlib only: this runs as root before anything else in Audius is loaded.
"""
import os
import re
import shutil
import tempfile
from pathlib import Path

STATE = Path("/var/lib/alsa/asound.state")
DROPIN = Path("/usr/lib/systemd/system/alsa-state.service.d/audius-keep-knob.conf")
PLACEHOLDER = 1
# One saved control, exactly as alsactl writes it; anything else is left alone.
CONTROL = re.compile(
    r"(\tcontrol\.\d+ \{\n\t\tiface MIXER\n\t\tname '(Main-Out [A-Z]+\d)'\n(?:\t\tindex \d+\n)?\t\tvalue )(\d+)")
BABYFACE_MARKERS = ("Main-Out PH3", "Mic-AN1 Gain")   # only the Babyface Pro's mixer has both
CARD = re.compile(r"^state\.(\S+) \{$", re.M)


def babyface_blocks(text):
    """(start, end) of each saved card that is a Babyface Pro."""
    for m in CARD.finditer(text):
        end = text.find("\n}\n", m.start())
        end = len(text) if end < 0 else end
        block = text[m.start():end]
        if all(f"\t\tname '{n}'\n" in block for n in BABYFACE_MARKERS):
            yield m.start(), end


def saved_volumes(text):
    """{control name: value} of every Babyface Main-Out that isn't the placeholder."""
    found = {}
    for start, end in babyface_blocks(text):
        for m in CONTROL.finditer(text, start, end):
            if int(m.group(3)) != PLACEHOLDER:
                found[m.group(2)] = int(m.group(3))
    return found


def reset(text):
    """(new text, [changes]) with every Babyface Main-Out value set to the placeholder."""
    changes = []

    def fix(match):
        value = int(match.group(3))
        if value == PLACEHOLDER:
            return match.group(0)
        changes.append(f"{match.group(2)}: {value} -> {PLACEHOLDER}")
        return f"{match.group(1)}{PLACEHOLDER}"

    out, last = [], 0
    for start, end in babyface_blocks(text):
        out.append(text[last:start])
        out.append(CONTROL.sub(fix, text[start:end]))
        last = end
    out.append(text[last:])
    return "".join(out), changes


def write_atomically(path, text):
    """Replace the file in one step, keeping its owner, mode and SELinux label."""
    fd, tmp = tempfile.mkstemp(prefix=".audius-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        shutil.copystat(path, tmp)          # mode, times and extended attributes (the label)
        st = path.stat()
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except PermissionError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def notice(state=STATE, dropin=DROPIN):
    """What to tell the user when the saved state would pull an output to an old level at the
    next boot, or None. Never raises: the file may be missing or unreadable."""
    try:
        saved = saved_volumes(Path(state).read_text())
    except (OSError, UnicodeDecodeError):
        return None
    if not saved:
        return None
    if Path(dropin).exists():
        return ("Your computer saved an old headphone volume and puts it back at every start. "
                "Restart once and your Babyface knob keeps its own level from then on.")
    return ("Your computer saved an old headphone volume and puts it back at every start, "
            "overriding your Babyface knob. The README’s “Keep the knob’s volume at startup” fixes it.")
