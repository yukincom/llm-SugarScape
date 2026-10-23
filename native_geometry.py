"""Required Rust geometry core. Python owns text, state and random generators."""

import ctypes as C
import hashlib
import json
import operator
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
LIBRARY_NAME = ('libsugarscape_core.dylib' if sys.platform == 'darwin' else
                'sugarscape_core.dll' if sys.platform == 'win32' else 'libsugarscape_core.so')
LIBRARY_PATH = ROOT / 'native' / LIBRARY_NAME
SOURCE_FILES = ('rust-core/Cargo.toml', 'rust-core/Cargo.lock',
                'rust-core/rust-toolchain.toml', 'rust-core/src/lib.rs')


def _load():
    try:
        manifest = json.loads((ROOT / 'native/build.json').read_text())
        if manifest['abi'] != 1 or manifest['library'] != LIBRARY_NAME:
            raise ValueError('Native ABI/platform mismatch')
        for name in SOURCE_FILES:
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != manifest['source_sha256'][name]:
                raise ValueError(f'Native source changed: {name}')
        if hashlib.sha256(LIBRARY_PATH.read_bytes()).hexdigest() != manifest['binary_sha256']:
            raise ValueError('Native binary checksum mismatch')
        library = C.CDLL(str(LIBRARY_PATH))
        library.ss_abi_version.argtypes = []
        library.ss_abi_version.restype = C.c_uint32
        if library.ss_abi_version() != 1:
            raise ValueError('Native ABI mismatch')
        return library
    except (OSError, ValueError, KeyError, AttributeError) as error:
        raise RuntimeError('Rust geometry core is missing or stale. Run python tools/build_native.py '
                           'after installing Rust 1.99.1, or reinstall the current Mac app.') from error


_LIB = _load()
_I64 = C.c_int64
_PTR = C.POINTER(_I64)
_SIZE = C.c_size_t
_LIB.ss_relative.argtypes = [_I64] * 5 + [_PTR, _SIZE]
_LIB.ss_in_range.argtypes = [_I64] * 6
_LIB.ss_in_range.restype = C.c_int32
_LIB.ss_visible.argtypes = [_I64] * 4 + [_PTR, _SIZE, _PTR, _SIZE, C.POINTER(_SIZE)]
_LIB.ss_cardinal.argtypes = [_I64] * 5 + [C.c_uint32, _PTR, _SIZE, C.POINTER(_SIZE)]
_LIB.ss_absolute.argtypes = [_I64] * 5 + [_PTR, _SIZE]
for _name in ('ss_relative', 'ss_visible', 'ss_cardinal', 'ss_absolute'):
    getattr(_LIB, _name).restype = C.c_int32


def _integer(value):
    value = operator.index(value)
    if not -(1 << 63) <= value < (1 << 63):
        raise OverflowError('Geometry coordinates must fit signed 64-bit integers')
    return value


def _point(value):
    if len(value) != 2:
        raise ValueError('Geometry positions must have two coordinates')
    return _integer(value[0]), _integer(value[1])


def _check(status):
    if status:
        raise ValueError('Invalid native geometry dimensions or buffers')


def _radius(radius, size):
    # Larger radii all mean the entire torus; negative radii see no cells.
    return min(max(operator.index(radius), -1), size // 2)


def relative(origin, target, size):
    output = (_I64 * 2)()
    _check(_LIB.ss_relative(*_point(origin), *_point(target), _integer(size), output, 2))
    return tuple(output)


def visible_offsets(origin, targets, size, radius):
    """Return (input index, dx, dy) only for visible targets, in input order."""
    points = [_point(point) for point in targets]
    array = (_I64 * (2 * len(points)))(*(value for point in points for value in point))
    output = (_I64 * (3 * len(points)))()
    written = _SIZE()
    size = _integer(size)
    _check(_LIB.ss_visible(*_point(origin), size, _radius(radius, size),
                          array, len(array), output, len(output), C.byref(written)))
    return [(output[index * 3], output[index * 3 + 1], output[index * 3 + 2])
            for index in range(written.value)]


def in_range(origin, target, size, radius):
    size = _integer(size)
    result = _LIB.ss_in_range(*_point(origin), *_point(target), size, _radius(radius, size))
    if result < 0:
        raise ValueError('Invalid native geometry grid size')
    return bool(result)


def cardinal_destinations(position, size, *, toward_delta=None):
    # Only direction signs are relevant; preserve arbitrary-sized parsed ints.
    toward = (0, 0) if toward_delta is None else tuple((n > 0) - (n < 0) for n in toward_delta)
    output = (_I64 * 16)()
    written = _SIZE()
    _check(_LIB.ss_cardinal(*_point(position), _integer(size), *toward, toward_delta is not None,
                           output, 16, C.byref(written)))
    return [{'position': [output[i * 4], output[i * 4 + 1]],
             'delta': [output[i * 4 + 2], output[i * 4 + 3]]} for i in range(written.value)]


def absolute_move(target, position, size):
    output = (_I64 * 2)()
    status = _LIB.ss_absolute(*_point(position), *_point(target), _integer(size), output, 2)
    if status == 2:
        return None
    _check(status)
    return tuple(output)


def build_report():
    return json.loads((ROOT / 'native/build.json').read_text())
