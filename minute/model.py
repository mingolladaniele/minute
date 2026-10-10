"""Download the speech model on machines that don't already have it from Handy."""
import urllib.request

from minute import config

CHUNK = 1 << 20


def download(on_progress):
    """Fetch the GGUF into LOCAL_DATA/models, calling on_progress(done_bytes, total_bytes)."""
    dest = config.DOWNLOADED_MODEL
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    with urllib.request.urlopen(config.MODEL_URL, timeout=60) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(CHUNK):
            f.write(chunk)
            done += len(chunk)
            on_progress(done, total)
    part.replace(dest)  # only a complete file ever has the final name
    return dest
