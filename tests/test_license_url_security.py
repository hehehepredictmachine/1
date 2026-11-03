"""Regression checks for URL validation and redirects; no license server required."""
from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import _env  # sets project backend on sys.path
from masterquo.license import client
from masterquo.license.edition import load
from masterquo.license.owner import OwnerError, OwnerLicenseManager
from masterquo.license.url import valid_license_url


class TestLicenseUrlSecurity(unittest.TestCase):
    def test_allow_only_valid_service_urls(self):
        for value in ("https://licenses.example.org", "https://licenses.example.org/pmw", "http://localhost:8000",
                      "http://127.0.0.1:8000", "http://[::1]:8000"):
            with self.subTest(value=value):
                self.assertTrue(valid_license_url(value))
        for value in ("http://localhost.evil.example", "http://127.0.0.1.evil.example", "http://localhost@evil.example",
                      "http://127.0.0.1@evil.example", "https://user:password@example.org", "https://example.org?x=1",
                      "https://example.org/#fragment", "https://example.org\\@evil.org", "https://bad host", "https://",
                      "http://192.168.1.1", "https://example.org:99999", "https://example.org\n.evil.org"):
            with self.subTest(value=value):
                self.assertFalse(valid_license_url(value))

    def test_client_edition_rejects_loopback_prefix_impostor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edition.json"
            path.write_text(json.dumps({"edition": "CLIENT", "license_api": "http://localhost.evil.example",
                                        "public_key": base64.b64encode(bytes(32)).decode()}))
            self.assertIsNotNone(load(path).problem)

    def test_owner_does_not_contact_loopback_prefix_impostor(self):
        called = []
        with tempfile.TemporaryDirectory() as tmp:
            owner = OwnerLicenseManager(Path(tmp), request=lambda *a, **k: called.append(a))
            with self.assertRaises(OwnerError):
                owner.set_server("http://127.0.0.1.evil.example")
        self.assertEqual(called, [])

    def test_redirect_does_not_forward_token(self):
        hits = []

        class Destination(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        target = HTTPServer(("127.0.0.1", 0), Destination)

        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{target.server_port}/collect")
                self.end_headers()

            def log_message(self, *args):
                pass

        origin = HTTPServer(("127.0.0.1", 0), Redirect)
        threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (origin, target)]
        for t in threads:
            t.start()
        try:
            with self.assertRaises(client.ApiError) as cm:
                client.request(f"http://127.0.0.1:{origin.server_port}", "/api/v1/admin/stats", token="test-token")
            self.assertEqual(cm.exception.code, "REDIRECT_REFUSED")
            self.assertEqual(hits, [])
        finally:
            for s in (origin, target):
                s.shutdown()
                s.server_close()
            for t in threads:
                t.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
