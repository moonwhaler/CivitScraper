"""Old run logs are pruned to the newest ``keep_files`` runs."""

import os

from civitscraper.utils.logging import prune_logs


def _touch(directory, name):
    with open(os.path.join(directory, name), "w") as f:
        f.write("x")


def test_keeps_newest_runs_with_their_rotated_pieces(tmp_path):
    """Older runs go, with their rotated pieces; other files stay."""
    for stamp in ("20260101_000000", "20260102_000000", "20260103_000000"):
        _touch(tmp_path, f"civitscraper_{stamp}.log")
    _touch(tmp_path, "civitscraper_20260101_000000.log.1")
    _touch(tmp_path, "civitscraper_20260103_000000.log.1")
    _touch(tmp_path, "other.log")

    deleted = prune_logs(str(tmp_path), 2)

    assert deleted == 2
    assert sorted(os.listdir(tmp_path)) == [
        "civitscraper_20260102_000000.log",
        "civitscraper_20260103_000000.log",
        "civitscraper_20260103_000000.log.1",
        "other.log",
    ]


def test_zero_keeps_everything_and_current_run_survives(tmp_path):
    """``keep`` 0 keeps all; the running log is never deleted."""
    for stamp in ("20260101_000000", "20260102_000000"):
        _touch(tmp_path, f"civitscraper_{stamp}.log")
    assert prune_logs(str(tmp_path), 0) == 0
    current = os.path.join(tmp_path, "civitscraper_20260101_000000.log")
    assert prune_logs(str(tmp_path), 1, current) == 0
    assert len(os.listdir(tmp_path)) == 2


def test_missing_directory(tmp_path):
    """A missing log directory is not an error."""
    assert prune_logs(str(tmp_path / "nope"), 3) == 0
