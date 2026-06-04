"""Minimal SSRF-guarded HTTPS JSON transport (stdlib only).

The whole engine talks to the network through this one function so the safety
properties live in a single place: HTTPS only, public hosts only, no redirects
to private space. Unit tests never call this (the Wave/Gmail layers expose mock
seams), so it stays dependency-free.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlparse

__all__ = ["post_json", "NetError", "HTTPStatusError"]


class NetError(Exception):
    """Base transport error."""


class HTTPStatusError(NetError):
    """Non-2xx HTTP response. Carries the status code for callers to translate."""

    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


def _host_is_public(host: str) -> bool:
    """Resolve host and reject loopback/private/link-local/reserved addresses."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise NetError(f"cannot resolve host {host!r}") from exc
    for info in infos:
        addr = info[4][0]
        ip = ipaddress.ip_address(addr.split("%")[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def post_json(
    url: str,
    headers: dict[str, str],
    payload: dict,
    *,
    timeout: float = 30.0,
) -> dict:
    """POST a JSON body to an HTTPS URL and return the parsed JSON response.

    Raises NetError for scheme/host violations and HTTPStatusError for non-2xx.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise NetError(f"refusing non-https url: {url!r}")
    if not parsed.hostname:
        raise NetError(f"url has no host: {url!r}")
    if not _host_is_public(parsed.hostname):
        raise NetError(f"refusing request to non-public host: {parsed.hostname!r}")

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        req.add_header(key, value)

    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:500]
        except Exception:
            pass
        raise HTTPStatusError(exc.code, detail) from exc
    except urllib.error.URLError as exc:  # type: ignore[attr-defined]
        raise NetError(str(exc.reason)) from exc
