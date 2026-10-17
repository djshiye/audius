#!/usr/bin/env bash
# Install Audius for the current user (no sudo): ./install.sh
# Remove it again:                                ./install.sh --uninstall
set -euo pipefail

APP_ID=io.github.djshiye.Audius
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA/audius"
BIN="$HOME/.local/bin"

uninstall() {
  rm -rf "$PREFIX"
  rm -f "$BIN/audius" "$DATA/applications/$APP_ID.desktop" "$DATA/metainfo/$APP_ID.metainfo.xml" \
        "$DATA/icons/hicolor/scalable/apps/$APP_ID.svg" "$DATA/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg"
  update-desktop-database -q "$DATA/applications" 2>/dev/null || true
  echo "Audius removed. Your settings stay in ~/.config/audius."
}

if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall
  exit 0
fi

missing=()
python3 - <<'EOF' || missing+=("python3-gobject gtk4 libadwaita webkitgtk6.0")
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("WebKit", "6.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gtk, Adw, WebKit, Gst  # noqa: F401
EOF
gst-inspect-1.0 level >/dev/null 2>&1 || missing+=("gstreamer1-plugins-good")
gst-inspect-1.0 pipewiresrc >/dev/null 2>&1 || missing+=("pipewire-gstreamer")
command -v pw-dump >/dev/null || missing+=("pipewire-utils")
if (( ${#missing[@]} )); then
  echo "Audius needs: ${missing[*]}"
  echo "Install them with: sudo dnf install ${missing[*]}"
  exit 1
fi

rm -rf "$PREFIX"
mkdir -p "$PREFIX" "$BIN" "$DATA/applications" "$DATA/metainfo" \
         "$DATA/icons/hicolor/scalable/apps" "$DATA/icons/hicolor/symbolic/apps"
cp -r "$SRC/audius" "$PREFIX/"
find "$PREFIX" -name __pycache__ -prune -exec rm -rf {} +

cat > "$BIN/audius" <<EOF
#!/usr/bin/env python3
import sys
sys.path.insert(0, "$PREFIX")
from audius.app import main
sys.exit(main())
EOF
chmod +x "$BIN/audius"

# GNOME Shell watches these folders and has crashed reading a half-written .desktop file,
# taking the whole session with it. Write each file next to the app, then rename it into place.
place() {
  local tmp; tmp="$(mktemp -p "$PREFIX")"
  cat > "$tmp"; chmod 644 "$tmp"; mv -f "$tmp" "$1"
}
sed "s|^Exec=audius|Exec=$BIN/audius|" "$SRC/data/$APP_ID.desktop" | place "$DATA/applications/$APP_ID.desktop"
place "$DATA/metainfo/$APP_ID.metainfo.xml" < "$SRC/data/$APP_ID.metainfo.xml"
place "$DATA/icons/hicolor/scalable/apps/$APP_ID.svg" < "$SRC/data/icons/$APP_ID.svg"
place "$DATA/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg" < "$SRC/data/icons/$APP_ID-symbolic.svg"
update-desktop-database -q "$DATA/applications" 2>/dev/null || true
gtk-update-icon-cache -q -t -f "$DATA/icons/hicolor" 2>/dev/null || true

echo "Audius installed. Open it from the app grid, or run: $BIN/audius"
