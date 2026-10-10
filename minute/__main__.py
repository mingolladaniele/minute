"""minute: local meeting notes.

    uv run python -m minute                      # desktop app (tray, window, recording indicator)
    uv run python -m minute --tray               # start hidden in the tray (used at Windows login)
    uv run python -m minute record [--seconds N] # headless capture in the terminal, Ctrl+C to stop
"""
import argparse
import sys

from minute import config


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
        from minute.app import run
        run(args)


if __name__ == "__main__":
    main()
