"""
Filesystem helpers for CivitScraper.

Atomic writes: content goes to a unique temporary file in the target directory and
is then moved over the target in one step, so an interrupted run (Ctrl-C, network
timeout, crash) never leaves a truncated preview, sidecar or HTML page that later
runs would mistake for a complete file. A hard kill can still leave a hidden
``.<name>.<random>.part`` file behind; it is never picked up as a preview or sidecar.
"""

import errno
import logging
import os
import stat
import tempfile
import time
from typing import Iterable, Union

logger = logging.getLogger(__name__)


def _read_umask() -> int:
    """Read the process umask (only possible by setting it, so restore immediately)."""
    mask = os.umask(0)
    os.umask(mask)
    return mask


# Read once at import time; umask is process-global and not changed by this tool.
_UMASK = _read_umask()

# Windows: antivirus scanners or the search indexer can briefly hold the target open.
_REPLACE_ATTEMPTS = 3
_REPLACE_RETRY_DELAY = 0.1

Content = Union[bytes, str, Iterable[bytes]]


def _replace_with_retry(source: str, target: str) -> None:
    """Move ``source`` over ``target``, retrying briefly on PermissionError."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            logger.debug(f"Target locked, retrying replace: {target}")
            time.sleep(_REPLACE_RETRY_DELAY)


def atomic_write(path: str, content: Content, encoding: str = "utf-8") -> None:
    """
    Write ``content`` to ``path`` atomically.

    Args:
        path: Target file path. A symlink is written through to its target, as a
            plain ``open(path, "w")`` would.
        content: ``str`` (encoded with ``encoding``), ``bytes``, or an iterable of
            ``bytes`` chunks (e.g. a streamed HTTP response)
        encoding: Text encoding for ``str`` content

    Raises:
        OSError: If writing or replacing fails; the temporary file is removed and
            any existing target is left untouched.
    """
    if os.path.islink(path):
        path = os.path.realpath(path)

    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)

    # Keep the existing file's permissions; new files get the usual 0666 & ~umask
    # instead of mkstemp's private 0600.
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        mode = 0o666 & ~_UMASK

    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".part"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            if isinstance(content, str):
                f.write(content.encode(encoding))
            elif isinstance(content, bytes):
                f.write(content)
            else:
                for chunk in content:
                    if chunk:
                        f.write(chunk)
        os.chmod(tmp_path, mode)
        _replace_with_retry(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


# link() is unsupported here (FAT/exFAT, some network shares): fall back to rename.
_NO_LINK_ERRNOS = {
    getattr(errno, name)
    for name in ("EPERM", "EOPNOTSUPP", "ENOTSUP", "EMLINK", "ENOSYS")
    if hasattr(errno, name)
}


def move_no_clobber(source: str, target: str) -> None:
    """
    Move a file to ``target``, never replacing an existing file.

    POSIX ``rename`` silently replaces the target, so on POSIX the file is hard-linked
    to its new name first (``link`` fails atomically with EEXIST when the name is
    taken) and the old name is then unlinked. Windows ``rename`` already refuses an
    existing target. A symlink is moved as a link, not followed.

    Raises:
        FileExistsError: ``target`` exists; nothing changed
        OSError: e.g. EXDEV when ``target`` is on another filesystem; nothing changed
    """
    if os.name == "nt":
        os.rename(source, target)
        return
    try:
        os.link(source, target, follow_symlinks=False)
    except FileExistsError:
        raise
    except OSError as e:
        if e.errno not in _NO_LINK_ERRNOS:
            raise
        if os.path.lexists(target):
            raise FileExistsError(errno.EEXIST, "File exists", target) from e
        os.rename(source, target)
        return
    try:
        os.unlink(source)
    except OSError:
        # Both names point at the same data: dropping the new one loses nothing.
        os.unlink(target)
        raise
