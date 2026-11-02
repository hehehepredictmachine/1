"""Device fingerprint for license binding - a practical deterrent, not proof of hardware identity.

Windows (the supported client OS) - identifiers, normalized and hashed together, never sent in clear:
  1. MachineGuid      HKLM\\SOFTWARE\\Microsoft\\Cryptography (created at Windows installation; changes after a reinstall)
  2. SMBIOS UUID      Win32_ComputerSystemProduct.UUID (motherboard firmware; placeholder values such as all-F are ignored)
  3. system volume serial number of %SystemDrive% (changes after reformatting the system drive)
MAC addresses are NOT used. At least one of (1) or (2) is required. A reinstall of Windows, a motherboard swap or some
virtual machines change the fingerprint - the administrator then resets the device binding.
Fingerprint = SHA-256("PMW-HWID-v1|mg=<guid>|uuid=<uuid>|vol=<serial>") as 64 hex characters.

Other OS (development / tests): /etc/machine-id (or the D-Bus id) + host name. PMW_HWID_OVERRIDE (non-Windows only) sets
the fingerprint source for tests.
"""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import threading

_cache: dict = {}
_lock = threading.Lock()
BAD_UUIDS = {"", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF", "00000000-0000-0000-0000-000000000000", "03000200-0400-0500-0006-000700080009"}


class HwidError(Exception):
    pass


def _machine_guid() -> str | None:
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        v, _ = winreg.QueryValueEx(k, "MachineGuid")
        return str(v).strip().lower() or None
    except OSError:
        return None


def _smbios_uuid() -> str | None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    cmds = [["powershell", "-NoProfile", "-NonInteractive", "-Command", "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID"],
            ["wmic", "csproduct", "get", "UUID"]]
    for cmd in cmds:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15, creationflags=flags).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for line in out.splitlines():
            v = line.strip().upper()
            if len(v) == 36 and v.count("-") == 4 and v not in BAD_UUIDS:
                return v
    return None


def _volume_serial() -> str | None:
    try:
        import ctypes
        serial = ctypes.c_uint32()
        root = (os.environ.get("SystemDrive") or "C:") + "\\"
        ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), None, 0, ctypes.byref(serial), None, None, None, 0)
        return f"{serial.value:08X}" if ok else None
    except (OSError, AttributeError):
        return None


def components() -> dict:
    """The identifiers that go into the fingerprint (local diagnostics only - never transmitted)."""
    if sys.platform == "win32":
        return {"mg": _machine_guid(), "uuid": _smbios_uuid(), "vol": _volume_serial()}
    override = os.environ.get("PMW_HWID_OVERRIDE")
    if override:
        return {"mg": override, "uuid": None, "vol": None}
    mid = None
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            mid = open(p, encoding="ascii").read().strip() or None
            if mid:
                break
        except OSError:
            continue
    return {"mg": mid, "uuid": platform.node() or None, "vol": None}


def fingerprint() -> str:
    """64-hex SHA-256 of the normalized identifiers (cached for the process; override changes in tests are honored)."""
    key = os.environ.get("PMW_HWID_OVERRIDE", "") if sys.platform != "win32" else "win"
    with _lock:
        if key in _cache:
            return _cache[key]
        c = components()
        if not c.get("mg") and not c.get("uuid"):
            raise HwidError("nie udało się odczytać identyfikatora urządzenia (MachineGuid / SMBIOS UUID)")
        norm = f"PMW-HWID-v1|mg={c.get('mg') or ''}|uuid={c.get('uuid') or ''}|vol={c.get('vol') or ''}"
        _cache[key] = hashlib.sha256(norm.encode("utf-8")).hexdigest()
        return _cache[key]
