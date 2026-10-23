"""One fail-closed CA policy for API calls and standalone builds."""

from functools import lru_cache
import base64
import hashlib
from importlib import metadata
from pathlib import Path
import os
import re
import ssl
import tempfile

from packaging.version import InvalidVersion, Version

MIN_CERTIFI = "2026.10.19"
MIN_PIP = "26.2.2"
MIN_UV = "0.13.4"
# emSign ECC Root CA - G3, removed by certifi 2026.10.19.
REJECTED_ROOT_SHA256 = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b"


class SecurityEnvironmentError(RuntimeError):
    """The application must not use an outdated or unverified trust store."""


def require_version(package, minimum, *, optional=False):
    try:
        installed = metadata.version(package)
    except metadata.PackageNotFoundError as error:
        if optional:
            return None
        raise SecurityEnvironmentError(f"{package} >= {minimum} is required; recreate the environment.") from error
    try:
        supported = Version(installed) >= Version(minimum)
    except InvalidVersion:
        supported = False
    if not supported:
        raise SecurityEnvironmentError(
            f"{package} {installed} is not supported; {package} >= {minimum} is required. "
            "Run python3.11 tools/bootstrap_environment.py --desktop, or install a newly rebuilt app.")
    return installed


def require_build_environment():
    return {"pip": require_version("pip", MIN_PIP),
            "certifi": require_version("certifi", MIN_CERTIFI),
            "uv": require_version("uv", MIN_UV, optional=True)}


def checked_ca_file():
    require_version("certifi", MIN_CERTIFI)
    import certifi
    path = Path(certifi.where())
    if not path.is_file():
        raise SecurityEnvironmentError("The application CA bundle is missing; rebuild or reinstall the app.")
    return path


def context_from_ca(cafile):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile=str(cafile))
    roots = context.get_ca_certs(binary_form=True)
    if not roots or any(hashlib.sha256(root).hexdigest() == REJECTED_ROOT_SHA256 for root in roots):
        raise SecurityEnvironmentError("The CA bundle is empty or still trusts emSign ECC Root CA - G3; rebuild the app.")
    context.set_alpn_protocols(["http/1.1"])
    return context


def _ca_certificates(path):
    """Read complete PEM blocks, preserving OpenSSL X509_AUX trust/reject."""
    data = Path(path).read_bytes()
    certificates = []
    for match in re.finditer(rb"-----BEGIN (CERTIFICATE|TRUSTED CERTIFICATE|X509 CERTIFICATE)-----\s+"
                             rb"(.*?)-----END \1-----", data, re.DOTALL):
        der = base64.b64decode(re.sub(rb"\s", b"", match[2]), validate=True)
        # A TRUSTED CERTIFICATE appends X509_AUX after the certificate DER.
        # Hash just the first DER SEQUENCE, without rewriting its AUX policy.
        if len(der) < 2 or der[0] != 0x30:
            raise SecurityEnvironmentError(f"Invalid CA certificate: {path}")
        length = der[1]
        offset = 2
        if length & 0x80:
            octets = length & 0x7f
            if not 1 <= octets <= 4 or len(der) < 2 + octets:
                raise SecurityEnvironmentError(f"Invalid CA certificate length: {path}")
            length = int.from_bytes(der[2:2 + octets], "big")
            offset += octets
        end = offset + length
        if end > len(der):
            raise SecurityEnvironmentError(f"Truncated CA certificate: {path}")
        certificates.append((hashlib.sha256(der[:end]).hexdigest(), match[0].decode("ascii") + "\n"))
    if not certificates:
        raise SecurityEnvironmentError(f"No PEM CA certificates: {path}")
    return certificates


def configured_context():
    """Keep default/custom CA trust, with the compromised root removed.

    Explicit CA settings are checked and rejected if they contain G3. System
    roots are copied into a new context without G3; OpenSSL's lazy capath is
    never attached to that context. The updated certifi bundle is the default
    public CA source when SSL_CERT_FILE does not override it.
    """
    approved = checked_ca_file()
    paths = ssl.get_default_verify_paths()
    explicit_file = "SSL_CERT_FILE" in os.environ
    explicit_dir = "SSL_CERT_DIR" in os.environ
    certificates = {}
    sources = []
    if paths.cafile:
        sources.append((Path(paths.cafile), explicit_file))
    elif explicit_file and os.environ["SSL_CERT_FILE"]:
        raise SecurityEnvironmentError("SSL_CERT_FILE is not a readable CA file.")
    directory_setting = os.environ.get("SSL_CERT_DIR", paths.openssl_capath)
    for directory in directory_setting.split(os.pathsep):
        if not directory:
            continue
        root = Path(directory)
        if not root.is_dir():
            if explicit_dir:
                raise SecurityEnvironmentError(f"SSL_CERT_DIR is not a readable CA directory: {directory}")
            continue
        # These are the only filenames OpenSSL's hashed CA directory uses.
        sources.extend((path, explicit_dir) for path in sorted(root.iterdir())
                       if re.fullmatch(r"[0-9a-fA-F]{8}\.[0-9]+", path.name))
    for path, explicit in sources:
        roots = _ca_certificates(path)
        if explicit and any(digest == REJECTED_ROOT_SHA256 for digest, _ in roots):
            raise SecurityEnvironmentError(f"Configured CA store still trusts emSign ECC Root CA - G3: {path}")
        for digest, block in roots:
            if digest != REJECTED_ROOT_SHA256:
                certificates.setdefault(digest, block)
    if not explicit_file:
        for digest, block in _ca_certificates(approved):
            if digest == REJECTED_ROOT_SHA256:
                raise SecurityEnvironmentError("The installed certifi bundle still contains emSign G3.")
            # A system CA's AUX rejection must take priority over a plain copy.
            certificates.setdefault(digest, block)
    if not certificates:
        raise SecurityEnvironmentError("The configured CA stores contain no usable CA certificates.")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # cafile uses PEM_read_bio_X509_AUX; converting to DER/cadata would erase
    # explicit distrust such as -addreject serverAuth.
    with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", suffix=".pem") as combined:
        combined.write("".join(certificates.values()))
        combined.flush()
        context.load_verify_locations(cafile=combined.name)
    context.set_alpn_protocols(["http/1.1"])
    return context


@lru_cache(maxsize=1)
def tls_context():
    """Build the verified trust policy once; never retry without verification."""
    return configured_context()


def security_report():
    context = tls_context()
    path = checked_ca_file()
    return {"certifi": metadata.version("certifi"), "openssl": ssl.OPENSSL_VERSION,
            "ca_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "trusted_roots": len(context.get_ca_certs()),
            "check_hostname": context.check_hostname,
            "verify_mode": context.verify_mode.name,
            "minimum_tls": context.minimum_version.name,
            "rejected_root_present": REJECTED_ROOT_SHA256 in
                {hashlib.sha256(root).hexdigest() for root in context.get_ca_certs(binary_form=True)}}
