"""Archive the self-contained Mac app, preserving executable bits and links."""

import hashlib
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_presets import APP_VERSION

def build_release(app=None, destination=None):
    app = Path(app) if app else ROOT / "dist/desktop/LLM SugarScape.app"
    app = app.absolute()
    if not app.is_dir() or app.is_symlink() or app.suffix != ".app":
        raise ValueError("Build the standalone Mac app first")
    with (app / "Contents/Info.plist").open("rb") as handle:
        info = plistlib.load(handle)
    if info.get("PythonInfoDict", {}).get("py2app", {}).get("alias") is not False:
        raise ValueError("An alias build must never be distributed")
    if not (app / "Contents/Frameworks/libpython3.11.dylib").is_file():
        raise ValueError("The Python runtime is missing")
    for path in app.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(app.resolve()):
            raise ValueError(f"External link in app: {path.relative_to(app)}")
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    destination = Path(destination) if destination else ROOT / "dist"
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"LLM-SugarScape-{APP_VERSION}-Mac-arm64.zip"
    # Reserve the name before invoking ditto. A failed build remains visible
    # and is not silently mistaken for an earlier reviewed release.
    with archive.open("xb"):
        pass
    subprocess.run(["/usr/bin/ditto", "-c", "-k", "--keepParent", str(app), str(archive)], check=True)
    archive.with_suffix(".zip.sha256").write_text(
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n", encoding="utf-8")
    return archive


if __name__ == "__main__":
    print(build_release())
