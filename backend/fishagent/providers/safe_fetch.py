"""Bounded, SSRF-guarded fetching of arbitrary result URLs.

Search results point at third-party sites, so every URL is attacker-influenced
until proven otherwise. This module only allows http(s) to public addresses,
caps the download size and strips the body down to readable text.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

MAX_BYTES = 512 * 1024
_SCRIPT_RE = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{2,}")


def _is_public_ip(raw: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def is_fetchable(url: str) -> bool:
    """True only for http(s) URLs whose host resolves solely to public IPs.

    Residual risk: DNS can be rebound between this check and the request. The
    size cap and timeout bound the damage; this is a best-effort guard, not a
    complete SSRF defence.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    if host in ("localhost", "localhost.localdomain"):
        return False
    # A literal IP is checked directly; a name must resolve entirely to public IPs.
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, UnicodeError, OSError):
        return False
    resolved = {entry[4][0] for entry in addresses if entry[4]}
    if not resolved:
        return False
    return all(_is_public_ip(address) for address in resolved)


def html_to_text(html: str) -> str:
    """Reduce an HTML document to whitespace-normalised readable text."""
    text = _SCRIPT_RE.sub(" ", html)
    text = _COMMENT_RE.sub(" ", text)
    text = _TAG_RE.sub("\n", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = _SPACE_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_LINES_RE.sub("\n", text).strip()


async def fetch_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int = MAX_BYTES,
) -> str:
    """Fetch one URL and return readable text; '' when the fetch is not allowed."""
    if not await is_fetchable(url):
        logger.info("skipping non-public or unsupported URL: %s", url[:120])
        return ""
    try:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                return ""
            content_type = response.headers.get("content-type", "")
            if content_type and not any(
                kind in content_type for kind in ("text/html", "text/plain", "application/xhtml")
            ):
                return ""
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= max_bytes:
                    break
    except httpx.HTTPError as exc:
        logger.info("page fetch failed for %s: %s", url[:120], exc)
        return ""

    raw = b"".join(chunks)[:max_bytes]
    encoding = "utf-8"
    if content_type and "charset=" in content_type:
        encoding = content_type.split("charset=")[-1].split(";")[0].strip() or "utf-8"
    try:
        html = raw.decode(encoding, errors="replace")
    except LookupError:
        html = raw.decode("utf-8", errors="replace")
    if not content_type or "text/html" in content_type:
        return html_to_text(html)
    return " ".join(html.split())
