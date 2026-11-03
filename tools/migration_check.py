"""Upgrade 1.28 -> 1.29 and rollback, checked on COPIES of the data (never the user's own folder) - §5 of the update package.

  python tools/migration_check.py [--old-ref 165bd5d] [--keep]

What it does (everything in a temporary folder, terminal simulator = SYNTHETIC data, no MT5, no orders):
 Bot (OWNER):
  1. 1.28 (git worktree of --old-ref) starts on a fresh data folder, computes market zones, saves the License Manager address,
     then stops - this is "the user's 1.28 data";
  2. a copy is kept as the backup made before the upgrade (the desktop app does this itself in <home>/backups);
  3. 1.29 (this repository) starts on a second copy: version, configuration kept, database migrations, zones restored (marked
     stale), License Manager keeps the server address and now uses the device key (no password);
  4. rollback: 1.28 starts on the backup copy (restore = copy the backup back) and works; for information also 1.28 started directly
     on the folder already used by 1.29.
 License API:
  5. the 1.28 server creates a database with a licence; 1.29 opens a copy -> schema v2 (admin_keys, admin_nonces), licence kept,
     backup-db works; rollback: the 1.28 server reads the v2 database (the new tables are ignored).
Prints one line per check (PASS / FAIL) and exits 1 when anything failed. Requires git (worktree) and the Python of the bot.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{' – ' + detail if detail else ''}", flush=True)
    return bool(ok)


class Http:
    """The panel's own way in: page "/" sets the session cookie, /api/v1/session gives the CSRF token for writes."""
    def __init__(self, port: int):
        import http.cookiejar
        self.port = port
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.open(f"http://127.0.0.1:{port}/", timeout=10).read()
        self.csrf = json.loads(self.op.open(f"http://127.0.0.1:{port}/api/v1/session", timeout=10).read()).get("csrf") or ""

    def get(self, path: str, timeout: float = 15):
        return json.loads(self.op.open(f"http://127.0.0.1:{self.port}{path}", timeout=timeout).read())

    def post(self, path: str, body: dict, timeout: float = 30):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-MQ-CSRF": self.csrf, "Origin": f"http://127.0.0.1:{self.port}"})
        return json.loads(self.op.open(req, timeout=timeout).read())


def health(port: int) -> bool:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=3) as r:
        return r.status == 200


class Bot:
    def __init__(self, tree: Path, data: Path, port: int):
        self.tree, self.data, self.port = tree, data, port
        self.env = dict(os.environ, MASTERQUO_DATA_DIR=str(data), PYTHONPATH=str(tree / "backend"))
        for k in ("ANTHROPIC_API_KEY", "MASTERQUO_EDITION_FILE"):
            self.env.pop(k, None)
        self.proc = None

    def __enter__(self):
        self.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=self.env,
                                     cwd=str(self.tree / "backend"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t0 = time.time()
        while time.time() - t0 < 120:
            try:
                if health(self.port):
                    self.http = Http(self.port)
                    return self
            except Exception:
                time.sleep(0.5)
        raise RuntimeError(f"bot {self.tree.name} did not start on {self.port}")

    def __exit__(self, *exc):
        subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=self.env, cwd=str(self.tree / "backend"), timeout=90,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.proc.wait(timeout=40)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def wait(fn, timeout: float, step: float = 0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        time.sleep(step)
    return None


def bot_part(old: Path, tmp: Path) -> None:
    d_old = tmp / "data_128"
    d_old.mkdir()
    cfg = {"server": {"port": 8811, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None}, "first_run_completed": True,
           "assets": {"active": "XAUUSD", "mappings": {"XAUUSD": {"broker_symbol": "XAUUSD-", "status": "USER_SPECIFIED"}}}}
    (d_old / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (d_old / "license_owner.json").write_text(json.dumps({"server_url": "https://licencje.example.invalid"}), encoding="utf-8")   # 1.28 format
    with Bot(old, d_old, 8811) as b:
        h = b.http
        v = h.get("/api/v1/state")
        check("1.28 startuje na świeżych danych", v.get("app_version", "").startswith("1.28"), v.get("app_version", "?"))
        wait(lambda: h.get("/api/v1/market-zones/bars?instrument=XAUUSD&tf=M5&count=40")["bars"], 60)
        h.post("/api/v1/market-zones/compute", {"instrument": "XAUUSD", "timeframes": ["M5", "M15"]})
        z = wait(lambda: h.get("/api/v1/market-zones?instrument=XAUUSD")["timeframes"]["M5"].get("computed"), 60)
        check("1.28 wyznaczył strefy M5 (dane do migracji)", bool(z))
        mig_old = sorted(r[0] for r in sqlite3.connect(str(d_old / "masterquo.sqlite")).execute("SELECT version FROM schema_migrations"))
    backup = tmp / "backup_before_1_29"
    shutil.copytree(d_old, backup)
    d_new = tmp / "data_upgraded"
    shutil.copytree(d_old, d_new)
    cfg_new = json.loads((d_new / "config.json").read_text(encoding="utf-8"))
    cfg_new["server"]["port"] = 8812
    (d_new / "config.json").write_text(json.dumps(cfg_new), encoding="utf-8")
    with Bot(ROOT, d_new, 8812) as b:
        h = b.http
        v = h.get("/api/v1/state")
        check("1.29 startuje na kopii danych 1.28", v.get("app_version") == "1.29.0", v.get("app_version", "?"))
        c = h.get("/api/v1/config")["config"]
        check("konfiguracja zachowana (aktywa, mapowanie, port)", c.get("assets", {}).get("mappings", {}).get("XAUUSD", {}).get("broker_symbol") == "XAUUSD-"
              and c.get("server", {}).get("port") == 8812 and c.get("first_run_completed") is True)
        mz = h.get("/api/v1/market-zones?instrument=XAUUSD")["timeframes"]["M5"]
        check("strefy z 1.28 odtworzone po aktualizacji (oznaczone jako nieaktualne do przeliczenia)",
              mz.get("computed") and (mz.get("restored") or mz.get("stale")) is not None, f"computed={mz.get('computed')} restored={mz.get('restored')}")
        try:
            own = h.post("/api/v1/owner/license-server/check", {})
        except Exception as e:  # noqa: BLE001 - the example address does not exist: the state must say so, not crash
            own = {"error": str(e)}
        check("License Manager 1.29: adres z 1.28, uwierzytelnianie kluczem urządzenia", own.get("server_url") == "https://licencje.example.invalid"
              and own.get("auth") == "DEVICE_KEY", f"paired={own.get('paired')} reason={str(own.get('reason'))[:60]}")
        db = d_new / "masterquo.sqlite"
        mig_new = sorted(r[0] for r in sqlite3.connect(str(db)).execute("SELECT version FROM schema_migrations"))
        check("migracje bazy: wszystkie z 1.28 zachowane", set(mig_old) <= set(mig_new), f"{len(mig_old)} -> {len(mig_new)}")
    owner_cfg = json.loads((d_new / "license_owner.json").read_text(encoding="utf-8"))
    check("adres serwera licencji z 1.28 zachowany", owner_cfg.get("server_url") == "https://licencje.example.invalid")
    check("brak hasła/sesji administratora w danych 1.29", not ({"password", "session", "token"} & set(owner_cfg)))
    # rollback = restore the backup folder, then start 1.28
    cfg_b = json.loads((backup / "config.json").read_text(encoding="utf-8"))
    cfg_b["server"]["port"] = 8813
    (backup / "config.json").write_text(json.dumps(cfg_b), encoding="utf-8")
    with Bot(old, backup, 8813) as b:
        v = b.http.get("/api/v1/state")
        check("powrót: 1.28 działa na kopii zapasowej sprzed aktualizacji", v.get("app_version", "").startswith("1.28"))
    cfg_n = json.loads((d_new / "config.json").read_text(encoding="utf-8"))
    cfg_n["server"]["port"] = 8814
    (d_new / "config.json").write_text(json.dumps(cfg_n), encoding="utf-8")
    try:
        with Bot(old, d_new, 8814) as b:
            v = b.http.get("/api/v1/state")
            check("(informacyjnie) 1.28 uruchomiony wprost na danych po 1.29", v.get("app_version", "").startswith("1.28"))
    except RuntimeError as e:
        check("(informacyjnie) 1.28 uruchomiony wprost na danych po 1.29", False, f"{e} – użyj kopii zapasowej")


def server_part(old: Path, tmp: Path) -> None:
    s = tmp / "server"
    (s / "secrets").mkdir(parents=True)
    env = dict(os.environ, PMW_LIC_DATABASE=str(s / "data" / "licenses.db"), PMW_LIC_SIGNING_KEY=str(s / "secrets" / "signing_key.pem"),
               PMW_LIC_KEY_PEPPER="migration-check-pepper-" + "x" * 30, PYTHONPATH=str(old / "license_server"))
    run = lambda tree, *a: subprocess.run([sys.executable, "-m", "pmw_license", *a], cwd=str(s),  # noqa: E731
                                          env={**env, "PYTHONPATH": str(tree / "license_server")}, capture_output=True, text=True, timeout=120)
    r1 = run(old, "init-keys")
    r2 = run(old, "create-license", "--duration", "72h", "--note", "migracja")
    check("serwer 1.28: baza + licencja", r1.returncode == 0 and r2.returncode == 0, (r2.stderr or "")[-200:])
    db = s / "data" / "licenses.db"
    v1 = sqlite3.connect(str(db)).execute("SELECT version FROM schema_version").fetchone()[0]
    n1 = sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM licenses").fetchone()[0]
    shutil.copy2(db, s / "licenses_backup_1_28.db")
    r3 = run(ROOT, "admin-keys", "list")
    con = sqlite3.connect(str(db))
    v2 = con.execute("SELECT version FROM schema_version").fetchone()[0]
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    n2 = con.execute("SELECT COUNT(*) FROM licenses").fetchone()[0]
    con.close()
    check("serwer 1.29: schemat v1 -> v2 (admin_keys, admin_nonces), licencje zachowane",
          r3.returncode == 0 and v1 == 1 and v2 == 2 and {"admin_keys", "admin_nonces"} <= tables and n1 == n2 == 1, f"v{v1}->v{v2}, {n1}->{n2}")
    r4 = run(ROOT, "backup-db", "--out", str(s / "backup_after.db"))
    check("serwer 1.29: backup-db", r4.returncode == 0 and (s / "backup_after.db").exists())
    r5 = run(old, "create-license", "--duration", "7d")
    n3 = sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM licenses").fetchone()[0]
    check("powrót serwera: 1.28 pracuje na bazie v2 (nowe tabele pomijane)", r5.returncode == 0 and n3 == 2, (r5.stderr or "")[-200:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-ref", default="165bd5d", help="commit / tag of 1.28.0")
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="pmw_migration_"))
    old = tmp / "pmw_1_28"
    try:
        subprocess.run(["git", "worktree", "add", "-f", "--detach", str(old), a.old_ref], cwd=str(ROOT), check=True, capture_output=True)
        bot_part(old, tmp)
        server_part(old, tmp)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(old)], cwd=str(ROOT), capture_output=True)
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)
    failed = [n for n, ok, _ in RESULTS if not ok and not n.startswith("(informacyjnie)")]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} PASS" + (f"; FAIL: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
