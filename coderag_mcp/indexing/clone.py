"""Validated, capped git cloning for the indexing pipeline."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from coderag_mcp.indexing.models import CloneTimeoutError, InvalidRepoURLError, RepoTooLargeError

ALLOWED_HOSTS = {"github.com", "gitlab.com"}
MAX_REPO_SIZE_MB = 200
CLONE_TIMEOUT_S = 60


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        if parsed.hostname not in ALLOWED_HOSTS:
            raise InvalidRepoURLError(f"host not allowed: {parsed.hostname!r}")
    elif parsed.scheme in ("", "file"):
        # Bare local filesystem paths (used by tests against local fixture
        # repos) never leave the machine, so there is no SSRF surface to
        # allowlist against.
        return
    else:
        raise InvalidRepoURLError(f"unsupported URL scheme: {parsed.scheme!r}")


def _dir_size_mb(path: Path) -> float:
    total_bytes = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total_bytes / (1024 * 1024)


def clone_repo(url: str) -> Path:
    """Clone ``url`` into a fresh temp directory and return the cloned repo's path.

    Raises ``InvalidRepoURLError``, ``CloneTimeoutError``, or ``RepoTooLargeError``
    on failure. The caller owns cleanup of the returned path's parent directory.
    """
    _validate_url(url)

    tmpdir = Path(tempfile.mkdtemp(prefix="coderag-clone-"))
    dest = tmpdir / "repo"

    try:
        subprocess.run(
            ["git", "clone", "--depth=1", url, str(dest)],
            check=True,
            capture_output=True,
            timeout=CLONE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise CloneTimeoutError(f"clone of {url!r} exceeded {CLONE_TIMEOUT_S}s") from exc
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise InvalidRepoURLError(f"git clone failed for {url!r}: {stderr}") from exc

    size_mb = _dir_size_mb(dest)
    if size_mb > MAX_REPO_SIZE_MB:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RepoTooLargeError(f"{url!r} is {size_mb:.1f}MB, exceeds {MAX_REPO_SIZE_MB}MB cap")

    return dest
