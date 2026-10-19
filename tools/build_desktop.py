"""Build and verify a standalone Mac app before archiving it."""

from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def sign_bundle(app):
    # py2app can merge two liblzma libraries with the same basename into
    # Frameworks while retaining the Mach-O layout of the first one. Keep
    # Pillow's already-copied, valid library as the single bundled version.
    destination = app / "Contents/Frameworks/liblzma.5.dylib"
    source = app / "Contents/Resources/lib/python3.11/lib-dynload/PIL/.dylibs/liblzma.5.dylib"
    checked = subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(destination)],
                             capture_output=True)
    if checked.returncode:
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(source)], check=True)
        shutil.copyfile(source, destination)
        subprocess.run(["/usr/bin/install_name_tool", "-id", "@executable_path/../Frameworks/liblzma.5.dylib",
                        str(destination)], check=True)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(destination)], check=True)
    subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)


def build():
    if sys.platform != "darwin":
        raise RuntimeError("Build this Mac app on macOS")
    subprocess.run([sys.executable, "setup_desktop.py", "py2app", "--dist-dir", "dist/desktop",
                    "--bdist-base", "build/desktop"], cwd=ROOT, check=True)
    app = ROOT / "dist/desktop/LLM SugarScape.app"
    sign_bundle(app)
    return app


if __name__ == "__main__":
    print(build())
