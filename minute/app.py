"""Desktop app: tray icon, main window (home, notes, settings) and a minimal recording indicator."""
import ctypes
import json
import os
import threading

import pystray
import webview
from PIL import Image

from minute import config, model, settings, storage, titles
from minute.indicator import Indicator
from minute.recorder import Recorder

MUTEX_NAME = "Local\\minute-single-instance"
ERROR_ALREADY_EXISTS = 183


class Api:
    """Exposed to the web view as window.pywebview.api.*"""

    def __init__(self, app):
        self._app = app

    # calls
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

    def retitle(self, call_id):
        self._app.generate_title(call_id, force=True)

    # recording
    def status(self):
        rec = self._app.recorder
        return {"state": rec.state, "call_id": rec.call_id, "model_ready": config.find_model() is not None
                or bool(self._app.args.model), "downloading": self._app.downloading}

    def start(self):
        self._app.start()

    def stop(self):
        self._app.stop()

    def download_model(self):
        self._app.download_model()

    # settings
    def get_settings(self):
        values = settings.load()
        values["ai_key"] = "•" * 8 if values["ai_key"] else ""  # never send the key back to the page
        values["pi_key_available"] = settings.pi_key_available()
        return values

    def save_settings(self, values):
        if values.get("ai_key", "").startswith("•"):
            values.pop("ai_key")  # unchanged placeholder
        settings.save(values)
        return self.get_settings()

    def choose_folder(self):
        picked = self._app.main.create_file_dialog(webview.FileDialog.FOLDER,
                                                   directory=str(settings.recordings_dir()))
        return picked[0] if picked else None

    def test_ai(self):
        try:
            title = titles.generate({"blocks": [], "notes": "Weekly sync: agreed to ship the beta on Friday, "
                                                            "Marco owns the release notes."})
            return {"ok": True, "title": title}
        except titles.TitleError as e:
            return {"ok": False, "error": str(e)}


class App:
    def __init__(self, args):
        self.args = args
        self.recorder = Recorder(args.engine_dir, self._on_event, model_path=args.model, language=args.lang)
        self.api = Api(self)
        self.quitting = False
        self.downloading = False
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

    def _emit(self, ev):
        self._js(self.main, f"window.minute && minute.onEvent({json.dumps(ev, ensure_ascii=False)})")

    def _on_event(self, ev):
        self._emit(ev)
        if ev["type"] == "levels":
            self.indicator.set_level(max(ev.get("YOU", 0), ev.get("THEM", 0)))
        elif ev["type"] == "state":
            if ev["state"] == "recording":
                self.indicator.show()
            elif ev["state"] == "idle":
                self.indicator.hide()
            self._refresh_tray()
        elif ev["type"] == "saved":
            self.generate_title(ev["call_id"])
        elif ev["type"] == "model_missing":
            self.show_main()

    def generate_title(self, call_id, force=False):
        def work():
            self._emit({"type": "titling", "call_id": call_id})
            try:
                if force:
                    storage.rename_call(call_id, storage.load_call(call_id)["title"], source="default")
                title = titles.title_call(call_id)
                self._emit({"type": "title", "call_id": call_id, "title": title})
            except Exception as e:  # TitleError, or anything unexpected: the call keeps its default name
                self._emit({"type": "title", "call_id": call_id, "title": None, "error": str(e)})

        threading.Thread(target=work, daemon=True).start()

    def download_model(self):
        if self.downloading:
            return
        self.downloading = True

        def work():
            last = [-1]

            def progress(done, total):
                pct = int(done * 100 / total) if total else 0
                if pct != last[0]:
                    last[0] = pct
                    self._emit({"type": "download", "done": done, "total": total})

            try:
                model.download(progress)
                self._emit({"type": "download_done"})
            except Exception as e:
                self._emit({"type": "download_error", "message": str(e)})
            finally:
                self.downloading = False

        threading.Thread(target=work, daemon=True).start()

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
            "minute", url=str(config.UI / "main.html"), js_api=self.api, hidden=self.args.tray,
            width=880, height=760, min_size=(560, 480), background_color="#F7F6F1",
        )
        self.main.events.closing += self._on_main_closing
        self.indicator = Indicator(on_click=self.show_main, on_stop=self.stop)
        self._build_tray()
        webview.start(icon=str(config.ICON_ICO))


def _focus_running_instance():
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "minute")
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)


def run(args):
    # One minute per user: a second launch (e.g. Start menu while it sits in the tray) focuses the first.
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        _focus_running_instance()
        return
    # Own taskbar identity, so Windows shows minute's icon instead of Python's.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("minute")
    try:
        App(args).run()
    finally:
        ctypes.windll.kernel32.CloseHandle(mutex)
