import threading

from minute import calls


def test_only_call_apps_count(monkeypatch):
    exes = {1: "chrome.exe", 2: "handy.exe", 3: "minute.exe", 4: "ms-teams.exe", 5: ""}
    monkeypatch.setattr(calls, "capturing_pids", lambda: set(exes))
    monkeypatch.setattr(calls, "_exe_name", exes.get)
    assert calls.active_call_apps() == {"Chrome", "Teams"}


def test_capturing_pids_runs_on_this_machine():
    # Real COM round trip on a thread with COM initialised, as CallWatcher's: must not raise.
    out = {}

    def run():
        calls.ctypes.windll.ole32.CoInitializeEx(None, 0)
        out["pids"] = calls.capturing_pids()

    t = threading.Thread(target=run)
    t.start()
    t.join(10)
    assert isinstance(out["pids"], set)


class FakeRecorder:
    busy = False
    auto = False


def test_watcher_starts_on_a_call(monkeypatch):
    started = []
    monkeypatch.setattr(calls, "active_call_apps", lambda: {"Zoom"})
    w = calls.CallWatcher.__new__(calls.CallWatcher)
    w.recorder, w.start, w.stop, w.enabled, w.ending = FakeRecorder(), started.append, None, lambda: True, lambda s: None
    w._ending, w.apps, w._last_seen, w._suppressed = None, set(), 0.0, False
    w._tick()
    assert started == ["Zoom"]
