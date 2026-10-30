"""Build identity for the static H5 shell, and the cache headers that carry it.

Why this exists: the browser was free to keep serving the previous ``app.js``.
Static files here answered with ``ETag`` and ``Last-Modified`` but no
``Cache-Control``, so browsers fell back to heuristic freshness -- commonly 10%
of the time since ``Last-Modified``, which for a day-old file is hours. An
installed phone therefore kept running an old build with nothing to tell it
otherwise, and a reload did not help because a fresh load was served from the
browser cache without ever contacting us.

Two pieces fix that:

1. ``no-cache`` on the shell files. The response may still be stored, but every
   use must be revalidated. Our ETags are content hashes, so the usual recheck
   is a ``304`` with no body -- cheap on the LAN. ``no-store`` would be wrong:
   it would also drop the offline fallback.
2. A build id derived from the file contents, served both in ``/health`` and
   injected into the HTML. The page can then tell "I am running old code"
   rather than having to guess from a missing UI element.

The id is computed, never hand-maintained. ``__version__`` stays the API
version -- it is a human decision, and asking someone to remember to bump a
constant on every deploy is how it ends up stale.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

# Files whose contents decide whether the client is current. Icons are excluded
# on purpose: they carry no behaviour and are cache-first in the service worker,
# so rotating their hash would announce an update that changes nothing a user
# can see or do.
SHELL_FILES = ("index.html", "app.js", "styles.css", "sw.js", "manifest.webmanifest")

# Excluded from ``no-cache`` for the same reason: they never change behaviour,
# and re-validating them on every load only adds round trips.
_LONG_LIVED_PREFIXES = ("icons/",)

BUILD_META_NAME = "fishagent-build"
BUILD_PLACEHOLDER = "__FISHAGENT_BUILD__"


def compute_build_id(web_dir: Path) -> str:
    """Hash the shell files into a short, stable id.

    Content, not mtime: a git checkout or a restore can move mtimes without
    changing a byte, and that must not look like a new release.
    """
    digest = hashlib.sha256()
    for name in SHELL_FILES:
        path = web_dir / name
        try:
            # Read as text and normalise line endings: git may store CRLF or LF
            # depending on checkout settings, and the same source must not look
            # like two different builds.
            data = path.read_bytes().replace(b"\r\n", b"\n")
        except OSError:
            # A partial checkout must not take the server down; the missing file
            # will fail loudly on its own request path.
            data = b""
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def _is_shell_asset(pathname: str) -> bool:
    rel = pathname.lstrip("/")
    if not rel or rel.endswith("/"):
        # "/" is the shell entry point.
        return True
    if rel.startswith(_LONG_LIVED_PREFIXES):
        return False
    name = rel.rsplit("/", 1)[-1]
    return name in SHELL_FILES


class ShellStaticFiles(StaticFiles):
    """StaticFiles that stops the browser from deciding when to look for updates.

    ``no-cache`` (revalidate every time) rather than ``no-store`` (never keep):
    the copy stays usable offline and a recheck is usually a 304.

    It also stamps the build id into ``index.html``. The page needs to know
    which build it is actually running, and the only trustworthy source for
    that is the server that handed it the bytes -- asking the browser would
    just report whatever it happens to have cached.
    """

    def __init__(self, *args, build_id=compute_build_id, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._build_id = build_id

    def file_response(  # type: ignore[override]
        self,
        full_path,
        stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        path = Path(full_path)
        if path.name == "index.html":
            return self._html_response(path, scope)

        response = super().file_response(full_path, stat_result, scope, status_code)
        if _is_shell_asset(scope.get("path", "")):
            response.headers["Cache-Control"] = "no-cache"
        else:
            # Icons and anything else immutable-ish: a day is plenty, and the
            # service worker already serves them from cache first.
            response.headers.setdefault("Cache-Control", "public, max-age=86400")
        return response

    def _html_response(self, path: Path, scope: Scope) -> Response:
        try:
            body = path.read_bytes()
        except OSError:
            return Response("Not Found", status_code=404)

        if BUILD_PLACEHOLDER.encode() in body:
            body = body.replace(BUILD_PLACEHOLDER.encode(), self._build_id().encode())

        # The body is synthesised here, so the ETag has to match what we send
        # rather than the file on disk; otherwise a revalidation could answer
        # 304 for a document that changed.
        etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
        headers = {
            "Cache-Control": "no-cache",
            "ETag": etag,
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": str(len(body)),
        }

        request_etags = scope.get("headers") or ()
        for key, value in request_etags:
            if key == b"if-none-match" and etag.encode() in value:
                return Response(
                    status_code=304,
                    headers={"Cache-Control": "no-cache", "ETag": etag},
                )

        return Response(content=body, status_code=200, headers=headers)


class BuildIdHolder:
    """Build id shared by /health and the HTML injection, refreshed on change.

    Caching the id once at startup would be wrong: the static mount reads from
    disk on every request, so a deploy that only touches ``web/`` (no restart)
    would hand clients new files while still reporting the old build -- the
    banner would never appear. Instead the signature of the shell files is
    re-read each time; it is five ``stat`` calls, and the hash is only computed
    when that signature actually moved.

    Threading because uvicorn serves the sync file responses in a worker thread
    while /health runs on the event loop.
    """

    def __init__(self, web_dir: Path) -> None:
        self._web_dir = web_dir
        self._lock = threading.Lock()
        self._value: str | None = None
        self._signature: tuple[tuple[str, int, int], ...] | None = None

    def _current_signature(self) -> tuple[tuple[str, int, int], ...]:
        signature = []
        for name in SHELL_FILES:
            try:
                stat = (self._web_dir / name).stat()
            except OSError:
                signature.append((name, -1, -1))
                continue
            signature.append((name, stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    def get(self) -> str:
        signature = self._current_signature()
        # Fast path deliberately outside the lock: this runs per /health poll,
        # and the common case is "nothing changed".
        if self._value is not None and signature == self._signature:
            return self._value
        with self._lock:
            if self._value is None or signature != self._signature:
                self._value = compute_build_id(self._web_dir)
                self._signature = signature
            return self._value
