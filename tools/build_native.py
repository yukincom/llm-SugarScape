"""Build the required, dependency-free Rust core using the pinned toolchain."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build():
    cargo = os.environ.get('CARGO', 'cargo')
    rustc = os.environ.get('RUSTC', 'rustc')
    try:
        version = subprocess.run([rustc, '--version'], cwd=ROOT / 'rust-core',
                                 capture_output=True, text=True, check=True).stdout.strip()
    except FileNotFoundError as error:
        raise RuntimeError('Install Rust with https://rustup.rs, then rustup toolchain install 1.99.1 --profile minimal') from error
    if version.split()[1] != '1.99.1':
        raise RuntimeError('Install the pinned Rust 1.99.1 toolchain before building')
    environment = os.environ.copy()
    environment['CARGO_TARGET_DIR'] = str(ROOT / 'rust-core/target')
    subprocess.run([cargo, 'build', '--manifest-path', str(ROOT / 'rust-core/Cargo.toml'),
                    '--release', '--locked', '--offline'], env=environment, cwd=ROOT / 'rust-core', check=True)
    name = ('libsugarscape_core.dylib' if sys.platform == 'darwin' else
            'sugarscape_core.dll' if sys.platform == 'win32' else 'libsugarscape_core.so')
    native = ROOT / 'native'
    native.mkdir(exist_ok=True)
    path = native / name
    shutil.copyfile(ROOT / 'rust-core/target/release' / name, path)
    if sys.platform == 'darwin':
        subprocess.run(['/usr/bin/install_name_tool', '-id', '@rpath/' + name, str(path)], check=True)
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--identifier',
                        'com.yukincom.sugarscape.core', str(path)], check=True)
    sources = ('rust-core/Cargo.toml', 'rust-core/Cargo.lock',
               'rust-core/rust-toolchain.toml', 'rust-core/src/lib.rs')
    report = {'abi': 1, 'library': name, 'rustc': version,
              'binary_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}}
    (native / 'build.json').write_text(json.dumps(report, indent=2) + '\n')
    return path


if __name__ == '__main__':
    print(build())
