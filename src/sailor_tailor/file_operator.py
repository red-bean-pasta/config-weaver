import logging
import os
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import portalocker


logger = logging.getLogger(__name__)


def create(path: Path) -> None:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)


def save(content: bytes, path: Path, timeout: int = 10) -> None:
    """
    Overwrite instead of append
    :param content:
    :param path:
    :param timeout:
    :return:
    """
    parent_dir = path.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    lock_path = _get_unified_lock_path(path)
    with portalocker.Lock(lock_path, mode="a", timeout=timeout):
        try:
            temp_path = save_bytes_to_temp_file(parent_dir, content)
            replace(temp_path, path)
            temp_path = None
        # Let error propagate
        finally:
            clean_up(temp_path)


def replace(replacement: Path | str, replaced: Path | str) -> None:
    os.replace(replacement, replaced)
    _fsync_dir(replaced.parent)


def edit(editor_cmd: str, path: Path) -> None:
    parent_dir = path.parent
    parent_dir.mkdir(parents=True, exist_ok=True) # Which also checks directory permission

    if path.exists():
        if not os.access(path, os.W_OK):
            raise PermissionError(f"No write permission on file: {path}")
        backup_path = backup(path)
        logger.info(f"Backup created at {backup_path}")

    lock_path = _get_unified_lock_path(path)
    with portalocker.Lock(lock_path, mode="a"):
        tmp_path = backup(path, ".tmp")
        try:
            cmd = shlex.split(editor_cmd) + [str(tmp_path)]
            proc = subprocess.run(cmd)
            if proc.returncode != 0:
                raise RuntimeError(f"Editor `{editor_cmd}` exited with code {proc.returncode}")
            replace(tmp_path, path)
        finally:
            if tmp_path != path:
                clean_up(tmp_path)


def confident_edit(editor_cmd: str, path: Path) -> None:
    """
    No backup, no lock and no permission check
    :param editor_cmd:
    :param path:
    :return:
    """
    parent_dir = path.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    tmp_path = backup(path, ".tmp")
    try:
        cmd = shlex.split(editor_cmd) + [str(tmp_path)]
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            raise RuntimeError(f"Editor `{editor_cmd}` exited with code {proc.returncode}")
        replace(tmp_path, path)
    finally:
        if tmp_path != path:
            clean_up(tmp_path)


def save_to_temp_file(parent_dir: Path | str, content: str, mode: int = 0o600) -> Path:
    return save_bytes_to_temp_file(parent_dir, content.encode(), mode)


def save_bytes_to_temp_file(parent_dir: Path | str, content: bytes, mode: int = 0o600) -> Path:
    fd, path = tempfile.mkstemp(
        suffix=".tmp",
        dir=parent_dir
    )
    os.fchmod(fd, mode)

    with os.fdopen(fd, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

    return Path(path)


def _fsync_dir(dir_path: Path) -> None:
    # Sync renaming, required by some filesystems in case of sudden crash like power loss
    dir_descriptor = os.open(dir_path, os.O_DIRECTORY)
    try:
        os.fsync(dir_descriptor)
    except NotImplementedError as e:
        logger.debug(f"{dir_path}: Failed to fsync, probably not implemented by OS: {e}")
    finally:
        os.close(dir_descriptor)


def clean_up(*files: Path | str) -> None:
    for file in files:
        if file is None:
            continue
        path = Path(file)
        if not path.exists():
            continue
        try:
            os.unlink(path)
        except (FileNotFoundError, OSError) as e:
            logger.info(f"Error occurred when removing temp file: {e}")


def _get_unified_lock_path(target: Path | str) -> Path:
    return Path(target).with_name(target.name + ".lock")


def backup(target: Path, suffix: str = ".bak") -> Path | None:
    if not target.exists():
        return None
    bak = target.with_name(f"{target.name}.{generate_timestamp()}{suffix}")
    shutil.copy2(target, bak)
    return bak


def generate_timestamp():
    return datetime.now().strftime('%Y%m%d_%H%M%S')
