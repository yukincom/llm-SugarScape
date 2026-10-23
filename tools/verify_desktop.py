"""Check the standalone runtime, CA stores and packaged application sources."""

import ast
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tls_security import checked_ca_file, context_from_ca, require_build_environment


def bundle_ca_paths(resources):
    """Read the paths the pinned py2app bootstrap actually installs."""
    tree = ast.parse((resources / "__boot__.py").read_text())
    setup = next((node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_setup_openssl"), None)
    if setup is None or not any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                               and isinstance(node.value.func, ast.Name)
                               and node.value.func.id == "_setup_openssl" for node in tree.body):
        raise ValueError("Missing py2app OpenSSL bootstrap")
    paths = {}
    for node in setup.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (not isinstance(target, ast.Subscript) or ast.unparse(target.value) != 'os.environ'
                or not isinstance(target.slice, ast.Constant)):
            continue
        name = target.slice.value
        if name not in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
            continue
        expected = ast.parse('os.path.join(resourcepath, "openssl.ca", "' +
                             ("cert.pem" if name == "SSL_CERT_FILE" else "certs") + '")', mode='eval').body
        if ast.dump(node.value) != ast.dump(expected):
            raise ValueError(f"Unexpected {name} in the real py2app bootstrap")
        paths[name] = resources / "openssl.ca" / ("cert.pem" if name == "SSL_CERT_FILE" else "certs")
    if set(paths) != {"SSL_CERT_FILE", "SSL_CERT_DIR"}:
        raise ValueError("Incomplete py2app CA bootstrap")
    return paths


def refresh_bundle_ca(app):
    """Replace py2app's host-derived CA store before signing the fresh build."""
    import shutil

    require_build_environment()
    source = checked_ca_file()
    context_from_ca(source)
    directory = Path(app) / "Contents/Resources/openssl.ca"
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, directory / "cert.pem")
    # Only the new build's CA directory is changed, never the host trust store.
    certificates = directory / "certs"
    if certificates.is_symlink():
        certificates.unlink()
    elif certificates.exists():
        shutil.rmtree(certificates)
    certificates.mkdir()


def verify_bundle(app):
    app = Path(app).resolve()
    resources = app / "Contents/Resources"
    ca_paths = bundle_ca_paths(resources)
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if info.get("PythonInfoDict", {}).get("py2app", {}).get("alias") is not False:
        raise ValueError("A standalone app is required")
    from app_presets import APP_VERSION
    if info["CFBundleVersion"] != APP_VERSION.rsplit('.', 1)[1]:
        raise ValueError("App version does not match the source")
    for path in app.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(app):
            raise ValueError(f"External bundle link: {path.relative_to(app)}")
    setup = ast.parse((ROOT / "setup_desktop.py").read_text())
    files = next(ast.literal_eval(node.value) for node in setup.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "APP_FILES" for target in node.targets))
    files += ["desktop.py", "assets/branding/app-icon.png", "assets/branding/llm-sugar-scape-logo.png"]
    files += [str(path.relative_to(ROOT)) for path in (ROOT / "assets/emoji").iterdir() if path.is_file()]
    hashes = {}
    for name in files:
        raw = (resources / name).read_bytes()
        if raw != (ROOT / name).read_bytes():
            raise ValueError(f"Bundled source differs: {name}")
        hashes[name] = hashlib.sha256(raw).hexdigest()
    if (resources / "AppIcon.icns").read_bytes() != (ROOT / "assets/branding/AppIcon.icns").read_bytes():
        raise ValueError("Bundled app icon differs")
    safe_ca = checked_ca_file().read_bytes()
    if ca_paths["SSL_CERT_FILE"].read_bytes() != safe_ca:
        raise ValueError("py2app OpenSSL CA store is not the approved certifi bundle")
    if sorted(path.name for path in (resources / "openssl.ca").iterdir()) != ["cert.pem", "certs"]:
        raise ValueError("Unexpected additional OpenSSL CA stores")
    if list(ca_paths["SSL_CERT_DIR"].iterdir()):
        raise ValueError("Unexpected additional certificates in OpenSSL CA directory")
    with zipfile.ZipFile(resources / "lib/python311.zip") as archive:
        # py2app stores explicitly included packages outside python311.zip.
        certifi_file = resources / "lib/python3.11/certifi/cacert.pem"
        bundled_ca = certifi_file.read_bytes() if certifi_file.is_file() else archive.read("certifi/cacert.pem")
        if bundled_ca != safe_ca:
            raise ValueError("Bundled certifi CA store differs")
        if any(name.startswith(("pip/", "ensurepip/", "uv/")) for name in archive.namelist()):
            raise ValueError("Installers must not be included in the app")
    for name in ("pip", "ensurepip", "uv"):
        if (resources / "lib/python3.11" / name).exists():
            raise ValueError("Installers must not be included in the app")
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("PYTHON", "DYLD_")) and key not in ("RESOURCEPATH", "EXECUTABLEPATH")}
    # Reproduce py2app's observed _setup_openssl bootstrap without opening a
    # window. Use the bundled interpreter/modules, not the build environment.
    environment.update({"PYTHONHOME": str(resources),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": os.pathsep.join(map(str, (resources, resources / "lib/python311.zip",
                                               resources / "lib/python3.11", resources / "lib/python3.11/lib-dynload"))),
        **{name: str(path) for name, path in ca_paths.items()}})
    probe = '''import hashlib, importlib.util, json, ssl, sys
from tls_security import REJECTED_ROOT_SHA256, security_report
from llm_api import TLS_CONTEXT
import aiohttp.connector
report = security_report()
report["python"] = sys.version.split()[0]
report["installers_present"] = [name for name in ("pip", "ensurepip", "uv") if importlib.util.find_spec(name)]
for name, context in (("default", ssl.create_default_context()), ("aiohttp_default", aiohttp.connector._SSL_CONTEXT_VERIFIED), ("api", TLS_CONTEXT)):
    hashes = {hashlib.sha256(root).hexdigest() for root in context.get_ca_certs(binary_form=True)}
    assert REJECTED_ROOT_SHA256 not in hashes and hashes
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    report[name + "_ca_count"] = len(hashes)
assert not report["installers_present"]
print(json.dumps(report))
'''
    result = subprocess.run([str(app / "Contents/MacOS/python"), "-S", "-c", probe],
                            env=environment, cwd=resources, check=True, capture_output=True, text=True)
    return {"app_version": APP_VERSION, "runtime": json.loads(result.stdout), "source_sha256": hashes}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python tools/verify_desktop.py 'path/to/LLM SugarScape.app'")
    print(json.dumps(verify_bundle(sys.argv[1]), ensure_ascii=False, indent=2))
