"""minute: local meeting notes.

    uv run python -m minute                      # desktop app (tray + window + overlay)
    uv run python -m minute record [--seconds N] # headless capture in the terminal, Ctrl+C to stop
"""
import argparse
import sys

from minute import config


def record(args):
    from minute import storage
    from minute.recorder import Recorder

    def on_event(ev):
        if ev["type"] == "state":
            print(f"-- {ev['state']}", flush=True)
        elif ev["type"] == "text" and ev["delta"].strip():
            print(f"[{ev['t']}] {ev['label']:<4} {ev['delta'].strip()}", flush=True)
        elif ev["type"] == "error":
            print(f"error: {ev['message']}", file=sys.stderr, flush=True)

    rec = Recorder(args.engine_dir, args.model, args.lang, on_event)
    rec.start(seconds=args.seconds)
    try:
        rec.wait()
    except KeyboardInterrupt:
        rec.stop()
        rec.wait()
    if rec.call_id:
        print(f"saved to {storage.call_dir(rec.call_id)}")
    rec.close()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="minute")
    config.add_arguments(ap)
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
