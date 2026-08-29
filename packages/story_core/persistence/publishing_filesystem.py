from __future__ import annotations

import ctypes
import logging
import os
import stat
import tempfile
import uuid
from ctypes import wintypes
from pathlib import Path


if os.name == "nt":
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _KERNEL32.CreateFileW.restype = wintypes.HANDLE
    _KERNEL32.GetFileAttributesW.argtypes = (wintypes.LPCWSTR,)
    _KERNEL32.GetFileAttributesW.restype = wintypes.DWORD
    _KERNEL32.GetFinalPathNameByHandleW.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    _KERNEL32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.GetFileSizeEx.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong))
    _KERNEL32.GetFileSizeEx.restype = wintypes.BOOL
    _KERNEL32.ReadFile.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    _KERNEL32.ReadFile.restype = wintypes.BOOL
else:
    _KERNEL32 = None


def _is_reparse_point(path: Path) -> bool:
    try:
        details = os.lstat(path)
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(details, "st_file_attributes", 0) & 0x400)

class PinnedPublishingFilesystem:
    """Pin publishing directories for one transaction.

    POSIX operations use the pinned directory descriptors directly (openat /
    renameat semantics).  Windows keeps every ancestor open without
    ``FILE_SHARE_DELETE``; the resulting directory handles make an ancestor
    rename/delete fail until the transaction has cleaned up.
    """

    _REPARSE_POINT = 0x400

    def __init__(self, root: Path):
        self.root = Path(root).absolute()
        self._root_fd: int | None = None
        self._dir_fds: dict[tuple[str, ...], int] = {}
        self._posix_root_path: str | None = None
        self._windows_handles: list[int] = []
        self._windows_final_root: str | None = None

    def __enter__(self) -> "PinnedPublishingFilesystem":
        try:
            if os.name == "nt":
                self._pin_windows_directory(self.root)
            else:
                if not os.path.exists("/proc/self/fd"):
                    raise ValueError("publishing_asset_write_failed")
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
                self._root_fd = os.open(self.root, flags)
                if not stat.S_ISDIR(os.fstat(self._root_fd).st_mode):
                    raise ValueError("publishing_asset_write_failed")
                self._posix_root_path = os.path.realpath(os.readlink(f"/proc/self/fd/{self._root_fd}"))
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_exc_info: object) -> None:
        logger = logging.getLogger(__name__)
        for descriptor in reversed(list(self._dir_fds.values())):
            try:
                os.close(descriptor)
            except OSError:
                logger.warning("publishing directory descriptor cleanup deferred")
        self._dir_fds.clear()
        if self._root_fd is not None:
            try:
                os.close(self._root_fd)
            except OSError:
                logger.warning("publishing root descriptor cleanup deferred")
            self._root_fd = None
        if os.name == "nt":
            for handle in reversed(self._windows_handles):
                if _KERNEL32 is not None and not _KERNEL32.CloseHandle(wintypes.HANDLE(handle)):
                    logger.warning("publishing directory handle cleanup deferred")
            self._windows_handles.clear()

    def _relative(self, path: Path) -> tuple[str, ...]:
        try:
            return Path(path).absolute().relative_to(self.root).parts
        except ValueError as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    @staticmethod
    def _is_asset_target(parts: tuple[str, ...]) -> bool:
        return len(parts) >= 3 and parts[0] == ".webnovel" and parts[1] == "assets"

    def _parent_fd(self, path: Path, *, create: bool) -> tuple[int, str]:
        parts = self._relative(path)
        if not parts:
            raise ValueError("publishing_asset_write_failed")
        parent_parts = parts[:-1]
        current_fd = self._root_fd
        if current_fd is None:  # pragma: no cover - callers are always in the transaction context
            raise ValueError("publishing_asset_write_failed")
        for index, part in enumerate(parent_parts):
            key = parent_parts[: index + 1]
            pinned = self._dir_fds.get(key)
            if pinned is not None:
                current_fd = pinned
                continue
            try:
                details = os.lstat(part, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise ValueError("publishing_asset_write_failed")
                os.mkdir(part, dir_fd=current_fd)
                details = os.lstat(part, dir_fd=current_fd)
            if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
                raise ValueError("publishing_asset_write_failed")
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(part, flags, dir_fd=current_fd)
            try:
                if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    raise ValueError("publishing_asset_write_failed")
                self._assert_posix_descriptor_contained(descriptor)
            except Exception:
                os.close(descriptor)
                raise
            self._dir_fds[key] = descriptor
            current_fd = descriptor
        self._assert_posix_descriptor_contained(current_fd)
        return current_fd, parts[-1]

    def _assert_posix_descriptor_contained(self, descriptor: int) -> None:
        """Detect a rename of a pinned directory out of the trusted root on Linux."""
        if self._posix_root_path is None:
            return  # Platforms without procfs still use descriptor-relative syscalls.
        current = os.path.realpath(os.readlink(f"/proc/self/fd/{descriptor}"))
        try:
            Path(current).relative_to(self._posix_root_path)
        except ValueError as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    @staticmethod
    def _windows_final_path(handle: int) -> str:
        if _KERNEL32 is None:  # pragma: no cover - Windows only
            raise OSError("kernel32 unavailable")
        needed = _KERNEL32.GetFinalPathNameByHandleW(wintypes.HANDLE(handle), None, 0, 0)
        if not needed:
            raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW")
        buffer = ctypes.create_unicode_buffer(needed + 1)
        if not _KERNEL32.GetFinalPathNameByHandleW(wintypes.HANDLE(handle), buffer, len(buffer), 0):
            raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW")
        return os.path.normcase(os.path.normpath(buffer.value.removeprefix("\\\\?\\")))

    def _pin_windows_directory(self, path: Path) -> None:
        if _KERNEL32 is None:  # pragma: no cover - Windows only
            raise OSError("kernel32 unavailable")
        flags = 0x02000000 | 0x00200000  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        handle = _KERNEL32.CreateFileW(
            str(path), 0x80000000, 0x00000001 | 0x00000002, None, 3, flags, None
        )
        handle_value = wintypes.HANDLE(handle).value
        invalid_handle = wintypes.HANDLE(-1).value
        if handle_value is None or handle_value == invalid_handle:
            raise OSError(ctypes.get_last_error(), "CreateFileW")
        try:
            attrs = _KERNEL32.GetFileAttributesW(str(path))
            if attrs == 0xFFFFFFFF or attrs & self._REPARSE_POINT:
                raise ValueError("publishing_asset_write_failed")
            final = self._windows_final_path(handle_value)
            if self._windows_final_root is None:
                self._windows_final_root = final
            elif os.path.commonpath([self._windows_final_root, final]) != self._windows_final_root:
                raise ValueError("publishing_asset_write_failed")
        except Exception:
            _KERNEL32.CloseHandle(wintypes.HANDLE(handle_value))
            raise
        self._windows_handles.append(handle_value)

    def _windows_assert_target(self, path: Path, *, create: bool) -> None:
        parts = self._relative(path)
        current = self.root
        for part in parts[:-1]:
            current = current / part
            if not os.path.lexists(current):
                if not create:
                    raise ValueError("publishing_asset_write_failed")
                current.mkdir()
            self._pin_windows_directory(current)
        if os.path.lexists(path) and _is_reparse_point(path):
            raise ValueError("publishing_asset_write_failed")

    def assert_target(self, path: Path) -> None:
        parts = self._relative(path)
        create = self._is_asset_target(parts)
        if os.name == "nt":
            self._windows_assert_target(path, create=create)
            return
        parent_fd, name = self._parent_fd(path, create=create)
        try:
            details = os.lstat(name, dir_fd=parent_fd)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(details.st_mode):
            raise ValueError("publishing_asset_write_failed")

    def exists(self, path: Path) -> bool:
        self.assert_target(path)
        if os.name == "nt":
            return os.path.lexists(path)
        parent_fd, name = self._parent_fd(path, create=False)
        try:
            os.lstat(name, dir_fd=parent_fd)
            return True
        except FileNotFoundError:
            return False

    def read_bytes(self, path: Path) -> bytes:
        self.assert_target(path)
        if os.name == "nt":
            return path.read_bytes()
        parent_fd, name = self._parent_fd(path, create=False)
        descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                return handle.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def read_bounded_bytes(self, path: Path, max_bytes: int) -> bytes:
        """Open once through pinned ancestors and read a regular file with a hard cap."""
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("publishing_asset_read_failed")
        self.assert_target(path)
        if os.name == "nt":
            if _KERNEL32 is None:  # pragma: no cover - Windows only
                raise ValueError("publishing_asset_read_failed")
            flags = 0x00200000  # OPEN_REPARSE_POINT
            handle = _KERNEL32.CreateFileW(str(path), 0x80000000, 0x00000001 | 0x00000002, None, 3, flags, None)
            handle_value = wintypes.HANDLE(handle).value
            invalid_handle = wintypes.HANDLE(-1).value
            if handle_value is None or handle_value == invalid_handle:
                if ctypes.get_last_error() in {2, 3}:
                    raise FileNotFoundError(path)
                raise ValueError("publishing_asset_read_failed")
            try:
                attrs = _KERNEL32.GetFileAttributesW(str(path))
                if attrs == 0xFFFFFFFF or attrs & self._REPARSE_POINT:
                    raise ValueError("publishing_asset_read_failed")
                final = self._windows_final_path(handle_value)
                if self._windows_final_root is None or os.path.commonpath([self._windows_final_root, final]) != self._windows_final_root:
                    raise ValueError("publishing_asset_read_failed")
                size_value = ctypes.c_longlong()
                if not _KERNEL32.GetFileSizeEx(wintypes.HANDLE(handle_value), ctypes.byref(size_value)):
                    raise ValueError("publishing_asset_read_failed")
                size = size_value.value
                if size <= 0 or size > max_bytes:
                    raise ValueError("publishing_asset_read_failed")
                chunks: list[bytes] = []
                remaining = max_bytes + 1
                while remaining:
                    buffer = ctypes.create_string_buffer(min(64 * 1024, remaining))
                    read = wintypes.DWORD()
                    if not _KERNEL32.ReadFile(wintypes.HANDLE(handle_value), buffer, len(buffer), ctypes.byref(read), None):
                        raise ValueError("publishing_asset_read_failed")
                    if not read.value:
                        break
                    chunks.append(buffer.raw[: read.value])
                    remaining -= read.value
                content = b"".join(chunks)
            finally:
                _KERNEL32.CloseHandle(wintypes.HANDLE(handle_value))
            if not content or len(content) > max_bytes:
                raise ValueError("publishing_asset_read_failed")
            return content
        parent_fd, name = self._parent_fd(path, create=False)
        descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_size <= 0 or details.st_size > max_bytes:
                raise ValueError("publishing_asset_read_failed")
            chunks: list[bytes] = []
            remaining = max_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            if not content or len(content) > max_bytes:
                raise ValueError("publishing_asset_read_failed")
            return content
        finally:
            os.close(descriptor)

    def prepare(self, path: Path, content: bytes, *, suffix: str) -> Path:
        self.assert_target(path)
        if os.name == "nt":
            return self._prepare_windows(path, content, suffix=suffix)
        parent_fd, target_name = self._parent_fd(path, create=True)
        try:
            existing_details = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing_mode = None
        else:
            if stat.S_ISLNK(existing_details.st_mode):
                raise ValueError("publishing_asset_write_failed")
            existing_mode = stat.S_IMODE(existing_details.st_mode)
        name = f".{path.name}.{uuid.uuid4().hex}{suffix}"
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        temp_path = path.parent / name
        try:
            if existing_mode is not None:
                os.fchmod(descriptor, existing_mode)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.unlink(name, dir_fd=parent_fd)
            except OSError:
                logging.getLogger(__name__).warning("publishing temp cleanup deferred: %s", temp_path)
            raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        return temp_path

    def _prepare_windows(self, path: Path, content: bytes, *, suffix: str) -> Path:
        fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=suffix)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    logging.getLogger(__name__).warning("publishing temp descriptor cleanup deferred: %s", temp_path)
                fd = None
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning("publishing temp cleanup deferred: %s", temp_path)
            raise
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    logging.getLogger(__name__).warning("publishing temp descriptor cleanup deferred: %s", temp_path)
        return temp_path

    def replace(self, source: Path, target: Path) -> None:
        self.assert_target(source)
        self.assert_target(target)
        if os.name == "nt":
            os.replace(source, target)
            return
        source_fd, source_name = self._parent_fd(source, create=False)
        target_fd, target_name = self._parent_fd(target, create=False)
        os.replace(source_name, target_name, src_dir_fd=source_fd, dst_dir_fd=target_fd)

    def unlink(self, path: Path) -> None:
        self.assert_target(path)
        if os.name == "nt":
            path.unlink(missing_ok=True)
            return
        parent_fd, name = self._parent_fd(path, create=False)
        try:
            os.unlink(name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass

    def fsync_parent(self, path: Path) -> None:
        if os.name == "nt":
            return
        try:
            descriptor, _ = self._parent_fd(path, create=False)
            os.fsync(descriptor)
        except OSError:
            pass
