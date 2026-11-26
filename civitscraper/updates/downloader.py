"""
Download a model file from CivitAI: resumable, hash-verified, never overwriting.

CivitAI's download endpoint (``/api/download/models/<version>?fileId=<file>``)
needs the API key (``Authorization: Bearer``) and answers with a redirect to a
signed storage URL. The redirect is followed by hand so the key is only ever sent
to the API host. Data goes to ``<target>.part`` next to the target; an interrupted
download resumes from there with a Range request. Only a file whose SHA256 matches
CivitAI's is moved into place, without replacing anything.
"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import requests

from ..api.request import RequestHandler
from ..utils.fs import move_no_clobber

logger = logging.getLogger(__name__)

CHUNK = 1024 * 1024
PART_SUFFIX = ".part"

OK = "ok"
UNAUTHORIZED = "unauthorized"
EARLY_ACCESS = "early_access"
NOT_FOUND = "not_found"
FAILED = "failed"
HASH_MISMATCH = "hash_mismatch"
SIZE_MISMATCH = "size_mismatch"
EXISTS = "exists"

ProgressFn = Callable[[int, int], None]


@dataclass
class Result:
    """Outcome of one download."""

    status: str
    message: str = ""
    sha256: Optional[str] = None
    verified: bool = False

    @property
    def ok(self) -> bool:
        """Whether the file is in place."""
        return self.status == OK


def part_path(target: str) -> str:
    """Where a download of ``target`` is written until it is complete."""
    return target + PART_SUFFIX


def download_url(entry: Dict[str, Any], version_id: Any, api_base_url: str) -> str:
    """
    Return the download URL of one file of a version, on the configured API host.

    The file's own ``downloadUrl`` carries ``?fileId=``; without it the version's
    primary file would be served, not the chosen variant.
    """
    api = urlparse(api_base_url)
    url = entry.get("downloadUrl")
    if isinstance(url, str) and url:
        parsed = urlparse(url)
        return urlunparse(parsed._replace(scheme=api.scheme or "https", netloc=api.netloc))
    query = f"?fileId={entry['id']}" if entry.get("id") else ""
    return f"{api.scheme or 'https'}://{api.netloc}/api/download/models/{version_id}{query}"


def _message(response: requests.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            return str(data.get("message") or data.get("error") or "")[:200]
    except ValueError:
        pass
    return (response.text or "")[:200]


class Downloader:
    """Download model files from CivitAI."""

    def __init__(
        self,
        api_key: Optional[str],
        api_host: str,
        user_agent: str = "CivitScraper",
        timeout: float = 30,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        rate_limiter: Any = None,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        """
        Set up downloads.

        Args:
            api_key: CivitAI API key (sent to ``api_host`` only)
            api_host: Hostname of the CivitAI API
            user_agent: User-Agent header
            timeout: Connect/read timeout in seconds
            max_retries: Retries after network errors, 429 and 5xx
            retry_delay: Base delay of the exponential backoff
            rate_limiter: Optional limiter with ``acquire()``
            session: requests session (tests)
            sleep: Sleep function (tests)
        """
        self.api_key = api_key
        self.api_host = api_host
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.rate_limiter = rate_limiter
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.session.headers.pop("Authorization", None)
        self.sleep = sleep

    def _acquire(self) -> None:
        if self.rate_limiter is not None:
            self.rate_limiter.acquire()

    def _locate(self, url: str) -> "tuple[Optional[str], Optional[Result]]":
        """Ask the API for the storage URL: ``(location, None)`` or ``(None, failure)``."""
        attempt = 0
        while True:
            self._acquire()
            headers: Dict[str, Optional[str]] = {}
            if self.api_key and urlparse(url).hostname == self.api_host:
                headers["Authorization"] = f"Bearer {self.api_key}"
            try:
                with self.session.get(
                    url,
                    headers=headers,
                    allow_redirects=False,
                    stream=True,
                    timeout=self.timeout,
                ) as response:
                    status = response.status_code
                    if status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if location:
                            return urljoin(url, location), None
                        return None, Result(FAILED, "redirect without a location")
                    if status == 401:
                        return None, Result(UNAUTHORIZED, _message(response))
                    if status == 403:
                        return None, Result(EARLY_ACCESS, _message(response))
                    if status == 404:
                        return None, Result(NOT_FOUND, _message(response))
                    if status == 429 or status >= 500:
                        if attempt >= self.max_retries:
                            return None, Result(FAILED, f"HTTP {status}")
                        delay = RequestHandler._retry_after_seconds(
                            response.headers.get("Retry-After"), self.retry_delay * 2**attempt
                        )
                        attempt += 1
                        self.sleep(delay)
                        continue
                    if status == 200:
                        return None, Result(FAILED, "the API answered without a redirect")
                    return None, Result(FAILED, f"HTTP {status}: {_message(response)}")
            except requests.RequestException as e:
                if attempt >= self.max_retries:
                    return None, Result(FAILED, str(e))
                attempt += 1
                self.sleep(self.retry_delay * 2 ** (attempt - 1))

    def download(
        self,
        url: str,
        target: str,
        size: Optional[int],
        sha256: Optional[str],
        progress: Optional[ProgressFn] = None,
    ) -> Result:
        """
        Download ``url`` to ``target``.

        Args:
            url: CivitAI download URL (see :func:`download_url`)
            target: Final path; never replaced when it exists
            size: Expected size in bytes (``sizeKB * 1024``), or None
            sha256: Expected SHA256, or None (then only the size is checked)
            progress: Called with ``(bytes done, total bytes)``

        Raises:
            KeyboardInterrupt: The ``.part`` file is kept for a later resume
        """
        if os.path.lexists(target):
            return Result(EXISTS, f"{target} exists")
        part = part_path(target)
        state = _State(hashlib.sha256(), 0)
        if os.path.isfile(part):
            state.have = _hash_into(part, state.digest)
        attempt = 0
        while True:
            location, failure = self._locate(url)
            if failure:
                return failure
            assert location is not None
            try:
                outcome = self._fetch(location, part, state, size, progress)
            except requests.RequestException as e:
                outcome = Result(FAILED, str(e))
            if outcome.status != FAILED or attempt >= self.max_retries:
                break
            attempt += 1
            logger.warning(
                f"Download of {os.path.basename(target)} interrupted ({outcome.message})"
            )
            self.sleep(self.retry_delay * 2 ** (attempt - 1))
        if outcome.status != OK:
            if outcome.status == SIZE_MISMATCH and os.path.isfile(part):
                os.remove(part)
            return outcome
        return self._finish(part, target, state.digest.hexdigest(), sha256)

    def _fetch(
        self,
        location: str,
        part: str,
        state: "_State",
        size: Optional[int],
        progress: Optional[ProgressFn],
    ) -> Result:
        """Fetch the storage URL into ``part``, appending to what ``state`` has."""
        self._acquire()
        # The session never carries the key, and None removes the header anyway.
        headers: Dict[str, Optional[str]] = {"Authorization": None}
        if state.have:
            headers["Range"] = f"bytes={state.have}-"
        with self.session.get(
            location, headers=headers, stream=True, timeout=self.timeout
        ) as response:
            status = response.status_code
            if status == 416 and state.have and size is not None and state.have == size:
                return Result(OK)
            if status == 206:
                start, total = _content_range(response.headers.get("Content-Range"))
                if start != state.have:
                    state.reset(part)
                    return Result(FAILED, "the server could not resume; starting over")
            elif status == 200:
                if state.have:
                    state.reset(part)  # the server ignored the range: start over
                total = _int(response.headers.get("Content-Length"))
            else:
                return Result(FAILED, f"storage answered HTTP {status}")
            if size is not None and total is not None and abs(total - size) > 1024:
                return Result(SIZE_MISMATCH, f"CivitAI said {size} bytes, the server sends {total}")
            expected = total if total is not None else size
            with open(part, "ab" if state.have else "wb") as f:
                try:
                    for block in response.iter_content(chunk_size=CHUNK):
                        if not block:
                            continue
                        f.write(block)
                        state.digest.update(block)
                        state.have += len(block)
                        if progress:
                            progress(state.have, expected or state.have)
                finally:
                    f.flush()
                    os.fsync(f.fileno())
            if expected is not None and state.have != expected:
                return Result(FAILED, f"connection closed after {state.have} of {expected} bytes")
            return Result(OK)

    @staticmethod
    def _finish(part: str, target: str, actual: str, expected: Optional[str]) -> Result:
        verified = bool(expected)
        if expected and actual.lower() != expected.lower():
            os.remove(part)
            return Result(HASH_MISMATCH, "the file does not match CivitAI's SHA256; removed")
        try:
            move_no_clobber(part, target)
        except FileExistsError:
            return Result(EXISTS, f"{target} appeared during the download; kept as {part}")
        return Result(OK, sha256=actual.lower(), verified=verified)


@dataclass
class _State:
    """Bytes in the ``.part`` file and their running SHA256."""

    digest: Any
    have: int

    def reset(self, part: str) -> None:
        """Empty the ``.part`` file and start the hash over."""
        with open(part, "wb"):
            pass
        self.digest = hashlib.sha256()
        self.have = 0


def _hash_into(path: str, digest: Any) -> int:
    """Feed a file into ``digest``; returns its size."""
    have = 0
    with open(path, "rb") as f:
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            digest.update(block)
            have += len(block)
    return have


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _content_range(header: Optional[str]) -> "tuple[Optional[int], Optional[int]]":
    """``bytes 100-199/1000`` -> ``(100, 1000)``; total is the full file size."""
    if not header or not header.startswith("bytes "):
        return None, None
    try:
        span, total = header[6:].split("/", 1)
        start = int(span.split("-", 1)[0])
        return start, (int(total) if total != "*" else None)
    except ValueError:
        return None, None
