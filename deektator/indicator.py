"""Bottom-of-screen indicator using the desktop's Wayland layer shell."""

import os
import subprocess
import sys


class RecordingIndicator:
    def __init__(self):
        self.process = None
        if os.environ.get("WAYLAND_DISPLAY"):
            try:
                self.process = subprocess.Popen(
                    [sys.executable, os.path.abspath(__file__)],
                    stdin=subprocess.PIPE,
                )
            except OSError:
                pass

    def show(self, visible):
        if not self.process or self.process.poll() is not None:
            return False
        try:
            self.process.stdin.write(b"1" if visible else b"0")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            return False
        return True

    def close(self):
        if self.process:
            try:
                self.process.stdin.close()
            except OSError:
                pass


def main():
    import gi

    try:
        gi.require_version("Gtk", "3.0")
        gi.require_version("GtkLayerShell", "0.1")
    except ValueError:
        print("Deektator: install gtk-layer-shell for the recording indicator.", file=sys.stderr)
        return 1
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

    if not Gtk.init_check()[0] or not GtkLayerShell.is_supported():
        print("Deektator: the desktop does not support the Wayland recording indicator.", file=sys.stderr)
        return 1

    window = Gtk.Window(decorated=False, resizable=False, accept_focus=False)
    window.set_default_size(160, 42)
    window.get_style_context().add_class("indicator-window")
    window.set_visual(window.get_screen().get_rgba_visual())
    GtkLayerShell.init_for_window(window)
    GtkLayerShell.set_namespace(window, "deektator-recording")
    GtkLayerShell.set_layer(window, GtkLayerShell.Layer.OVERLAY)
    GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.BOTTOM, True)
    GtkLayerShell.set_margin(window, GtkLayerShell.Edge.BOTTOM, 32)
    GtkLayerShell.set_exclusive_zone(window, 0)
    GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.NONE)

    pill = Gtk.Box(spacing=9)
    pill.get_style_context().add_class("recording-pill")
    icon = Gtk.Image.new_from_icon_name("media-record-symbolic", Gtk.IconSize.MENU)
    icon.get_style_context().add_class("recording-dot")
    pill.pack_start(icon, False, False, 0)
    pill.pack_start(Gtk.Label(label="Recording"), False, False, 0)
    window.add(pill)

    style = Gtk.CssProvider()
    style.load_from_data(b"""
        .indicator-window { background: transparent; }
        .recording-pill {
            background: #182422;
            color: #fff;
            border: 1px solid #485855;
            border-radius: 22px;
            padding: 10px 18px;
            font-size: 11pt;
            font-weight: 700;
        }
        .recording-dot { color: #ff786f; }
    """)
    Gtk.StyleContext.add_provider_for_screen(
        window.get_screen(), style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    def update(fd, condition):
        if condition & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
            Gtk.main_quit()
            return GLib.SOURCE_REMOVE
        data = os.read(fd, 4096)
        if not data:
            Gtk.main_quit()
            return GLib.SOURCE_REMOVE
        if data[-1:] == b"1":
            window.show_all()
        else:
            window.hide()
        return GLib.SOURCE_CONTINUE

    GLib.io_add_watch(sys.stdin.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, update)
    Gtk.main()
    window.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
