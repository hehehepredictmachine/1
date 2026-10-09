"""LicenseService - account session, activation, heartbeat/lease, operation authorization and expiry handling
for the local bot. The authoritative rights live on the central server; this module only holds what the server signed.

Effects (documented for the user):
* logout in the monitor: the monitor shows the login screen; the device credential stays (bot features keep working
  only while the server keeps issuing leases for this installation);
* password change: other sessions are revoked by the server; the device credential is NOT affected;
* account blocked / license revoked / seat reset / device revoked: the server stops issuing leases -> the bot loses
  new functions at the end of the current lease (<= 60 s); revocation is immediate on central APIs;
* restart: no lease until the first successful heartbeat.
"""
from __future__ import annotations

import logging
import threading
import time

import jwt
from cryptography.hazmat.primitives import serialization

from .central_client import CentralClient, CentralError
from .device import DeviceIdentity
from .guard import LicenseGuard, LicenseRequired

log = logging.getLogger("masterquo.license")
FATAL = ("LICENSE_EXPIRED", "LICENSE_REVOKED", "NO_ACTIVE_ACTIVATION", "DEVICE_REVOKED", "ACCOUNT_NOT_ACTIVE", "DEVICE_UNKNOWN",
         "LICENSE_ISSUED", "SERVER_CLOCK_ANOMALY")
WARN_AT = (3600, 600)


class OpGrant:
    def __init__(self, claims: dict, deadline: float):
        self.claims, self.deadline = claims, deadline
        self.used = False


class LicenseService:
    def __init__(self, cfg_store, secrets, data_dir, bus=None, applog=None, mono=time.monotonic, wall=time.time):
        self.cfg_store, self.bus, self.log = cfg_store, bus, applog
        self.mono = mono
        self.device = DeviceIdentity(secrets, data_dir / "license")
        self.guard = LicenseGuard(mono=mono, wall=wall)
        self._lock = threading.RLock()
        self._token: str | None = None            # central CLIENT session token - RAM only
        self.user: dict | None = None
        self.license: dict | None = None          # last server view of the license (display)
        self.server_offset: float | None = None   # server_time - local wall (display only)
        self.last_ok_at: float | None = None
        self.last_error: str | None = None
        self.online = False
        self.my_licenses: list = []
        self._used_jti: set[str] = set()
        self._warned: set[tuple] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.guard.listeners.append(self._on_guard_change)
        self.on_lost: list = []                   # fn(reason) - enforcement hooks (orders, ML, engine)
        self.on_restored: list = []

    # ------------------------------------------------------------ helpers
    @property
    def cfg(self):
        return self.cfg_store.get().central

    def client(self) -> CentralClient:
        if not self.cfg.url:
            raise CentralError("CENTRAL_URL_NOT_CONFIGURED")
        return CentralClient(self.cfg.url, allow_insecure_localhost=self.cfg.allow_insecure_localhost)

    def _pub(self, s: str):
        if self.bus:
            self.bus.publish(s, self.status())

    def _info(self, code: str, msg: str) -> None:
        if self.log:
            self.log.info("LICENSE", code, msg)

    def _warn(self, code: str, msg: str) -> None:
        if self.log:
            self.log.warn("LICENSE", code, msg)

    def _on_guard_change(self, valid: bool, reason: str) -> None:
        if valid:
            self._info("RESTORED", "Licencja ważna – funkcje produktu dostępne.")
            for fn in list(self.on_restored):
                try:
                    fn()
                except Exception:
                    log.exception("on_restored")
        else:
            self._warn("LOCKED", f"Brak ważnej licencji ({reason}) – nowe analizy, setupy, trening i nowe otwarcia zatrzymane; "
                                 "ochrona istniejących pozycji działa dalej.")
            for fn in list(self.on_lost):
                try:
                    fn(reason)
                except Exception:
                    log.exception("on_lost")
        self._pub("license")

    # ------------------------------------------------------------ account (proxy to the central server)
    def login(self, email: str, password: str, totp: str | None = None) -> dict:
        out = self.client().login(email, password, totp)
        with self._lock:
            prev = (self.user or {}).get("id")
            self._token, self.user = out["token"], out["user"]
        if prev and prev != out["user"]["id"] and self.bus:
            self.bus.publish("session_reset", {"reason": "USER_CHANGED"})
        self._info("LOGIN", f"Zalogowano: {out['user']['email']}")
        self.refresh_me()
        self.heartbeat_now()
        return self.status()

    def logout(self) -> dict:
        with self._lock:
            tok, self._token, self.user = self._token, None, None
        if tok:
            try:
                self.client().logout(tok)
            except CentralError:
                pass
        if self.bus:
            self.bus.publish("session_reset", {"reason": "LOGOUT"})
        return self.status()

    def logged_in(self) -> bool:
        return self._token is not None and self.user is not None

    def token(self) -> str:
        if not self._token:
            raise CentralError("NOT_LOGGED_IN", 401)
        return self._token

    def refresh_me(self) -> dict | None:
        try:
            me = self.client().me(self.token())
        except CentralError as e:
            if e.status in (401, 403):
                with self._lock:
                    self._token, self.user = None, None
            return None
        with self._lock:
            self.user = me["user"]
            self.my_licenses = me["licenses"]
        return me

    def activate(self, key: str) -> dict:
        priv = self.device.private_key()
        out = self.client().activate(self.token(), key, priv, self.device.public_pem(), self.device.install_id(), self.device.default_name())
        self.device.save(device_id=out["device_id"], activation_id=out["activation_id"], owner_user_id=self.user["id"],
                         lease_public_key=out["lease_public_key"], kid=out["kid"], issuer=out["issuer"])
        self.license = out["license"]
        self._warned.clear()
        self._info("ACTIVATED", f"Licencja {out['license']['key_hint']} aktywna do {time.strftime('%Y-%m-%d %H:%M', time.localtime(out['license']['expires_at']))} "
                                "(czas serwera, 48 h od pierwszej aktywacji).")
        self.heartbeat_now()
        return self.status()

    # ------------------------------------------------------------ lease
    def _verify(self, token: str, aud: str) -> dict:
        st = self.device.state()
        pem = st.get("lease_public_key")
        if not pem:
            raise LicenseRequired("NO_PINNED_SERVER_KEY")
        key = serialization.load_pem_public_key(pem.encode())
        try:
            hdr = jwt.get_unverified_header(token)
            if hdr.get("alg") != "EdDSA" or hdr.get("kid") != st.get("kid"):
                raise LicenseRequired("LEASE_HEADER_INVALID")
            # signature, algorithm, audience and issuer are verified; time is judged with the MONOTONIC clock below,
            # because the local wall clock may be wrong or manipulated.
            c = jwt.decode(token, key, algorithms=["EdDSA"], audience=aud, issuer=st.get("issuer"),
                           options={"verify_exp": False, "verify_nbf": False, "verify_iat": False, "require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti"]})
        except jwt.PyJWTError as e:
            raise LicenseRequired(f"LEASE_SIGNATURE_OR_CLAIMS_INVALID:{type(e).__name__}") from None
        if c.get("dev") != st.get("device_id") or c.get("act") != st.get("activation_id") or c.get("sub") != st.get("owner_user_id"):
            raise LicenseRequired("LEASE_NOT_FOR_THIS_DEVICE")
        ttl = int(c["exp"]) - int(c["iat"])
        if ttl <= 0 or ttl > 60 or int(c["nbf"]) > int(c["iat"]):
            raise LicenseRequired("LEASE_TTL_INVALID")
        return c

    def heartbeat_now(self) -> bool:
        st = self.device.state()
        if not st.get("device_id") or not self.cfg.url:
            self.guard.clear("NOT_ACTIVATED_ON_THIS_COMPUTER" if self.cfg.url else "CENTRAL_URL_NOT_CONFIGURED")
            return False
        try:
            out, t0, _t1 = self.client().device_call(self.device.private_key(), st["device_id"], "POST", "/api/v1/device/heartbeat", {}, mono=self.mono)
            claims = self._verify(out["lease"], "masterquo-bot")
            if claims.get("lic_exp") is not None and int(claims["exp"]) > int(claims["lic_exp"]):
                raise LicenseRequired("LEASE_BEYOND_LICENSE")
            deadline = t0 + (int(claims["exp"]) - int(claims["iat"]))     # conservative: counted from the request START
            self.guard.install(claims, deadline)
            self.license = out["license"]
            self.server_offset = out["server_time"] - time.time()
            self.last_ok_at, self.last_error, self.online = time.time(), None, True
            self._expiry_warnings()
            self._pub("license")
            return True
        except LicenseRequired as e:
            self.last_error = e.reason
            self.guard.clear(e.reason)
        except CentralError as e:
            self.last_error = e.code
            self.online = not e.network
            if e.code in FATAL or e.code.startswith("LICENSE_"):
                self.license = (self.license or {}) | ({"status": e.code.replace("LICENSE_", "")} if e.code.startswith("LICENSE_") else {})
                self.guard.clear(e.code)                   # authoritative refusal: stop now
            # network problem: keep the existing lease ONLY until its original monotonic deadline
            self.guard.poll()
        self._pub("license")
        return False

    def _expiry_warnings(self) -> None:
        lic = self.license or {}
        rem = lic.get("remaining_s")
        if not rem or lic.get("status") != "ACTIVE":
            return
        for w in WARN_AT:
            k = (lic.get("id"), w)
            if rem <= w and k not in self._warned:
                self._warned.add(k)
                if self.bus:
                    self.bus.publish("license_warning", {"minutes": w // 60, "expires_at": lic.get("expires_at"), "license_id": lic.get("id")})
                self._warn("EXPIRES_SOON", f"Licencja wygaśnie za ok. {rem // 60} min (czas serwera).")

    # ------------------------------------------------------------ operation authorization (before every NEW opening order)
    def authorize_open(self, intent_id: str, detail: dict) -> OpGrant:
        self.guard.require("trade_open")
        st = self.device.state()
        try:
            out, t0, _ = self.client().device_call(self.device.private_key(), st["device_id"], "POST", "/api/v1/ops/authorize",
                                                   {"intent_id": intent_id, "op": "OPEN", **{k: detail.get(k) for k in ("symbol", "side", "volume", "mode")}},
                                                   mono=self.mono)
        except CentralError as e:
            if e.code in FATAL:
                self.guard.clear(e.code)
            raise LicenseRequired("OP_AUTH_" + e.code) from None
        c = self._verify(out["op_token"], "masterquo-bot-op")
        if c.get("intent") != intent_id or c.get("op") != "OPEN":
            raise LicenseRequired("OP_TOKEN_MISMATCH")
        return OpGrant(c, t0 + (int(c["exp"]) - int(c["iat"])))

    def consume(self, grant: OpGrant) -> None:
        """Called immediately before order_send. Single use, short validity, still-valid lease."""
        with self._lock:
            jti = grant.claims["jti"]
            if grant.used or jti in self._used_jti:
                raise LicenseRequired("OP_TOKEN_REUSED")
            if self.mono() >= grant.deadline:
                raise LicenseRequired("OP_TOKEN_EXPIRED")
            self.guard.require("trade_open")
            grant.used = True
            self._used_jti.add(jti)

    # ------------------------------------------------------------ loop
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="license-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        last = 0.0
        while not self._stop.is_set():
            self.guard.poll()
            if self.mono() - last >= self.cfg.heartbeat_seconds or not self.guard.allows("analysis") and self.mono() - last >= 5:
                last = self.mono()
                try:
                    self.heartbeat_now()
                except Exception:
                    log.exception("heartbeat")
            self._stop.wait(1.0)

    # ------------------------------------------------------------ status for UI
    def status(self) -> dict:
        st = self.device.state()
        valid = self.guard.allows("analysis")
        lic = dict(self.license or {})
        if self.guard.reason in ("LICENSE_EXPIRED", "LICENSE_REVOKED") and lic.get("status") == "ACTIVE":
            lic["status"], lic["remaining_s"] = self.guard.reason.replace("LICENSE_", ""), 0
        same_user = bool(self.user) and st.get("owner_user_id") == (self.user or {}).get("id")
        return {"configured": bool(self.cfg.url), "central_url": self.cfg.url, "logged_in": self.logged_in(),
                "user": {k: (self.user or {}).get(k) for k in ("id", "email", "display_name", "status", "role")} if self.user else None,
                "activated_here": bool(st.get("device_id")), "owner_matches_user": same_user,
                "valid": valid, "ui_unlocked": valid and same_user, "reason": None if valid else self.guard.reason,
                "lease_remaining_s": round(self.guard.lease_remaining(), 1),
                "license": {k: lic.get(k) for k in ("id", "key_hint", "status", "activated_at", "expires_at", "remaining_s", "type")} if lic else None,
                "online": self.online, "last_ok_at": self.last_ok_at, "last_error": self.last_error,
                "server_offset_s": None if self.server_offset is None else round(self.server_offset, 1),
                "device_key_protection": self.device.protection(),
                "note": "48 godzin liczy się od pierwszej aktywacji według czasu serwera – także gdy program jest wyłączony."}
