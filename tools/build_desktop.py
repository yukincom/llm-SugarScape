"""Build and verify a standalone Mac app before archiving it."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_presets import APP_VERSION
from tls_security import checked_ca_file, require_build_environment
from tools.verify_desktop import refresh_bundle_ca, verify_bundle


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
    # py2app already signed nested code; liblzma is signed above and the Rust
    # core below. Re-sign only the root so the native binary hash stays fixed.
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(app)], check=True)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)


def build():
    if sys.platform != "darwin":
        raise RuntimeError("Build this Mac app on macOS")
    require_build_environment()
    destination = ROOT / "dist" / f"desktop-{APP_VERSION}"
    if destination.exists():
        raise FileExistsError(f"Refusing to reuse a previous build: {destination}")
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"desktop-{APP_VERSION}-", dir=ROOT / "build") as temporary:
        ca_directory = Path(temporary) / "trusted-ca"
        (ca_directory / "certs").mkdir(parents=True)
        shutil.copyfile(checked_ca_file(), ca_directory / "cert.pem")
        environment = os.environ.copy()
        environment.update({"SSL_CERT_FILE": str(ca_directory / "cert.pem"),
                            "SSL_CERT_DIR": str(ca_directory / "certs")})
        subprocess.run([sys.executable, "setup_desktop.py", "py2app", "--dist-dir", str(destination),
                        "--bdist-base", str(Path(temporary) / "objects")],
                       cwd=ROOT, env=environment, check=True)
    app = destination / "LLM SugarScape.app"
    refresh_bundle_ca(app)
    # py2app strips/re-signs data_files dylibs. Restore the exact reviewed,
    # signed Rust artifact and its manifest before the final root signature.
    from native_geometry import LIBRARY_NAME
    for name in (LIBRARY_NAME, "build.json"):
        shutil.copyfile(ROOT / "native" / name, app / "Contents/Resources/native" / name)
    sign_bundle(app)
    verify_bundle(app)
    return app


if __name__ == "__main__":
    print(build())
