"""Download the prebuilt transcribe.cpp native library (Windows, Vulkan) into vendor/."""
import io
import tarfile
import urllib.request
from pathlib import Path

VERSION = "0.3.1"
URL = (
    f"https://github.com/handy-computer/transcribe.cpp/releases/download/v{VERSION}/"
    f"transcribe-native-{VERSION}-windows-x86_64-cpu-vulkan.tar.gz"
)
VENDOR = Path(__file__).resolve().parent.parent / "vendor"

if __name__ == "__main__":
    VENDOR.mkdir(exist_ok=True)
    print(f"downloading {URL}")
    data = urllib.request.urlopen(URL).read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(VENDOR, filter="data")
    print(f"extracted to {VENDOR}")
