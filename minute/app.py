"""Desktop app: tray icon, main window (home, notes, settings) and a minimal recording indicator."""
import ctypes
import json
import os
import threading
import time
import webbrowser

import pystray
import webview
from PIL import Image

import minute
from minute import ai, ask, config, model, settings, storage, titles
from minute.calls import CallWatcher
from minute.indicator import Indicator
from minute.recorder import Recorder
from minute.worker import Worker

MUTEX_NAME = "Local\\minute-single-instance"
UNLOAD_AFTER = float(os.environ.get("MINUTE_UNLOAD_AFTER", 600))  # seconds without calls before the model is freed
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

    def save_enhanced(self, call_id, text):
        storage.save_enhanced(call_id, text, source="user")

    def regenerate_enhanced(self, call_id):
        storage.update_meta(call_id, enhanced_status="pending", enhanced_error=None, enhanced_edited=False)
        self._app.worker.kick()

    def delete_call(self, call_id):
        storage.delete_call(call_id)

    def open_raw(self, call_id, what):
        """what: "you" / "them" (audio, in the default player), "text" (raw live transcript), "folder"."""
        if what == "folder":
            os.startfile(storage.call_dir(call_id))
        elif what == "text":
            os.startfile(storage.raw_text_file(call_id))
        elif what in ("you", "them"):
            wav = storage.call_dir(call_id) / f"{what}.wav"
            if not wav.exists():
                return False
            os.startfile(wav)
        return True

    def retitle(self, call_id):
        storage.update_meta(call_id, title_source="default", title_status="pending")
        self._app.worker.kick()

    def retry(self, call_id):
        """Redo whatever failed for this call (transcript from audio, AI title) now."""
        meta = storage.read_meta(call_id)
        if meta.get("title_status") == "pending":
            storage.update_meta(call_id, title_error=None)
        self._app.worker.kick()

    # recording
    def status(self):
        rec = self._app.recorder
        return {"state": rec.state, "call_id": rec.call_id, "auto": rec.auto,
                "engine": rec.engine_state, "engine_error": rec.engine_error,
                "model_ready": config.find_model() is not None or bool(self._app.args.model),
                "downloading": self._app.downloading}

    def start(self):
        self._app.start()

    def stop(self):
        self._app.stop()

    def keep_recording(self):
        """Cancel the auto-stop countdown: from now on this note only stops when the user stops it."""
        self._app.recorder.auto = False
        self._app.on_call_ending(None)

    def download_model(self):
        self._app.download_model()

    # about
    def about(self):
        try:
            changelog = config.CHANGELOG.read_text(encoding="utf-8")
        except OSError:
            changelog = ""
        return {"version": minute.__version__, "author": minute.AUTHOR, "website": minute.WEBSITE,
                "repo": minute.REPO, "changelog": changelog}

    def open_url(self, url):
        if url.startswith(("https://", "http://")):  # links only, never local paths
            webbrowser.open(url)

    # settings
    def get_settings(self):
        values = settings.load()
        values["ai_key"] = "•" * 8 if values["ai_key"] else ""  # never send the key back to the page
        values["pi_key_available"] = settings.pi_key_available()
        values["languages"] = settings.LANGUAGES
        values["windows_language"] = settings.default_language()
        return values

    def save_settings(self, values):
        if values.get("ai_key", "").startswith("•"):
            values.pop("ai_key")  # unchanged placeholder
        settings.save(values)
        self._app.worker.kick()  # e.g. a new API key: pending titles can go now
        return self.get_settings()

    def choose_folder(self):
        picked = self._app.main.create_file_dialog(webview.FileDialog.FOLDER,
                                                   directory=str(settings.recordings_dir()))
        return picked[0] if picked else None

    def ask(self, question, history=None, call_id=None):
        """Ask anything, about one call (call_id) or all of them. Runs on pywebview's worker thread."""
        try:
            return {"ok": True, "answer": ask.ask(question, [tuple(t) for t in history or []], call_id or None)}
        except ai.AIError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # never leave the page waiting
            return {"ok": False, "error": f"something went wrong: {e}"}

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
        self.worker = None
        self.watcher = None
        self._auto_stopping = False

    # --- recording -------------------------------------------------------
    def start(self):
        self.recorder.start()
        self._refresh_tray()

    def auto_start(self, app):
        if self.recorder.start(auto=True, app=app):
            self._notify(f"Taking notes on your {app} call. Hover the pill on the right to stop.")

    def stop(self, source="window"):
        """A stop from the user (window, pill, tray), as opposed to the call ending."""
        if self.watcher:
            self.watcher.user_stopped()
        self.recorder.stop(source)

    def on_call_ending(self, seconds):
        self.indicator.set_ending(seconds is not None)
        self._emit({"type": "call_ending", "seconds": seconds})

    def _auto_stop(self):
        self._auto_stopping = True
        self.recorder.stop("call ended")

    def toggle(self):
        self.stop("tray") if self.recorder.busy else self.start()

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
                self._auto_stopping = False
            self._refresh_tray()
        elif ev["type"] == "saved":
            self.worker.kick()  # transcript catch-up, AI title, audio cleanup
            if self._auto_stopping:
                self._notify("Call ended. Your notes are saved; enhanced notes are on the way.")
        elif ev["type"] == "model_missing" and not self.recorder.auto:
            self.show_main()
        elif ev["type"] == "model_missing":
            self._notify("Recording audio only: the speech model isn't downloaded yet. Open minute to get it.")

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
                self.worker.kick()  # transcribe what was recorded as audio only
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
        self.tray = pystray.Icon("minute", Image.open(config.ICON), f"minute {minute.__version__}", menu)
        self.tray.run_detached()

    def _unload_when_idle(self):
        # The model is loaded at the start of each call (audio is captured meanwhile) and freed
        # after UNLOAD_AFTER without calls: minute idles at a fraction of the memory.
        while not self.quitting:
            time.sleep(min(60, UNLOAD_AFTER / 2))
            self.recorder.unload_if_idle(UNLOAD_AFTER)

    def _notify(self, message):
        try:
            self.tray.notify(message, "minute")
        except Exception:
            pass  # notifications are a nicety

    def _refresh_tray(self):
        if self.tray:
            self.tray.title = f"minute {minute.__version__}" + (" (recording)" if self.recorder.busy else "")
            self.tray.update_menu()

    def quit(self):
        self.quitting = True
        threading.Thread(target=self._shutdown, daemon=True).start()

    def _shutdown(self):
        self.worker.stop()
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
        self.indicator = Indicator(on_click=self.show_main, on_stop=lambda: self.stop("pill"))
        self._build_tray()
        storage.recover_interrupted()  # calls cut short by a crash or power loss
        threading.Thread(target=self._unload_when_idle, name="minute-unload", daemon=True).start()
        self.worker = Worker(self.recorder, self._emit)
        self.watcher = CallWatcher(self.recorder, start=self.auto_start, stop=self._auto_stop,
                                   enabled=lambda: settings.load()["auto_record"], ending=self.on_call_ending)
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
