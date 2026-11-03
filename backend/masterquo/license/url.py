"""Validate license-service base URLs without trusting string prefixes."""
from __future__ import annotations

from urllib.parse import urlsplit


def valid_license_url(url: object) -> bool:
    """HTTPS for a remote service; cleartext HTTP only for an exact local loopback host.

    A path prefix is allowed for a reverse proxy. Credentials, query strings,
    fragments, backslashes, control characters and whitespace are forbidden.
    """
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return False
    if "\\" in url:
        return False
    try:
        p = urlsplit(url)
        host, port = p.hostname, p.port  # accessing port rejects malformed ports
        if not host or p.username is not None or p.password is not None or p.query or p.fragment:
            return False
        if port is not None and not 1 <= port <= 65535:
            return False
        if p.scheme == "https":
            return True
        return p.scheme == "http" and host.lower() in ("localhost", "127.0.0.1", "::1")
    except (TypeError, ValueError):
        return False
