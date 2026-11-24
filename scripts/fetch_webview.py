"""Download the webview C library (webview/webview 0.12, as built by webview_deno 0.9.0) into vendor/webview/.

The main window hosts WebView2 through it. Each file is checked against its SHA-256 before it is kept.
WebView2Loader.dll is Microsoft's, signed by Microsoft; webview.dll is the project's CI build.
"""
import hashlib
import urllib.request
from pathlib import Path

VERSION = "0.9.0"
BASE = f"https://github.com/webview/webview_deno/releases/download/{VERSION}/"
FILES = {
    "webview.dll": "fec1e559a6ff67e695416b5cf42221eb319ea3ccb6719c05dbd2ae01a3c9810a",
    "WebView2Loader.dll": "184574b9c36b044888644fc1f2b19176e0e76ccc3ddd2f0a5f0d618c88661f86",
}
VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "webview"

if __name__ == "__main__":
    VENDOR.mkdir(parents=True, exist_ok=True)
    for name, sha256 in FILES.items():
        print(f"downloading {BASE}{name}")
        data = urllib.request.urlopen(BASE + name).read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != sha256:
            raise SystemExit(f"{name}: SHA-256 {digest} does not match the pinned {sha256}")
        (VENDOR / name).write_bytes(data)
    print(f"saved to {VENDOR}")
