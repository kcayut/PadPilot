"""Private local state: reject foreign/symlink endpoints before reading or writing."""
import json
import os
import stat
import tempfile
from pathlib import Path


class UnsafePathError(RuntimeError):
    pass


def latest_state_path(*paths: Path) -> Path:
    """Select the last atomic write, including fallback, without changing files."""
    existing = []
    for path in dict.fromkeys(paths):
        parents = [path.parent.parent, path.parent] if path.parent.name == 'runtime' else [path.parent]
        for parent in parents:
            try:
                info = parent.lstat()
            except FileNotFoundError:
                break
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise UnsafePathError(f'Refusing unsafe state directory: {parent}')
        else:
            private_file(path, harden=False)
            try:
                existing.append((path.stat().st_mtime_ns, path))
            except FileNotFoundError:
                pass
    return max(existing, key=lambda item: item[0])[1] if existing else paths[0]


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise UnsafePathError(f'Refusing unsafe state directory: {path}')
    path.chmod(0o700)


def private_file(path: Path, *, create=False, harden=True) -> None:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if create:
        flags |= os.O_CREAT
    try:
        fd = os.open(path, flags, 0o600)
    except FileNotFoundError:
        if create:
            raise
        return
    except OSError as error:
        raise UnsafePathError(f'Refusing unsafe state file: {path}') from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise UnsafePathError(f'Refusing unsafe state file: {path}')
        if harden:
            os.fchmod(fd, 0o600)
    finally:
        os.close(fd)


def state_directory(path: Path) -> None:
    # runtime is a child of the application-owned root, including /tmp fallback.
    if path.name == 'runtime':
        private_directory(path.parent)
    private_directory(path)


def state_file_exists(path: Path, *, socket_ok=False) -> bool:
    """Validate existing state before marker reads or cleanup; never follow links."""
    parents = [path.parent.parent, path.parent] if path.parent.name == 'runtime' else [path.parent]
    for parent in parents:
        if not (parent.exists() or parent.is_symlink()):
            return False
        private_directory(parent)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if socket_ok and stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid():
        return True
    private_file(path)
    return True


def remove_state_file(path: Path, *, socket_ok=False) -> None:
    if state_file_exists(path, socket_ok=socket_ok):
        path.unlink(missing_ok=True)


def read_private_json(path: Path):
    state_directory(path.parent)
    private_file(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        return json.load(stream)


def atomic_write(path: Path, content: bytes, *, private_parent=True) -> None:
    if private_parent:
        state_directory(path.parent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    private_file(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
