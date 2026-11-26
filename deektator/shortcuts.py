import fcntl
import os
import re
import uuid

from gi.repository import Gio, GLib

from .engine import APP_ID


DESTINATION = "org.freedesktop.portal.Desktop"
DESKTOP_PATH = "/org/freedesktop/portal/desktop"
SHORTCUTS = "org.freedesktop.portal.GlobalShortcuts"
REQUEST = "org.freedesktop.portal.Request"
SESSION = "org.freedesktop.portal.Session"
REGISTRY = "org.freedesktop.host.portal.Registry"
SHORTCUT_ID = "dictate"
PREFERRED = "CTRL+ALT+space"
ALT_KEYS = (56, 100)
SUPER_KEYS = (125, 126)
# EVIOCGKEY(96), for the Linux input bitmap covering KEY_MAX (0x2ff).
READ_PRESSED_KEYS = (2 << 30) | (96 << 16) | (ord("E") << 8) | 0x18


class KeyboardShortcut:
    def __init__(self, path, on_change, on_status):
        self.on_change = on_change
        self.on_status = on_status
        self.active = False
        self.armed = False
        self.keys = bytearray(96)
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.timer = None
        try:
            fcntl.ioctl(self.fd, READ_PRESSED_KEYS, self.keys)
        except OSError:
            self.close()
            raise
        self.timer = GLib.timeout_add(25, self.poll)
        self.on_status("Alt + Super (Windows)", True)

    def poll(self):
        try:
            fcntl.ioctl(self.fd, READ_PRESSED_KEYS, self.keys)
        except OSError:
            self.timer = None
            if self.active:
                self.on_change(False)
            self.close()
            self.on_status("Keyboard disconnected. Reconnect it, then retry the shortcut.", False)
            return GLib.SOURCE_REMOVE
        alt = any(self.keys[key // 8] & (1 << (key % 8)) for key in ALT_KEYS)
        super_key = any(self.keys[key // 8] & (1 << (key % 8)) for key in SUPER_KEYS)
        if not alt and not super_key:
            self.armed = True
        active = self.armed and alt and super_key
        if active != self.active:
            self.active = active
            self.on_change(active)
        return GLib.SOURCE_CONTINUE

    def close(self):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class PortalShortcut:
    def __init__(self, on_change, on_status):
        self.bus = None
        self.on_change = on_change
        self.on_status = on_status
        self.session = None
        self.signals = []
        self.pending = {}
        self.closed = False

    def connect(self):
        try:
            address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
        except GLib.Error as error:
            self.fail(f"The desktop session bus is unavailable. {error.message}")
            return
        flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
        Gio.DBusConnection.new_for_address(address, flags, None, None, self.bus_connected)

    def bus_connected(self, _source, result):
        try:
            bus = Gio.DBusConnection.new_for_address_finish(result)
        except GLib.Error as error:
            if not self.closed:
                self.fail(f"Could not connect to the desktop session bus. {error.message}")
            return
        if self.closed:
            bus.close(None, None)
            return
        self.bus = bus
        self.bus.connect("closed", self.bus_closed)
        self.bus.call(
            DESTINATION, DESKTOP_PATH, REGISTRY, "Register", GLib.Variant("(sa{sv})", (APP_ID, {})),
            None, Gio.DBusCallFlags.NONE, 5000, None, self.registered,
        )

    def bus_closed(self, *_args):
        if not self.closed:
            self.fail("The desktop session bus closed. Retry the shortcut to reconnect.")

    def registered(self, connection, result):
        if self.closed:
            return
        try:
            connection.call_finish(result)
        except GLib.Error as error:
            if Gio.DBusError.get_remote_error(error) not in {
                "org.freedesktop.DBus.Error.UnknownInterface", "org.freedesktop.DBus.Error.UnknownMethod"
            }:
                self.fail(f"The desktop could not register Deektator. {error.message}")
                return
        options = {"session_handle_token": GLib.Variant("s", "s" + uuid.uuid4().hex)}
        self.request("CreateSession", "(a{sv})", (), options, self.session_created)

    def request(self, method, signature, args, options, callback):
        token = "r" + uuid.uuid4().hex
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        path = f"{DESKTOP_PATH}/request/{sender}/{token}"
        options["handle_token"] = GLib.Variant("s", token)

        def responded(*values):
            subscription = self.pending.pop(path, None)
            if subscription:
                self.bus.signal_unsubscribe(subscription)
            if self.closed:
                return
            code, results = values[-1].unpack()
            if code == 0:
                callback(results)
            else:
                if code == 1:
                    if method == "BindShortcuts":
                        self.on_status("Shortcut setup cancelled. Assign Hold to dictate in Shortcut Settings.", False)
                    else:
                        self.fail("Shortcut setup cancelled.")
                else:
                    self.fail("The desktop rejected the shortcut.")

        def sent(connection, result):
            try:
                connection.call_finish(result)
            except GLib.Error as error:
                if not self.closed and path in self.pending:
                    self.fail(f"Global shortcut unavailable. {error.message}")

        self.pending[path] = self.bus.signal_subscribe(
            DESTINATION, REQUEST, "Response", path, None, Gio.DBusSignalFlags.NONE, responded
        )
        self.bus.call(
            DESTINATION, DESKTOP_PATH, SHORTCUTS, method, GLib.Variant(signature, (*args, options)),
            None, Gio.DBusCallFlags.NONE, 10_000, None, sent,
        )

    def session_created(self, results):
        self.session = results.get("session_handle")
        if not isinstance(self.session, str) or not self.session.startswith(DESKTOP_PATH + "/session/"):
            self.fail("The desktop did not create a shortcut session.")
            return
        for member in ("Activated", "Deactivated", "ShortcutsChanged"):
            self.signals.append(self.bus.signal_subscribe(
                DESTINATION, SHORTCUTS, member, DESKTOP_PATH, None,
                Gio.DBusSignalFlags.NONE, self.shortcut_signal,
            ))
        self.signals.append(self.bus.signal_subscribe(
            DESTINATION, SESSION, "Closed", self.session, None, Gio.DBusSignalFlags.NONE,
            lambda *_: self.fail("The desktop closed the shortcut session."),
        ))
        shortcuts = [(SHORTCUT_ID, {
            "description": GLib.Variant("s", "Hold to dictate"),
            "preferred_trigger": GLib.Variant("s", PREFERRED),
        })]
        self.request("BindShortcuts", "(oa(sa{sv})sa{sv})", (self.session, shortcuts, ""), {}, self.binding_changed)

    def shortcut_signal(self, _bus, _sender, _path, _interface, member, values):
        session, *payload = values.unpack()
        if self.closed or session != self.session:
            return
        if member == "ShortcutsChanged":
            self.binding_changed({"shortcuts": payload[0]})
        elif payload[0] == SHORTCUT_ID:
            self.on_change(member == "Activated")

    def binding_changed(self, results):
        description = next(
            (options.get("trigger_description") for key, options in results.get("shortcuts", []) if key == SHORTCUT_ID),
            None,
        )
        if description:
            self.on_status(re.sub(r"\s*\+\s*", " + ", description), True)
        else:
            self.on_change(False)
            self.on_status("No global shortcut assigned. Choose a key for Hold to dictate in Shortcut Settings.", False)

    def configure(self):
        def configured(connection, result):
            try:
                connection.call_finish(result)
            except GLib.Error:
                if not self.closed:
                    self.on_status("Open KDE System Settings → Shortcuts to change Hold to dictate.", False)

        self.bus.call(
            DESTINATION, DESKTOP_PATH, SHORTCUTS, "ConfigureShortcuts",
            GLib.Variant("(osa{sv})", (self.session, "", {})),
            None, Gio.DBusCallFlags.NONE, 5000, None, configured,
        )

    def fail(self, message):
        self.on_change(False)
        self.close()
        self.on_status(message, False)

    def close(self):
        self.closed = True
        if not self.bus:
            return
        for subscription in self.signals:
            self.bus.signal_unsubscribe(subscription)
        self.signals.clear()
        for path, subscription in self.pending.items():
            self.bus.signal_unsubscribe(subscription)
            self.bus.call(DESTINATION, path, REQUEST, "Close", None, None, Gio.DBusCallFlags.NONE, 1000)
        self.pending.clear()
        if self.session:
            self.bus.call(DESTINATION, self.session, SESSION, "Close", None, None, Gio.DBusCallFlags.NONE, 1000)
            self.session = None
        self.bus.close(None, None)
        self.bus = None
