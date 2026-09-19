"""Read a bounded native process identity, without parsing ps or process argv.

This is not a descendant-empty, sandbox, code-signature or file-custody proof.
The approved owner and executable must come from trusted deployment metadata.
"""
import ctypes
import os
import sys


class ProcessIdentityError(ValueError):
    pass


class _BsdInfo(ctypes.Structure):
    # Public Darwin sys/proc_info.h: PROC_PIDTBSDINFO, MAXCOMLEN=16.
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid',
        'ruid', 'rgid', 'svuid', 'svgid', 'reserved')]
    _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in (
        'nfiles', 'pgid', 'jobc', 'tdev', 'tpgid')]
    _fields_ += [('nice', ctypes.c_int32), ('start_sec', ctypes.c_uint64),
                ('start_usec', ctypes.c_uint64)]


def _library():
    if sys.platform != 'darwin':
        raise ProcessIdentityError('macos-process-platform-required')
    if ctypes.sizeof(_BsdInfo) != 136:
        raise ProcessIdentityError('macos-process-abi-unavailable')
    try:
        lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                    ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
        lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        lib.proc_pidpath.restype = ctypes.c_int
    except (OSError, AttributeError):
        raise ProcessIdentityError('macos-process-api-unavailable') from None
    return lib


def _record(lib, pid):
    value = _BsdInfo()
    size = ctypes.sizeof(value)
    if lib.proc_pidinfo(pid, 3, 0, ctypes.byref(value), size) != size:
        raise ProcessIdentityError('gateway-process-unavailable')
    if (value.pid != pid or value.status in (0, 5) or value.start_sec == 0
            or value.start_usec >= 1000000):
        raise ProcessIdentityError('gateway-process-mismatch')
    return (value.pid, value.start_sec, value.start_usec, value.uid, value.gid,
            value.ruid, value.rgid, value.svuid, value.svgid)


def process_identity(pid, *, uid, gid, executable):
    """Snapshot pid/creation/credentials/path and detect changes while reading.

    Only a live unprivileged identity is accepted. The surrounding service
    adapter must independently recheck launchd's PID and deployment custody.
    No secrets, arguments or environment values are read or returned.
    """
    if (type(pid) is not int or not 0 < pid <= 2147483647
            or type(uid) is not int or not 0 < uid < 4294967295
            or type(gid) is not int or not 0 <= gid < 4294967295
            or not isinstance(executable, str) or not executable.startswith('/')
            or any(c in executable for c in '\0\n\r')
            or any(p in ('', '.', '..') for p in executable.split('/')[1:])):
        raise ProcessIdentityError('gateway-process-specification-invalid')
    lib = _library()
    before = _record(lib, pid)
    buffer = ctypes.create_string_buffer(4096)  # PROC_PIDPATHINFO_MAXSIZE
    length = lib.proc_pidpath(pid, buffer, len(buffer))
    if not 0 < length < len(buffer) or buffer.raw[length] != 0:
        raise ProcessIdentityError('gateway-process-path-unavailable')
    raw = buffer.raw[:length]
    if b'\0' in raw or os.fsdecode(raw) != executable:
        raise ProcessIdentityError('gateway-process-executable-mismatch')
    after = _record(lib, pid)
    if before != after:
        raise ProcessIdentityError('gateway-process-changed')
    if before[3:] != (uid, gid, uid, gid, uid, gid):
        raise ProcessIdentityError('gateway-process-owner-mismatch')
    return (*before, executable)
