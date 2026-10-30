"""The served shell must carry a build id the page can compare against."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fishagent import static_build

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def test_health_carries_a_build_id(client):
    body = client.get("/health").json()
    assert body["build"], "build id must not be empty; the page polls for it"
    assert re.fullmatch(r"[0-9a-f]{12}", body["build"])


def test_health_is_not_cached(client):
    """A cached /health would have the page polling a stale answer forever."""
    response = client.get("/health")
    assert response.headers["cache-control"] == "no-store"


def test_index_serves_the_same_build_as_health(client):
    """The page compares its own build against /health, so they must agree."""
    served = client.get("/").text
    match = re.search(r'name="fishagent-build" content="([^"]*)"', served)
    assert match, "index.html must carry the build meta tag"
    assert match.group(1) == client.get("/health").json()["build"]


def test_build_placeholder_is_never_served(client):
    """Shipping the literal placeholder would read as a phantom update."""
    assert static_build.BUILD_PLACEHOLDER not in client.get("/").text


def test_shell_assets_must_be_revalidated(client):
    """Without this the browser invents a freshness lifetime and never asks.

    Regression: static responses carried ETag and Last-Modified but no
    Cache-Control, so heuristic freshness (10% of the file's age) let a phone
    keep running the previous app.js for hours, with no reload able to help.
    """
    for path in ("/", "/app.js", "/styles.css", "/sw.js", "/manifest.webmanifest"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers.get("cache-control") == "no-cache", path


def test_icons_stay_cheap_to_serve(client):
    """Icons carry no behaviour; revalidating them buys nothing."""
    response = client.get("/icons/icon-192.png")
    assert response.status_code == 200
    assert "max-age" in response.headers.get("cache-control", "")


def test_index_revalidation_is_a_304(client):
    """The injected HTML must keep a usable ETag, or every poll sends a body."""
    first = client.get("/")
    etag = first.headers["etag"]
    again = client.get("/", headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_build_id_changes_with_content(tmp_path):
    web = tmp_path
    for name in static_build.SHELL_FILES:
        (web / name).write_text("x", encoding="utf-8")
    first = static_build.compute_build_id(web)
    (web / "app.js").write_text("y", encoding="utf-8")
    assert static_build.compute_build_id(web) != first


def test_build_id_ignores_line_ending_style(tmp_path):
    """A CRLF checkout is the same build; it must not look like a release."""
    web = tmp_path
    for name in static_build.SHELL_FILES:
        (web / name).write_bytes(b"a\nb\n")
    lf = static_build.compute_build_id(web)
    (web / "app.js").write_bytes(b"a\r\nb\r\n")
    assert static_build.compute_build_id(web) == lf


def test_holder_notices_a_change_without_a_restart(tmp_path):
    """A deploy that only touches web/ must still be visible.

    The static mount reads from disk per request, so caching the id once at
    startup would serve new files while reporting the old build -- the banner
    would never fire for exactly the deploy it exists to announce.
    """
    web = tmp_path
    for name in static_build.SHELL_FILES:
        (web / name).write_text("v1", encoding="utf-8")
    holder = static_build.BuildIdHolder(web)
    first = holder.get()

    (web / "app.js").write_text("v2", encoding="utf-8")
    assert holder.get() != first


def test_holder_is_stable_when_nothing_changes(tmp_path):
    web = tmp_path
    for name in static_build.SHELL_FILES:
        (web / name).write_text("v1", encoding="utf-8")
    holder = static_build.BuildIdHolder(web)
    assert holder.get() == holder.get()


@pytest.mark.parametrize("path", ["/app.js", "/styles.css", "/sw.js"])
def test_served_shell_assets_exist(client, path):
    assert client.get(path).status_code == 200
