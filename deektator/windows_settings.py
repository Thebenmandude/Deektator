"""The Windows shortcut settings dialog."""

import tkinter as tk
from dataclasses import replace
from tkinter import ttk

from .settings import MODIFIER_KEYS, SHORTCUT_KEYS, ShortcutSettings


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, settings, on_save, on_close):
        super().__init__(parent)
        self.on_save = on_save
        self.on_close = on_close
        self.last_valid = settings
        self.title("Deektator Settings")
        self.transient(parent)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())

        body = ttk.Frame(self, padding=20)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        ttk.Label(body, text="Dictation shortcut", font=("Segoe UI", 14, "bold")).grid(sticky="w")
        ttk.Label(body, text="Hold your shortcut to record. Release to transcribe.", wraplength=380).grid(
            sticky="w", pady=(4, 16)
        )
        self.enabled = tk.BooleanVar(self, value=settings.enabled)
        ttk.Checkbutton(body, text="Enable global shortcut", variable=self.enabled, command=self.refresh).grid(sticky="w")

        self.controls = []
        modifiers = ttk.LabelFrame(body, text="Modifier keys", padding=10)
        modifiers.grid(sticky="ew", pady=(12, 10))
        self.modifiers = {}
        for column, name in enumerate(MODIFIER_KEYS):
            variable = tk.BooleanVar(self, value=name in settings.modifiers)
            self.modifiers[name] = variable
            control = ttk.Checkbutton(modifiers, text=name, variable=variable, command=self.refresh)
            control.grid(row=0, column=column, padx=(0, 12))
            self.controls.append(control)

        ttk.Label(body, text="Additional key").grid(sticky="w")
        self.key = tk.StringVar(self, value=settings.key or "None (modifiers only)")
        self.key_input = ttk.Combobox(
            body, textvariable=self.key, state="readonly", values=("None (modifiers only)", *SHORTCUT_KEYS), width=30,
        )
        self.key_input.grid(sticky="ew", pady=(4, 12))
        self.key_input.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        self.preview = tk.StringVar(self)
        ttk.Label(body, textvariable=self.preview, wraplength=380, font=("Segoe UI", 10, "bold")).grid(sticky="w")
        ttk.Label(
            body, text="Choose a combination unused by your other apps.\nThe shortcut is paused while Settings is open.",
            wraplength=380,
        ).grid(sticky="w", pady=(8, 0))
        self.error = tk.StringVar(self)
        ttk.Label(body, textvariable=self.error, wraplength=380, foreground="#a12622").grid(sticky="w", pady=(8, 8))

        buttons = ttk.Frame(body)
        buttons.grid(sticky="ew")
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="Restore default", command=self.restore_default).grid(row=0, column=0)
        ttk.Button(buttons, text="Cancel", command=self.close).grid(row=0, column=2, padx=(16, 8))
        self.save_button = ttk.Button(buttons, text="Save", command=self.save)
        self.save_button.grid(row=0, column=3)
        self.refresh()
        self.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_reqwidth()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_reqheight()) // 2)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.save_button.focus_set()

    def selection(self):
        if not self.enabled.get():
            return replace(self.last_valid, enabled=False)
        return ShortcutSettings(
            tuple(name for name, variable in self.modifiers.items() if variable.get()),
            None if self.key.get() == "None (modifiers only)" else self.key.get(),
            self.enabled.get(),
        )

    def refresh(self):
        self.error.set("")
        for control in self.controls:
            control.configure(state="normal" if self.enabled.get() else "disabled")
        self.key_input.configure(state="readonly" if self.enabled.get() else "disabled")
        try:
            settings = self.selection()
        except ValueError as error:
            self.preview.set("Choose your shortcut")
            self.error.set(str(error))
            self.save_button.configure(state="disabled")
        else:
            self.last_valid = settings
            self.preview.set(settings.label if settings.enabled else "Global shortcut is off")
            self.save_button.configure(state="normal")

    def restore_default(self):
        settings = ShortcutSettings()
        self.enabled.set(settings.enabled)
        for name, variable in self.modifiers.items():
            variable.set(name in settings.modifiers)
        self.key.set("None (modifiers only)")
        self.refresh()

    def save(self):
        try:
            self.on_save(self.selection())
        except (OSError, ValueError) as error:
            self.error.set(f"Could not save settings. {error}")
            return
        self.close()

    def close(self):
        self.grab_release()
        self.destroy()
        self.on_close()
