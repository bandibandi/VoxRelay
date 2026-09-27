#!/usr/bin/env bash
# One-time setup: copies the .example config files into place and checks
# that the system-level tools this project shells out to are installed.
# Safe to run again later, it never overwrites a file that already exists.
set -euo pipefail
cd "$(dirname "$0")"

echo "== Config files =="

copy_if_missing() {
    local src="$1" dst="$2"
    if [ -f "$dst" ]; then
        echo "  already exists, skipping: $dst"
    else
        cp "$src" "$dst"
        echo "  created: $dst"
    fi
}

copy_if_missing "config/config.toml.example" "config/config.toml"
copy_if_missing "config/commands.toml.example" "config/commands.toml"

read -rp "Which language example content do you want (hu/en)? " LANG_CHOICE
LANG_CHOICE="${LANG_CHOICE:-hu}"

copy_if_missing "config/dictionary-${LANG_CHOICE}.example" "config/dictionary.txt"
copy_if_missing "config/blocklist-${LANG_CHOICE}.example" "config/blocklist.txt"
copy_if_missing "config/profanity-${LANG_CHOICE}.example" "config/profanity.txt"

echo
echo "== System tools =="

check_tool() {
    local tool="$1" hint="$2"
    if command -v "$tool" >/dev/null 2>&1; then
        echo "  found: $tool"
    else
        echo "  MISSING: $tool ($hint)"
    fi
}

check_tool xdotool "needed to type dictated text, apt install xdotool"
check_tool xclip "needed for clipboard-based text injection, apt install xclip"
check_tool paplay "needed for start/stop/error sounds, apt install pulseaudio-utils"
check_tool fc-list "needed by the dialog to install its bundled font, apt install fontconfig"

if command -v gnome-terminal >/dev/null 2>&1 || command -v alacritty >/dev/null 2>&1 || command -v x-terminal-emulator >/dev/null 2>&1; then
    echo "  found a terminal emulator for running voice commands"
else
    echo "  MISSING: a terminal emulator (gnome-terminal, alacritty, or x-terminal-emulator)"
fi

if python3 -c "import gi; gi.require_version('Gtk', '3.0')" >/dev/null 2>&1; then
    echo "  found: python3-gi (GTK 3 bindings)"
else
    echo "  MISSING: python3-gi and gir1.2-gtk-3.0, apt install python3-gi gir1.2-gtk-3.0"
fi

if python3 -c "import gi; gi.require_version('AyatanaAppIndicator3', '0.1')" >/dev/null 2>&1; then
    echo "  found: gir1.2-ayatanaappindicator3-0.1 (tray icon)"
else
    echo "  MISSING: gir1.2-ayatanaappindicator3-0.1, apt install gir1.2-ayatanaappindicator3-0.1 (only needed for the tray icon)"
fi

if groups "$USER" | grep -qw input; then
    echo "  $USER is in the 'input' group (needed to read the keyboard/button device)"
else
    echo "  MISSING: $USER is not in the 'input' group, run: sudo usermod -aG input $USER (then log out and back in)"
fi

echo
echo "== Python packages =="
echo "  install with: pip install -r requirements.txt"

echo
echo "Next steps:"
echo "  1. Fix any MISSING lines above."
echo "  2. Edit config/config.toml: set keyboard_name, key, device and compute_type for your machine."
echo "  3. Run: python3 voxrelay.py"
