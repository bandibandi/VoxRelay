#!/usr/bin/env python3
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk


CSS = b"""
window {
    background-color: transparent;
}

.modal {
    background-color: @theme_bg_color;
    color: @theme_fg_color;

    border: 1px solid alpha(@theme_fg_color, 0.12);
    border-radius: 16px;
}

.header {
    padding: 17px 22px 8px 22px;
}

.icon-badge {
    background-color: alpha(@theme_selected_bg_color, 0.16);
    border-radius: 999px;
    padding: 7px;
}

.header-title {
    color: @theme_fg_color;
    font: 600 13px Sans;
}

.close {
    min-width: 28px;
    min-height: 28px;

    padding: 0;
    border: none;
    border-radius: 14px;
    outline: none;

    background-image: none;
    background-color: transparent;

    color: alpha(@theme_fg_color, 0.50);
    font: 400 17px Sans;
}

.close:hover {
    background-color: alpha(@theme_fg_color, 0.10);
    color: @theme_fg_color;
}

.close:active {
    background-color: alpha(@theme_fg_color, 0.14);
}

.close:focus {
    outline: none;
    border: none;
}

.content {
    padding: 10px 28px 20px 28px;
}

.phrase {
    color: @theme_fg_color;
    font: 600 23px Sans;
}

.command-label {
    color: alpha(@theme_fg_color, 0.58);
    font: 500 12px Sans;
}

.command-card {
    background-color: alpha(@theme_fg_color, 0.06);

    border: 1px solid alpha(@theme_fg_color, 0.13);
    border-radius: 11px;

    padding: 15px 17px;
}

.prompt {
    color: @theme_selected_bg_color;
    font: 600 15px "JetBrains Mono";
}

.command {
    color: @theme_fg_color;
    font: 400 15px "JetBrains Mono";
}

entry.command-input {
    min-height: 48px;

    padding: 0 14px;

    background-image: none;
    background-color: alpha(@theme_fg_color, 0.045);

    color: @theme_fg_color;

    border: 1px solid alpha(@theme_fg_color, 0.14);
    border-radius: 10px;

    font: 400 14px "JetBrains Mono";
    caret-color: @theme_selected_bg_color;
}

entry.command-input:focus {
    border-color: @theme_selected_bg_color;
}

.footer {
    padding: 0 22px 18px 28px;
}

button.secondary {
    min-height: 38px;

    padding: 0 15px;

    background-image: none;
    background-color: transparent;

    border: 1px solid alpha(@theme_fg_color, 0.12);
    border-radius: 9px;

    color: alpha(@theme_fg_color, 0.72);
    font: 500 13px Sans;
}

button.secondary:hover {
    background-color: alpha(@theme_fg_color, 0.07);
    color: @theme_fg_color;
}

button.secondary:active {
    background-color: alpha(@theme_fg_color, 0.12);
}

button.secondary:focus {
    outline: none;
}

button.primary {
    min-height: 38px;

    padding: 0 17px;

    background-image: none;
    background-color: @theme_selected_bg_color;

    border: 1px solid alpha(@theme_selected_bg_color, 0.9);
    border-radius: 9px;

    color: @theme_selected_fg_color;

    font: 600 13px Sans;
}

button.primary:hover {
    background-color: lighter(@theme_selected_bg_color);
}

button.primary:active {
    background-color: darker(@theme_selected_bg_color);
}

button.primary:focus {
    outline: none;
}

separator {
    background-color: transparent;
}
"""


MIC_SVG = """
<svg xmlns="http://www.w3.org/2000/svg"
     width="18"
     height="18"
     viewBox="0 0 24 24"
     fill="none"
     stroke="currentColor"
     stroke-width="2"
     stroke-linecap="round"
     stroke-linejoin="round">

    <rect x="9" y="2" width="6" height="12" rx="3"/>
    <path d="M19 10v1a7 7 0 0 1-14 0v-1"/>
    <line x1="12" y1="18" x2="12" y2="22"/>
    <line x1="8" y1="22" x2="16" y2="22"/>
</svg>
"""


def ensure_font() -> None:
    listed = subprocess.run(
        ["fc-list", ":family"],
        capture_output=True,
        text=True,
    ).stdout

    if "JetBrains Mono" in listed:
        return

    bundled = sorted(
        (
            Path(__file__).resolve().parent
            / "assets"
            / "fonts"
        ).glob("JetBrainsMono-*.ttf")
    )

    if not bundled:
        return

    target = Path.home() / ".local" / "share" / "fonts"
    target.mkdir(parents=True, exist_ok=True)

    for file in bundled:
        shutil.copy2(file, target / file.name)

    subprocess.run(
        ["fc-cache", "-f"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def styled_label(
    text: str,
    css_class: str,
    *,
    wrap: bool = False,
) -> Gtk.Label:
    widget = Gtk.Label(label=text)
    widget.get_style_context().add_class(css_class)

    widget.set_xalign(0)

    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(2)
        widget.set_max_width_chars(90)

    return widget


def theme_accent() -> str:
    found, color = Gtk.Window().get_style_context().lookup_color("theme_selected_bg_color")

    if not found:
        return "#5e81ac"

    return "#{:02x}{:02x}{:02x}".format(
        int(color.red * 255),
        int(color.green * 255),
        int(color.blue * 255),
    )


def mic_badge() -> Gtk.Box:
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.write(MIC_SVG.replace("currentColor", theme_accent()).encode("utf-8"))
    loader.close()

    badge = Gtk.Box()
    badge.get_style_context().add_class("icon-badge")
    badge.add(Gtk.Image.new_from_pixbuf(loader.get_pixbuf()))

    return badge


def close_button() -> Gtk.Button:
    button = Gtk.Button(label="×")
    button.get_style_context().add_class("close")
    button.set_tooltip_text("Close")
    button.set_focus_on_click(False)

    return button


def build(
    phrase: str,
    command: str,
    ask: bool,
) -> tuple[Gtk.Window, dict]:

    result = {
        "ok": False,
        "text": "",
    }

    window = Gtk.Window()
    window.set_decorated(False)
    window.set_position(Gtk.WindowPosition.CENTER)
    window.set_keep_above(True)
    window.set_type_hint(Gdk.WindowTypeHint.DIALOG)

    window.set_size_request(680, -1)
    window.set_resizable(False)

    window.set_app_paintable(True)

    visual = Gdk.Screen.get_default().get_rgba_visual()

    if visual is not None:
        window.set_visual(visual)

    root = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=0,
    )

    root.get_style_context().add_class("modal")

    window.add(root)

    header = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=10,
    )

    header.get_style_context().add_class("header")

    icon = mic_badge()
    icon.set_valign(Gtk.Align.CENTER)

    header.pack_start(icon, False, False, 0)

    title = styled_label("Voice command", "header-title")
    title.set_valign(Gtk.Align.CENTER)

    header.pack_start(title, False, False, 0)

    close = close_button()
    close.set_valign(Gtk.Align.CENTER)

    header.pack_end(close, False, False, 0)

    root.pack_start(header, False, False, 0)

    content = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=0,
    )

    content.get_style_context().add_class("content")

    root.pack_start(content, False, False, 0)

    phrase_label = styled_label(phrase, "phrase", wrap=True)
    phrase_label.set_margin_top(4)
    phrase_label.set_margin_bottom(22)

    content.pack_start(phrase_label, False, False, 0)

    command_label = styled_label("Command to run", "command-label")
    command_label.set_margin_bottom(9)

    content.pack_start(command_label, False, False, 0)

    entry = None

    if ask:
        entry = Gtk.Entry()
        entry.get_style_context().add_class("command-input")
        entry.set_placeholder_text("Enter a shell command…")

        content.pack_start(entry, False, False, 0)

    else:
        command_card = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10,
        )

        command_card.get_style_context().add_class("command-card")

        prompt = styled_label("$", "prompt")
        prompt.set_valign(Gtk.Align.START)

        command_card.pack_start(prompt, False, False, 0)

        command_text = styled_label(command, "command", wrap=True)
        command_text.set_valign(Gtk.Align.CENTER)

        command_card.pack_start(command_text, True, True, 0)

        content.pack_start(command_card, False, False, 0)

    footer = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL,
        spacing=9,
    )

    footer.get_style_context().add_class("footer")
    footer.set_margin_top(6)

    action = Gtk.Button(label="Save" if ask else "Run")
    action.get_style_context().add_class("primary")

    footer.pack_end(action, False, False, 0)

    cancel = Gtk.Button(label="Cancel")
    cancel.get_style_context().add_class("secondary")

    footer.pack_end(cancel, False, False, 0)

    root.pack_start(footer, False, False, 0)

    def quit_cancel(*_):
        Gtk.main_quit()

    def approve(*_):
        result["ok"] = True

        if entry is not None:
            result["text"] = entry.get_text().strip()
        else:
            result["text"] = ""

        Gtk.main_quit()

    close.connect("clicked", quit_cancel)
    cancel.connect("clicked", quit_cancel)
    action.connect("clicked", approve)

    if entry is not None:
        entry.connect("activate", approve)

    def on_key(_widget, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()

        elif event.keyval in (
            Gdk.KEY_Return,
            Gdk.KEY_KP_Enter,
        ):
            approve()

    window.connect("key-press-event", on_key)
    window.connect("destroy", lambda *_: Gtk.main_quit())

    if entry is not None:
        entry.set_can_focus(True)
        window.set_focus(entry)
    else:
        action.set_can_default(True)
        window.set_default(action)
        window.set_focus(action)

    return window, result


def fade_in(window: Gtk.Window, steps: int = 12, interval: int = 12) -> None:
    Gtk.Widget.set_opacity(window, 0.0)
    progress = {"step": 0}

    def tick() -> bool:
        progress["step"] += 1
        Gtk.Widget.set_opacity(window, min(progress["step"] / steps, 1.0))
        return progress["step"] < steps

    GLib.timeout_add(interval, tick)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument("--phrase", required=True)
    parser.add_argument("--command", default="")
    parser.add_argument("--ask", action="store_true")

    args = parser.parse_args()

    ensure_font()

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)

    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )

    window, result = build(
        args.phrase,
        args.command,
        args.ask,
    )

    window.show_all()
    fade_in(window)

    Gtk.main()

    if not result["ok"]:
        return 1

    if args.ask:
        print(result["text"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
