"""minute: local meeting notes.

    uv run python -m minute                      # desktop app (tray, window, recording indicator)
    uv run python -m minute --tray               # start hidden in the tray (used at Windows login)
    uv run python -m minute record [--seconds N] # headless capture in the terminal, Ctrl+C to stop
"""
import argparse
import ctypes
import sys

from minute import config

MUTEX_NAME = "Local\\minute-single-instance"
ERROR_ALREADY_EXISTS = 183


def record(args):
    from minute import storage, titles
    from minute.recorder import Recorder

    def on_event(ev):
        if ev["type"] == "state":
            print(f"-- {ev['state']}", flush=True)
        elif ev["type"] == "text" and ev["delta"].strip():
            print(f"[{ev['t']}] {ev['label']:<4} {ev['delta'].strip()}", flush=True)
        elif ev["type"] == "model_missing":
            print("error: speech model not found; open the app once to download it, or pass --model",
                  file=sys.stderr, flush=True)
        elif ev["type"] == "error":
            print(f"error: {ev['message']}", file=sys.stderr, flush=True)

    rec = Recorder(args.engine_dir, on_event, model_path=args.model, language=args.lang)
    rec.start(seconds=args.seconds)
    try:
        rec.wait()
    except KeyboardInterrupt:
        rec.stop()
        rec.wait()
    rec.close()
    if not rec.call_id or not storage.call_dir(rec.call_id).exists():
        return
    try:
        title = titles.title_call(rec.call_id)
        if title:
            print(f"title: {title}")
    except titles.TitleError as e:
        print(f"no AI title: {e}", file=sys.stderr)
    print(f"saved to {storage.call_dir(rec.call_id)}")


def _focus_running_instance():
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "minute")
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)


def desktop(args):
    # One minute per user: a second launch (e.g. Start menu while it sits in the tray) focuses the first,
    # checked before any heavy import so that it takes a blink.
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        _focus_running_instance()
        return
    # Own taskbar identity, so Windows shows minute's icon instead of Python's.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("minute")
    from minute.app import run

    try:
        run(args)
    finally:
        kernel32.CloseHandle(mutex)


def main():
    if sys.stdout:  # None under pythonw / the windowed build
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="minute")
    config.add_arguments(ap)
    ap.add_argument("--tray", action="store_true", help="start hidden in the tray")
    sub = ap.add_subparsers(dest="cmd")
    rp = sub.add_parser("record", help="capture and transcribe in the terminal")
    rp.add_argument("--seconds", type=float, help="stop after N seconds (default: until Ctrl+C)")
    args = ap.parse_args()
    if args.cmd == "record":
        record(args)
    else:
        desktop(args)


if __name__ == "__main__":
    main()
