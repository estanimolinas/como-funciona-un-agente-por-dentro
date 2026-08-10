"""Validated, capped git cloning for the indexing pipeline."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from coderag_mcp.config import get_settings
from coderag_mcp.indexing.models import CloneTimeoutError, InvalidRepoURLError, RepoTooLargeError


def _looks_like_scp_style(url: str) -> bool:
    """True for git's SCP-style remote syntax: [user@]host:path (no scheme)."""
    if "://" in url:
        return False
    colon_index = url.find(":")
    if colon_index == -1:
        return False
    slash_index = url.find("/")
    return slash_index == -1 or colon_index < slash_index


def _validate_url(url: str, *, allow_local_paths: bool, allowed_hosts: list[str]) -> None:
    if url.startswith("-"):
        raise InvalidRepoURLError(f"URL must not start with '-': {url!r}")

    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        if parsed.hostname not in allowed_hosts:
            raise InvalidRepoURLError(f"host not allowed: {parsed.hostname!r}")
    elif parsed.scheme == "":
        if _looks_like_scp_style(url):
            raise InvalidRepoURLError(f"SCP-style git URLs are not allowed: {url!r}")
        # A bare local filesystem path (used by tests against local fixture
        # repos) never leaves the machine, so there is no SSRF surface to
        # allowlist against — but callers must opt in explicitly, since a
        # future HTTP/MCP caller must never be able to trigger local file
        # disclosure just by passing a path instead of a URL.
        if allow_local_paths:
            return
        raise InvalidRepoURLError(f"local filesystem paths are not allowed: {url!r}")
    else:
        raise InvalidRepoURLError(f"unsupported URL scheme: {parsed.scheme!r}")


def _dir_size_mb(path: Path) -> float:
    total_bytes = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total_bytes / (1024 * 1024)


def clone_repo(url: str, *, allow_local_paths: bool = False) -> Path:
    """Clone ``url`` into a fresh temp directory and return the cloned repo's path.

    ``allow_local_paths`` must be explicitly set to ``True`` to permit cloning
    from a bare local filesystem path (used by tests against local fixture
    repos) — callers driven by untrusted input (HTTP/MCP) must leave this
    ``False`` to avoid local file disclosure.

    Raises ``InvalidRepoURLError``, ``CloneTimeoutError``, or ``RepoTooLargeError``
    on failure. The caller owns cleanup via ``cleanup_clone``.
    """
    settings = get_settings()
    _validate_url(url, allow_local_paths=allow_local_paths, allowed_hosts=settings.allowed_hosts)

    tmpdir = Path(tempfile.mkdtemp(prefix="coderag-clone-"))
    dest = tmpdir / "repo"

    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                f"--filter=blob:limit={settings.max_repo_size_mb}m",
                "--",
                url,
                str(dest),
            ],
            check=True,
            capture_output=True,
            timeout=settings.clone_timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise CloneTimeoutError(f"clone of {url!r} exceeded {settings.clone_timeout_s}s") from exc
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise InvalidRepoURLError(f"git clone failed for {url!r}: {stderr}") from exc

    size_mb = _dir_size_mb(dest)
    if size_mb > settings.max_repo_size_mb:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RepoTooLargeError(f"{url!r} is {size_mb:.1f}MB, exceeds {settings.max_repo_size_mb}MB cap")

    return dest


def cleanup_clone(cloned_path: Path) -> None:
    """Remove the temp directory tree that clone_repo created for cloned_path."""
    shutil.rmtree(cloned_path.parent, ignore_errors=True)
