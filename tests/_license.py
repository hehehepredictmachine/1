"""Test helpers for licensing.

* AllowGuard - ONLY for unit tests that construct single components (gateway, agent) without a runtime; it lives in
  tests/, is not part of the product and is never shipped in the client package.
* LicenseServerFixture - a real mqlicense server (separate package server/mqlicense) on 127.0.0.1 with fresh keys in a
  temporary directory; used by the process/UI tests, which start MasterQUO exactly like masterquo_start and paste a key
  on stdin.
"""
from __future__ import annotations

import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "server") not in sys.path:
    sys.path.insert(0, str(ROOT / "server"))

TEST_ADMIN = {"id": "test-admin", "email": "test-admin@example.invalid", "role": "ADMIN"}


class AllowGuard:
    def ok(self) -> bool:
        return True

    def status(self) -> dict:
        return {"state": "ACTIVE", "ok": True, "test": True}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class LicenseServerFixture:
    def __init__(self, *, clock=None, lease_seconds: int = 30, serve: bool = True):
        import base64
        import secrets as _s

        from cryptography.fernet import Fernet
        from mqlicense import security as sec
        from mqlicense.clock import SystemClock
        from mqlicense.config import Settings
        from mqlicense.db import DB
        from mqlicense.service import LicenseService
        self.dir = Path(tempfile.mkdtemp(prefix="mql_test_"))
        self.public_pem = sec.gen_signing_key(self.dir / "signing.pem")
        self.settings = Settings(env="test", db_path=str(self.dir / "lic.sqlite3"), signing_key_file=str(self.dir / "signing.pem"),
                                 key_pepper=base64.urlsafe_b64encode(_s.token_bytes(32)).decode(), data_key=Fernet.generate_key().decode(),
                                 lease_seconds=lease_seconds, host="127.0.0.1", port=free_port())
        self.db = DB(self.settings.db_path)
        self.clock = clock or SystemClock(self.db)
        self.svc = LicenseService(self.settings, self.db, self.clock)
        self.url = f"http://127.0.0.1:{self.settings.port}"
        self.server = None
        if serve:
            self._serve()

    def _serve(self) -> None:
        import uvicorn
        from mqlicense.api import create_app
        cfg = uvicorn.Config(create_app(self.svc), host="127.0.0.1", port=self.settings.port, log_level="error", access_log=False, lifespan="off")
        self.server = uvicorn.Server(cfg)
        self._t = threading.Thread(target=self.server.run, daemon=True)
        self._t.start()
        for _ in range(100):
            if self.server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("license test server did not start")

    def issue(self, **kw) -> dict:
        return self.svc.create_license(TEST_ADMIN, **kw)

    def client_config(self) -> dict:
        return {"license": {"server_url": self.url, "public_key_pem": self.public_pem}}

    def close(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
            self._t.join(timeout=5)
        shutil.rmtree(self.dir, ignore_errors=True)
