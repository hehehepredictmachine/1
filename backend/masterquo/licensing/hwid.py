"""HWID komputera dla licencji PMW1 (1.43.0).

get_hwid() = SHA-256("PMW-HWID-v1|" + MachineGuid + "|" + UUID płyty głównej) -> pierwsze 100 bitów -> Base32 Crockford ->
4 grupy po 5 znaków, np. "A1B2C-D3E4F-G5H6J-K7M8N". Alfabet bez I, L, O, U (nie da się pomylić 0/O ani 1/I/L).

Źródła (Windows):
  * MachineGuid  – HKLM\\SOFTWARE\\Microsoft\\Cryptography (widok 64-bitowy rejestru);
  * UUID płyty   – tabela SMBIOS typu 1 (GetSystemFirmwareTable 'RSMB'; to samo co Win32_ComputerSystemProduct.UUID),
                   awaryjnie PowerShell Get-CimInstance (wmic bywa usunięty w Windows 11).
Poza Windows (testy, deweloperka): /etc/machine-id i /sys/class/dmi/id/product_uuid.
Brak jednego źródła nie blokuje HWID (w jego miejsce wchodzi "-"); brak obu = HwidError.
Ten sam wzór policzy później aplikacja klienta przy sprawdzaniu licencji – nie zmieniać bez nowej wersji ("PMW-HWID-v2").
"""
from __future__ import annotations

import functools
import hashlib
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"          # Base32 Crockford
_CH = "[0-9A-HJKMNP-TV-Z]"
HWID_RE = re.compile(rf"^{_CH}{{5}}(?:-{_CH}{{5}}){{3}}$")
HWID_FORMAT_PL = "XXXXX-XXXXX-XXXXX-XXXXX (4 grupy po 5 znaków: cyfry i litery A–Z bez I, L, O, U)"
DOMAIN = "PMW-HWID-v1"


class HwidError(RuntimeError):
    pass


def format_hwid(digest: bytes) -> str:
    """Pierwsze 100 bitów skrótu -> 20 znaków Base32 Crockford -> 4 grupy po 5."""
    n = int.from_bytes(digest[:13], "big") >> 4                  # 104 bity -> 100 bitów
    chars = [ALPHABET[(n >> (5 * (19 - i))) & 31] for i in range(20)]
    s = "".join(chars)
    return "-".join(s[i:i + 5] for i in range(0, 20, 5))


def hwid_from_sources(machine_guid: str | None, board_uuid: str | None) -> str:
    g = (machine_guid or "").strip().lower()
    u = (board_uuid or "").strip().lower()
    if not g and not u:
        raise HwidError("nie udało się odczytać MachineGuid ani UUID płyty głównej")
    return format_hwid(hashlib.sha256(f"{DOMAIN}|{g or '-'}|{u or '-'}".encode("utf-8")).digest())


def normalize_hwid(text: str | None) -> str | None:
    """Wpisany / wklejony HWID -> postać kanoniczna (wielkie litery, bez spacji) albo None, gdy format jest zły.
    Litery spoza alfabetu (I, L, O, U) są błędem – nie są po cichu zamieniane."""
    if text is None:
        return None
    s = re.sub(r"\s+", "", str(text)).upper()
    return s if HWID_RE.match(s) else None


# ---------------------------------------------------------------------------------------------------------------- źródła
def _machine_guid() -> str | None:
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
                v, _ = winreg.QueryValueEx(k, "MachineGuid")
                return str(v).strip() or None
        except OSError:
            return None
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            v = Path(p).read_text(encoding="ascii").strip()
            if v:
                return v
        except OSError:
            continue
    return None


def _uuid_ok(u: bytes) -> bool:
    return len(u) == 16 and u not in (b"\x00" * 16, b"\xff" * 16)


def parse_smbios_uuid(table: bytes) -> str | None:
    """UUID z surowej tabeli SMBIOS (struktura typu 1, przesunięcie 0x08, 16 bajtów). Od SMBIOS 2.6 trzy pierwsze pola są
    little-endian – zapis jak w Windows (Win32_ComputerSystemProduct.UUID)."""
    i = 0
    while i + 4 <= len(table):
        typ, ln = table[i], table[i + 1]
        if ln < 4:
            break
        if typ == 1 and ln >= 0x19 and i + 0x18 <= len(table):
            u = table[i + 8:i + 24]
            return str(uuid.UUID(bytes_le=u)).upper() if _uuid_ok(u) else None
        if typ == 127:                                            # koniec tabeli
            break
        j = i + ln                                                # obszar sformatowany, potem napisy zakończone podwójnym NUL
        while j + 1 < len(table) and not (table[j] == 0 and table[j + 1] == 0):
            j += 1
        i = j + 2
    return None


def _board_uuid_windows() -> str | None:
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.GetSystemFirmwareTable.argtypes = [wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        k.GetSystemFirmwareTable.restype = wintypes.UINT
        sig = 0x52534D42                                          # 'RSMB'
        n = k.GetSystemFirmwareTable(sig, 0, None, 0)
        if n:
            buf = ctypes.create_string_buffer(n)
            if k.GetSystemFirmwareTable(sig, 0, buf, n) == n:
                raw = buf.raw                                      # RawSMBIOSData: 4 bajty wersji, DWORD długości, tabela
                length = int.from_bytes(raw[4:8], "little")
                u = parse_smbios_uuid(raw[8:8 + length])
                if u:
                    return u
    except Exception:  # noqa: BLE001 - awaryjnie PowerShell
        pass
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID"],
                           capture_output=True, text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        v = (r.stdout or "").strip().splitlines()
        v = v[-1].strip() if v else ""
        u = uuid.UUID(v)
        return str(u).upper() if _uuid_ok(u.bytes) else None
    except Exception:  # noqa: BLE001
        return None


def _board_uuid() -> str | None:
    if sys.platform == "win32":
        return _board_uuid_windows()
    try:
        v = Path("/sys/class/dmi/id/product_uuid").read_text(encoding="ascii").strip()
        u = uuid.UUID(v)
        return str(u).upper() if _uuid_ok(u.bytes) else None
    except (OSError, ValueError):
        return None


@functools.lru_cache(maxsize=1)
def _sources() -> tuple[str | None, str | None]:
    from .edition import dev_overrides
    if dev_overrides() and os.environ.get("PMW_TEST_HWID_SOURCES"):   # testy (tylko repozytorium / wersja właściciela): "guid|uuid"
        g, _, u = os.environ["PMW_TEST_HWID_SOURCES"].partition("|")
        return g or None, u or None
    return _machine_guid(), _board_uuid()


def hwid_sources() -> dict:
    g, u = _sources()
    return {"machine_guid": bool(g), "board_uuid": bool(u)}


def get_hwid() -> str:
    """HWID tego komputera (stały – odczyt raz na proces)."""
    g, u = _sources()
    return hwid_from_sources(g, u)
