"""Find the Babyface's PipeWire nodes (for level meters) via pw-dump."""
import json
import logging
import subprocess

log = logging.getLogger(__name__)


def _positions(value):
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [p.strip() for p in value.strip("[] ").replace(",", " ").split() if p.strip()]
    return []


def find_nodes(card_index, timeout=3.0):
    """Return {'source': node, 'sink': node} for an ALSA card; nodes are dicts with
    name, channels, positions, description. Missing entries are None."""
    found = {"source": None, "sink": None}
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=timeout, check=False).stdout
        data = json.loads(out or "[]")
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        log.info("pw-dump unavailable: %s", e)
        return found
    for obj in data:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = (obj.get("info") or {}).get("props") or {}
        card = props.get("api.alsa.pcm.card", props.get("alsa.card"))
        if card is None or str(card) != str(card_index):
            continue
        cls = props.get("media.class", "")
        kind = "source" if cls == "Audio/Source" else "sink" if cls == "Audio/Sink" else None
        if kind is None or found[kind] is not None:
            continue
        positions = _positions(props.get("audio.position"))
        try:
            channels = int(props.get("audio.channels") or len(positions) or 2)
        except (TypeError, ValueError):
            channels = len(positions) or 2
        found[kind] = {"name": props.get("node.name"), "channels": channels, "positions": positions,
                       "description": props.get("node.description", ""),
                       "profile": props.get("device.profile.name", "")}
    return found
