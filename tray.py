#!/usr/bin/env python3

import os
import re
import shutil
import subprocess
import sys
import tomllib

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")

from gi.repository import AyatanaAppIndicator3 as AppIndicator, GLib, Gtk


SERVICE = "voxrelay"
HERE = os.path.dirname(os.path.abspath(__file__))

# Our own icons rather than theme names like "audio-input-microphone": a
# theme icon is drawn in the panel's foreground colour, so it is always
# whatever the panel decides, usually plain white. Pointing the indicator at
# a directory of our own gives us the colour. The shape is the same mic that
# dialog.py draws.
ICON_PATH = os.path.join(HERE, "assets", "tray")
ICON_RUNNING = "voxrelay-running"
ICON_STOPPED = "voxrelay-stopped"
CONFIG_FILE = os.path.join(HERE, "config", "config.toml")
TRANSCRIPT_FILE = os.path.join(HERE, "transcript_log.txt")

# A useful subset of what faster-whisper accepts. Picking one rewrites the
# model line in config.toml and restarts the daemon, which is the only way the
# setting takes effect. A model you have not used before is downloaded on the
# first recording after that, so the first one is slow.
MODELS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]

# Label, path. Everything but config.toml is wrapped in a WatchedFile by the
# daemon and reloads on its own, so only the settings entry warns about the
# restart.
EDITABLE = [
    ("Settings (needs restart)", os.path.join(HERE, "config", "config.toml")),
    ("Dictionary", os.path.join(HERE, "config", "dictionary.txt")),
    ("Blocklist", os.path.join(HERE, "config", "blocklist.txt")),
    ("Profanity list", os.path.join(HERE, "config", "profanity.txt")),
    ("Voice commands", os.path.join(HERE, "config", "commands.toml")),
]


def is_running() -> bool:
    result = subprocess.run(["systemctl", "--user", "is-active", "--quiet", SERVICE])
    return result.returncode == 0


def systemctl(action: str) -> None:
    subprocess.Popen(["systemctl", "--user", action, SERVICE])


def current_model() -> str:
    try:
        with open(CONFIG_FILE, "rb") as f:
            return tomllib.load(f).get("model", "")
    except (OSError, tomllib.TOMLDecodeError):
        return ""


def set_model(name: str) -> None:
    # A line rewrite rather than a full parse and dump: tomllib only reads,
    # and rewriting the file from a parsed dict would throw away every
    # comment in it.
    with open(CONFIG_FILE, encoding="utf-8") as f:
        text = f.read()
    new, changed = re.subn(r'(?m)^model\s*=\s*".*"$', f'model = "{name}"', text, count=1)
    if not changed:
        print(f"No model line in {CONFIG_FILE}", file=sys.stderr)
        return
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(new)
    systemctl("restart")


def open_path(path: str) -> None:
    subprocess.Popen(["xdg-open", path])


def show_logs() -> None:
    # -o cat drops journalctl's own "date host python[pid]:" prefix, which is
    # around 45 wasted columns per line: voxrelay's log format already starts
    # with a timestamp and a level of its own.
    # 1000 lines of history, not 100: the journal is persistent and holds
    # everything, and the terminal's own scrollback is far larger than this.
    journal = f"journalctl --user -u {SERVICE} -f -n 1000 -o cat"

    # Decoration belongs to the viewer, not to the log. The journal keeps one
    # plain line per event, and sed draws a rule in front of every new
    # recording so the start of an utterance is easy to find while scrolling.
    # sed -u keeps it line buffered; without it nothing would show up until
    # its buffer filled, which defeats -f.
    rule = "\u2500" * 100
    command = f"{journal} | sed -u 's/.*Recording started.*/{rule}\\n&/'"

    # Wide enough that a dictated sentence fits on one line instead of
    # wrapping. x-terminal-emulator gets no size flag: it is whatever the
    # distro points it at, and an unsupported option would just fail to open.
    terminals = [
        ["gnome-terminal", "--geometry=160x40", "--", "bash", "-c", command],
        ["alacritty",
         "-o", "window.dimensions.columns=160",
         "-o", "window.dimensions.lines=40",
         "-e", "bash", "-c", command],
        ["x-terminal-emulator", "-e", "bash", "-c", command],
    ]
    for terminal in terminals:
        if shutil.which(terminal[0]):
            subprocess.Popen(terminal)
            return
    print("No terminal emulator found", file=sys.stderr)


class Tray:
    def __init__(self) -> None:
        self.indicator = AppIndicator.Indicator.new(
            "voxrelay",
            ICON_STOPPED,
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_icon_theme_path(ICON_PATH)
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("VoxRelay")

        self.toggle = Gtk.MenuItem(label="Start")
        self.indicator.set_menu(self._build_menu())

        self.refresh()
        GLib.timeout_add_seconds(3, self.refresh)

    def _build_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()

        self.toggle.connect("activate", self._on_toggle)
        menu.append(self.toggle)
        menu.append(self._item("Restart", lambda _: systemctl("restart")))

        menu.append(Gtk.SeparatorMenuItem())

        menu.append(self._item("Show logs", lambda _: show_logs()))
        menu.append(self._item("Transcript log", lambda _: open_path(TRANSCRIPT_FILE)))

        menu.append(Gtk.SeparatorMenuItem())

        model = Gtk.MenuItem(label="Model")
        model.set_submenu(self._build_model_menu())
        menu.append(model)

        edit = Gtk.MenuItem(label="Edit")
        edit.set_submenu(self._build_edit_menu())
        menu.append(edit)

        menu.append(Gtk.SeparatorMenuItem())

        menu.append(self._item("Open project folder", lambda _: open_path(HERE)))
        menu.append(self._item("Quit tray", lambda _: Gtk.main_quit()))

        menu.show_all()
        return menu

    def _build_edit_menu(self) -> Gtk.Menu:
        submenu = Gtk.Menu()
        for label, path in EDITABLE:
            # path=path binds the current value into the lambda. Without it
            # every entry would close over the same loop variable and all five
            # would open whichever file happened to be last.
            submenu.append(self._item(label, lambda _, path=path: open_path(path)))
        return submenu

    def _build_model_menu(self) -> Gtk.Menu:
        submenu = Gtk.Menu()
        active = current_model()
        group = []
        for name in MODELS:
            item = Gtk.RadioMenuItem(label=name)
            if group:
                item.join_group(group[0])
            group.append(item)
            # Set the state before connecting, otherwise marking the current
            # model would fire the handler and restart the daemon at startup.
            item.set_active(name == active)
            item.connect("toggled", self._on_model, name)
            submenu.append(item)
        return submenu

    def _on_model(self, item: Gtk.RadioMenuItem, name: str) -> None:
        # A radio group fires twice per change, once for the item losing the
        # selection and once for the one gaining it.
        if item.get_active() and name != current_model():
            set_model(name)

    def _item(self, label: str, callback) -> Gtk.MenuItem:
        item = Gtk.MenuItem(label=label)
        item.connect("activate", callback)
        return item

    def _on_toggle(self, _item: Gtk.MenuItem) -> None:
        systemctl("stop" if is_running() else "start")

    def refresh(self) -> bool:
        running = is_running()
        self.indicator.set_icon_full(ICON_RUNNING if running else ICON_STOPPED, "VoxRelay")
        self.toggle.set_label("Stop" if running else "Start")
        return True


def main() -> None:
    Tray()
    Gtk.main()


if __name__ == "__main__":
    main()
