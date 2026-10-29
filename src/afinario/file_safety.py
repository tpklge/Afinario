"""Small filesystem primitives: exclusive creation and no replacement of foreign files."""

import ctypes
import os
import shutil
import stat
import sys
from contextlib import contextmanager
from pathlib import Path


def regular_file(path: Path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or path.is_symlink()
        or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    ):
        raise OSError("Links e arquivos especiais não podem ser alterados.")
    if info.st_nlink != 1 or not info.st_ino:
        raise OSError("Arquivo com vínculos físicos ou identidade indisponível.")
    return info


def directory_identity(path: Path):
    # Refuse a symlink/junction anywhere in the absolute directory chain.
    for part in (path, *path.parents):
        info = part.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or part.is_symlink()
            or (
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            )
        ):
            raise OSError("A pasta contém um link ou ponto de redirecionamento.")
    info = path.stat()
    return (info.st_dev, info.st_ino)


def identity(path: Path):
    info = regular_file(path)
    return (info.st_dev, info.st_ino)


def sync_file(path: Path):
    # Windows FlushFileBuffers requires a handle with write access.
    with path.open("r+b" if os.name == "nt" else "rb") as stream:
        os.fsync(stream.fileno())
        if sys.platform == "darwin":
            import fcntl

            fcntl.fcntl(stream.fileno(), fcntl.F_FULLFSYNC)


def sync_directory(path: Path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def move_exclusive(source: Path, destination: Path):
    """Both paths are in the same directory. Never use POSIX replacing rename."""
    if source.parent != destination.parent:
        raise OSError("A operação precisa permanecer na mesma pasta.")
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        function = kernel.MoveFileExW
        function.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        function.restype = ctypes.c_int
        # WRITE_THROUGH, deliberately without REPLACE_EXISTING or COPY_ALLOWED.
        if not function(str(source), str(destination), 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    elif sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        function = libc.renamex_np
        function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        function.restype = ctypes.c_int
        if function(os.fsencode(source), os.fsencode(destination), 0x00000004):
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
    else:
        # link() creates exclusively; unlink() occurs only after that succeeds.
        os.link(source, destination, follow_symlinks=False)
        source.unlink()
    sync_directory(source.parent)


def copy_exclusive(source: Path, destination: Path):
    regular_file(source)
    if os.name == "nt":
        # Windows 11 CopyFile also preserves security resource properties.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        function = kernel.CopyFileW
        function.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int)
        function.restype = ctypes.c_int
        if not function(str(source), str(destination), 1):
            raise ctypes.WinError(ctypes.get_last_error())
        shutil.copystat(source, destination, follow_symlinks=False)
    elif sys.platform == "darwin":
        # copyfile.h: ALL includes data, stat, ACLs and extended attributes.
        libc = ctypes.CDLL(None, use_errno=True)
        function = libc.copyfile
        function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_uint)
        function.restype = ctypes.c_int
        flags = 0xF | (1 << 17) | (1 << 18) | (1 << 19)
        if function(os.fsencode(source), os.fsencode(destination), None, flags):
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
    else:
        with source.open("rb") as original, destination.open("xb") as target:
            shutil.copyfileobj(original, target, 1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        shutil.copystat(source, destination, follow_symlinks=False)
    sync_file(destination)
    sync_directory(destination.parent)


@contextmanager
def operation_lock(path: Path):
    """An OS lock is released by process death; no stale PID lock to guess about."""
    with path.open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            if not stream.read(1):
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise OSError("Outra janela está aplicando ou recuperando alterações.") from None
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise OSError("Outra janela está aplicando ou recuperando alterações.") from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
