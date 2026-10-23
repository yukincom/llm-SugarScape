"""Create the project venv, authenticate pip before any dependency resolution."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import urlopen
import venv

ROOT = Path(__file__).resolve().parents[1]
# Python security team's published bootstrap, not an unhashed index lookup:
# https://discuss.python.org/t/109576
PIP_SHA256 = "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
PIP_WHEEL = "pip-26.2.2-py3-none-any.whl"
PIP_URL = ("https://files.pythonhosted.org/packages/3f/06/"
           "3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/" + PIP_WHEEL)


def install_environment(directory, *, desktop=False):
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Use Python 3.11 for this application and its standalone build.")
    directory = Path(directory).resolve()
    if not (directory / "pyvenv.cfg").is_file():
        if directory.exists() and any(directory.iterdir()):
            raise RuntimeError("Refusing to replace a nonempty directory without pyvenv.cfg")
        venv.EnvBuilder(with_pip=True).create(directory)
    python = directory / "bin/python"
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("PIP_") and key not in
                   ("PYTHONPATH", "PYTHONHOME", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR")}
    environment["PIP_CONFIG_FILE"] = os.devnull
    with tempfile.TemporaryDirectory(prefix="sugarscape-pip-") as temporary:
        wheel = Path(temporary) / PIP_WHEEL
        # TLS validation remains enabled. The official out-of-band hash also
        # authenticates this first transfer even when the old CA store is stale.
        with urlopen(PIP_URL, timeout=60) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != PIP_SHA256:
            raise RuntimeError("pip bootstrap SHA-256 mismatch; no downloaded code was executed")
        wheel.write_bytes(payload)
        command = [str(python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-cache-dir"]
        subprocess.run([*command, "install", "--no-index", "--no-deps", "--force-reinstall", str(wheel)],
                       env=environment, check=True)
        # pip 26.2.2 contains certifi 2026.10.19. Exclude an outdated OS/Homebrew
        # trust store while resolving packages; this does not disable TLS.
        subprocess.run([*command, "install", "--use-deprecated=legacy-certs", "--upgrade", "-r",
                        str(ROOT / ("requirements-desktop.txt" if desktop else "requirements.txt"))],
                       env=environment, check=True)
        subprocess.run([*command, "check"], env=environment, check=True)
    subprocess.run([str(python), "-c", "from tls_security import require_build_environment, tls_context; "
                    "print(require_build_environment()); tls_context()"], cwd=ROOT, env=environment, check=True)
    subprocess.run([str(python), str(ROOT / "tools/build_native.py")], cwd=ROOT, env=environment, check=True)
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv")
    parser.add_argument("--desktop", action="store_true")
    args = parser.parse_args()
    print(install_environment(args.venv, desktop=args.desktop))
