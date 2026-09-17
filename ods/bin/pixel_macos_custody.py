"""Fail-closed file custody for the forthcoming macOS service adapter.

This verifies deployment files, not a running process or its isolation. Callers
must still verify the loaded launchd job and qualify the host access controls.
"""
import ctypes
import errno
import hashlib
import os
import plistlib
import re
import stat
import sys
from xml.parsers.expat import ExpatError


class CustodyError(ValueError):
    pass


def verify_loaded_launchd_definition(raw, target, filename, expected):
    """Compare a launchctl print snapshot with a trusted deployment definition.

    This supplements on-disk custody: kickstart does not reload a changed plist.
    It proves neither process identity nor absence of surviving descendants.
    Unknown launchctl formatting fails closed; never parse untrusted output as
    a deployment specification.
    """
    def fail():
        raise CustodyError('launchd-loaded-definition-mismatch')

    if (not isinstance(raw, str) or not isinstance(expected, dict)
            or not isinstance(target, str) or not re.fullmatch(
                r'(?:system|gui/[0-9]+)/[A-Za-z0-9][A-Za-z0-9.-]{0,127}', target)):
        fail()
    lines = raw.splitlines()
    if not lines or lines[0] != target + ' = {' or lines[-1] != '}':
        fail()

    def scalar(name):
        values = re.findall(r'^\t' + re.escape(name) + r' = ([^\n]*)$', raw, re.M)
        if len(values) != 1:
            fail()
        return values[0]

    def block(name, *, optional=False):
        start = '\t' + name + ' = {'
        positions = [i for i, line in enumerate(lines) if line == start]
        if not positions and optional:
            return []
        if len(positions) != 1:
            fail()
        values = []
        for line in lines[positions[0] + 1:]:
            if line == '\t}':
                return values
            if not line.startswith('\t\t') or line.startswith('\t\t\t'):
                fail()
            values.append(line[2:])
        fail()

    args = expected.get('ProgramArguments')
    environment = expected.get('EnvironmentVariables')
    if (expected.get('Label') != target.split('/')[-1]
            or not isinstance(args, list) or not args
            or any(not isinstance(a, str) or not a or any(c in a for c in '\n\r\t') for a in args)
            or not isinstance(environment, dict)
            or any(not isinstance(k, str) or not isinstance(v, str)
                   or any(c in k + v for c in '\n\r\t') for k, v in environment.items())):
        fail()
    for key, value in {'path': os.fspath(filename),
                       'program': expected.get('Program', args[0]),
                       'working directory': expected.get('WorkingDirectory'),
                       'stdout path': expected.get('StandardOutPath'),
                       'stderr path': expected.get('StandardErrorPath')}.items():
        if not isinstance(value, str) or scalar(key) != value:
            fail()
    if block('arguments') != args or block('inherited environment', optional=True):
        fail()
    loaded = {}
    for line in block('environment'):
        key, separator, value = line.partition(' => ')
        if not separator or not key or key in loaded:
            fail()
        loaded[key] = value
    # launchd injects these independently of EnvironmentVariables.
    if loaded.pop('XPC_SERVICE_NAME', None) != expected['Label']:
        fail()
    rate = loaded.pop('OSLogRateLimit', None)
    if rate is not None and not rate.isdecimal():
        fail()
    if loaded != environment:
        fail()


def _require_no_acl(fd):
    if sys.platform != 'darwin':
        raise CustodyError('macos-custody-platform-required')
    libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    libc.acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
    libc.acl_get_fd_np.restype = ctypes.c_void_p
    libc.acl_valid.argtypes = [ctypes.c_void_p]
    libc.acl_valid.restype = ctypes.c_int
    libc.acl_get_entry.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                   ctypes.POINTER(ctypes.c_void_p)]
    libc.acl_get_entry.restype = ctypes.c_int
    libc.acl_free.argtypes = [ctypes.c_void_p]
    libc.acl_free.restype = ctypes.c_int
    ctypes.set_errno(0)
    acl = libc.acl_get_fd_np(fd, 0x100)  # ACL_TYPE_EXTENDED from sys/acl.h.
    if not acl:
        # Apple's filesec_get_property reports absent FILESEC_ACL as ENOENT.
        # This is a descriptor query, not a missing pathname. Other errors fail.
        if ctypes.get_errno() == errno.ENOENT:
            os.fstat(fd)
            return
        raise CustodyError('macos-custody-acl-unavailable')
    try:
        if libc.acl_valid(acl) != 0:
            raise CustodyError('macos-custody-acl-invalid')
        entry = ctypes.c_void_p()
        ctypes.set_errno(0)
        result = libc.acl_get_entry(acl, 0, ctypes.byref(entry))
        # Darwin returns 0 for an entry, -1/EINVAL for an empty valid ACL.
        # Reject even restrictive ACLs: deployment never needs custom entries.
        if result != -1 or ctypes.get_errno() != errno.EINVAL:
            raise CustodyError('macos-custody-acl-present')
    finally:
        libc.acl_free(acl)


def _verify_fd(fd, *, directory):
    info = os.fstat(fd)
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
            or not directory and info.st_nlink != 1):
        raise CustodyError('macos-root-custody-required')
    _require_no_acl(fd)
    return info


def protected_bytes(filename, *, limit=1024 * 1024):
    """Read a bounded root-owned file through individually verified dirfds.

    No resolve(): that would hide symlinks before checking them. Walking from
    an open root prevents replacement of an unchecked intermediate directory.
    """
    value = os.fspath(filename)
    if (not isinstance(value, str) or not value.startswith('/') or '\0' in value
            or any(part in ('', '.', '..') for part in value.split('/')[1:])
            or type(limit) is not int or limit < 1):
        raise CustodyError('macos-custody-path-invalid')
    parts = value.split('/')[1:]
    opened = []
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        parent = os.open('/', flags | os.O_DIRECTORY)
        opened.append(parent)
        _verify_fd(parent, directory=True)
        for part in parts[:-1]:
            parent = os.open(part, flags | os.O_DIRECTORY, dir_fd=parent)
            opened.append(parent)
            _verify_fd(parent, directory=True)
        fd = os.open(parts[-1], flags, dir_fd=parent)
        opened.append(fd)
        before = _verify_fd(fd, directory=False)
        if before.st_size > limit:
            raise CustodyError('macos-custody-file-too-large')
        chunks, length = [], 0
        while length <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - length))
            if not chunk:
                break
            chunks.append(chunk)
            length += len(chunk)
        after = _verify_fd(fd, directory=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after):
            raise CustodyError('macos-custody-file-changed')
        if length > limit:
            raise CustodyError('macos-custody-file-too-large')
        return b''.join(chunks)
    except OSError:
        raise CustodyError('macos-custody-file-unavailable') from None
    finally:
        for fd in reversed(opened):
            os.close(fd)


def launchd_document_binding(filename, expected):
    """Pin a complete approved plist; never infer approval from its label alone.

    expected must come from the trusted deployment specification, not the
    candidate file. This does not prove executable/plugin/config file custody.
    """
    if not isinstance(expected, dict) or not expected:
        raise CustodyError('launchd-specification-required')
    body = protected_bytes(filename)
    try:
        document = plistlib.loads(body)
        # Canonical bytes also distinguish plist booleans from integer values.
        actual = plistlib.dumps(document, fmt=plistlib.FMT_BINARY, sort_keys=True)
        wanted = plistlib.dumps(expected, fmt=plistlib.FMT_BINARY, sort_keys=True)
    except (ValueError, TypeError, OverflowError, plistlib.InvalidFileException, ExpatError):
        raise CustodyError('launchd-document-invalid') from None
    if actual != wanted:
        raise CustodyError('launchd-document-changed')
    # Only installer-generated encodings are accepted, avoiding duplicate XML
    # keys or other parser ambiguities between plistlib and launchd.
    if body not in (wanted, plistlib.dumps(expected, sort_keys=True)):
        raise CustodyError('launchd-document-noncanonical')
    return {'schemaVersion': 1, 'path': os.fspath(filename),
            'sha256': hashlib.sha256(body).hexdigest()}
