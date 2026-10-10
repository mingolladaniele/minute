"""Desktop app: tray icon, main window (home + notes) and a minimal recording indicator."""
import ctypes
import json
import os
import threading
from pathlib import Path

import pystray
import webview
from PIL import Image

from minute import config, storage
from minute.indicator import Indicator
from minute.recorder import Recorder

UI = Path(__file__).resolve().parent / "ui"


class Api:
    """Exposed to the web view as window.pywebview.api.*"""

    def __init__(self, app):
        self._app = app

    def list_calls(self):
        return storage.list_calls()

    def get_call(self, call_id):
        return storage.load_call(call_id)

    def rename_call(self, call_id, title):
        storage.rename_call(call_id, title)

    def save_notes(self, call_id, text):
        storage.save_notes(call_id, text)

    def delete_call(self, call_id):
        storage.delete_call(call_id)

    def open_folder(self, call_id):
        os.startfile(storage.call_dir(call_id))

    def status(self):
        rec = self._app.recorder
        return {"state": rec.state, "call_id": rec.call_id}

    def start(self):
        self._app.start()

    def stop(self):
        self._app.stop()


class App:
    def __init__(self, args):
        self.recorder = Recorder(args.engine_dir, args.model, args.lang, self._on_event)
        self.api = Api(self)
        self.quitting = False
        self.main = None
        self.indicator = None
        self.tray = None

    # --- recording -------------------------------------------------------
    def start(self):
        self.recorder.start()
        self._refresh_tray()

    def stop(self):
        self.recorder.stop()

    def toggle(self):
        self.stop() if self.recorder.busy else self.start()

    def _on_event(self, ev):
        payload = json.dumps(ev, ensure_ascii=False)
        self._js(self.main, f"window.minute && minute.onEvent({payload})")
        if ev["type"] == "levels":
            self.indicator.set_level(max(ev.get("YOU", 0), ev.get("THEM", 0)))
        elif ev["type"] == "state":
            if ev["state"] == "recording":
                self.indicator.show()
            elif ev["state"] == "idle":
                self.indicator.hide()
            self._refresh_tray()

    @staticmethod
    def _js(window, script):
        if window is None:
            return
        try:
            window.evaluate_js(script)
        except Exception:
            pass  # page not ready yet / window being torn down

    # --- windows ---------------------------------------------------------
    def show_main(self):
        self.main.show()
        self.main.restore()

    def _on_main_closing(self):
        if self.quitting:
            return True
        self.main.hide()  # the X sends minute to the tray; Quit lives in the tray menu
        return False

    # --- tray ------------------------------------------------------------
    def _build_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open minute", lambda: self.show_main(), default=True),
            pystray.MenuItem(lambda item: "Stop recording" if self.recorder.busy else "Start recording",
                             lambda: self.toggle()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self.quit()),
        )
        self.tray = pystray.Icon("minute", Image.open(config.ICON), "minute", menu)
        self.tray.run_detached()

    def _refresh_tray(self):
        if self.tray:
            self.tray.title = "minute (recording)" if self.recorder.busy else "minute"
            self.tray.update_menu()

    def quit(self):
        self.quitting = True
        threading.Thread(target=self._shutdown, daemon=True).start()

    def _shutdown(self):
        self.recorder.close()  # finishes and saves a call in progress
        if self.tray:
            self.tray.stop()
        self.indicator.close()
        self.main.destroy()

    def run(self):
        self.main = webview.create_window(
            "minute", url=str(UI / "main.html"), js_api=self.api,
            width=880, height=760, min_size=(560, 480), background_color="#F7F6F1",
        )
        self.main.events.closing += self._on_main_closing
        self.indicator = Indicator(on_click=self.show_main, on_stop=self.stop)
        self._build_tray()
        webview.start(icon=str(config.ROOT / "assets" / "icon.ico"))


def run(args):
    # Own taskbar identity, so Windows shows minute's icon instead of Python's.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("minute")
    App(args).run()
