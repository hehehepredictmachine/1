"""Edycja programu (1.44.0).

  OWNER  – wersja właściciela: w programie jest generator licencji (licensing/owner.py). Licencja nie jest wymagana.
  CLIENT – paczka klienta (tools/build_release.py --edition client): bez generatora, wymaga ważnej licencji PMW1.
Brak generatora w programie = zawsze CLIENT. PMW_EDITION=CLIENT wymusza CLIENT (testy wersji klienta w repozytorium) – żadnej zmiennej
nie da się użyć, żeby z paczki klienta zrobić wersję właściciela.
"""
from __future__ import annotations

import os
from pathlib import Path

_OWNER_FILE = Path(__file__).resolve().with_name("owner.py")


def edition() -> str:
    if os.environ.get("PMW_EDITION", "").strip().upper() == "CLIENT":
        return "CLIENT"
    return "OWNER" if _OWNER_FILE.exists() else "CLIENT"


def dev_overrides() -> bool:
    """Zmienne testowe (podmiana klucza publicznego, pliku licencji, czasu z internetu) działają tylko w repozytorium / wersji właściciela –
    w paczce klienta (bez generatora) są ignorowane."""
    return _OWNER_FILE.exists()
