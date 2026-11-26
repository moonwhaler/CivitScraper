"""
Move files to the desktop Trash (freedesktop.org Trash specification).

A file on the home filesystem goes to ``$XDG_DATA_HOME/Trash``; a file on another
filesystem to ``$topdir/.Trash-$uid`` of its mount point, so trashing is always a
rename on the same filesystem. Each trashed file gets a ``.trashinfo`` record, so
it can be restored from any file manager, or with :func:`restore`.
Linux and other freedesktop systems only (:func:`supported`).
"""

import datetime
import os
import sys
from typing import Tuple
from urllib.parse import quote

from .fs import move_no_clobber


def supported() -> bool:
    """Whether this platform has a freedesktop Trash."""
    return os.name == "posix" and sys.platform != "darwin"


def _home_trash() -> str:
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return os.path.join(data_home, "Trash")


def _mount_point(path: str) -> str:
    path = os.path.realpath(path)
    device = os.stat(path).st_dev
    while True:
        parent = os.path.dirname(path)
        if parent == path:
            return path
        try:
            if os.stat(parent).st_dev != device:
                return path
        except OSError:
            return path
        path = parent


def _device(path: str) -> int:
    current = os.path.abspath(path)
    while not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.stat(current).st_dev


def trash_dir_for(path: str) -> Tuple[str, str]:
    """Return ``(trash dir, base for the Path= entry)`` for a file."""
    home = _home_trash()
    if _device(home) == os.stat(path).st_dev:
        return home, ""
    topdir = _mount_point(os.path.dirname(os.path.abspath(path)))
    return os.path.join(topdir, f".Trash-{os.getuid()}"), topdir


def trash(path: str) -> Tuple[str, str]:
    """
    Move ``path`` to the Trash.

    Returns:
        ``(trashed file, .trashinfo file)``, for :func:`restore`

    Raises:
        OSError: Nothing was trashed
    """
    if not supported():
        raise OSError("no desktop Trash on this platform")
    path = os.path.abspath(path)
    trash_dir, topdir = trash_dir_for(path)
    files_dir = os.path.join(trash_dir, "files")
    info_dir = os.path.join(trash_dir, "info")
    for directory in (trash_dir, files_dir, info_dir):
        os.makedirs(directory, mode=0o700, exist_ok=True)
    original = os.path.relpath(path, topdir) if topdir else path
    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    record = f"[Trash Info]\nPath={quote(original)}\nDeletionDate={stamp}\n"
    name = os.path.basename(path)
    stem, ext = os.path.splitext(name)
    n = 1
    while True:
        candidate = name if n == 1 else f"{stem}.{n}{ext}"
        info_path = os.path.join(info_dir, candidate + ".trashinfo")
        try:
            fd = os.open(info_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            n += 1
            continue
        trashed = os.path.join(files_dir, candidate)
        if os.path.lexists(trashed):
            os.close(fd)
            os.remove(info_path)
            n += 1
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(record)
        try:
            move_no_clobber(path, trashed)
        except OSError:
            os.remove(info_path)
            raise
        return trashed, info_path


def restore(trashed: str, info_path: str, original: str) -> None:
    """
    Move a trashed file back to ``original`` (never replacing a file there).

    Raises:
        OSError: e.g. FileExistsError when ``original`` is taken; nothing changed
    """
    os.makedirs(os.path.dirname(os.path.abspath(original)), exist_ok=True)
    move_no_clobber(trashed, original)
    try:
        os.remove(info_path)
    except FileNotFoundError:
        pass
