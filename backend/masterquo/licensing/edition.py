"""Edycja programu (1.44.0).

  OWNER  – wersja właściciela: w programie jest generator licencji (licensing/owner.py). Licencja nie jest wymagana.
  CLIENT – paczka klienta (tools/build_release.py --edition client): bez generatora, wymaga ważnej licencji PMW1.
Brak generatora w programie = zawsze CLIENT. PMW_EDITION=CLIENT wymusza CLIENT (testy wersji klienta w repozytorium) – żadnej zmiennej
nie da się użyć, żeby z paczki klienta zrobić wersję właściciela.
1.46: znacznik edycji klienta (licensing/_edition.py, dopisywany przez build paczki klienta) ma pierwszeństwo przed owner.py – pusty albo
pozostawiony ze starszej instalacji plik owner.py nie zmienia paczki klienta w wersję właściciela. Uwaga: źródła Python paczki można
zmienić ręcznie – edycja chroni przed przypadkiem i prostym dopisaniem pliku, nie przed świadomą modyfikacją kodu.
"""
from __future__ import annotations

import os
from pathlib import Path

_OWNER_FILE = Path(__file__).resolve().with_name("owner.py")
# 1.46: written ONLY into the client package by the build (never in the repository / owner edition); its presence = CLIENT (fail-closed:
# the content is not parsed, an unreadable or edited marker is still a client package)
_CLIENT_MARKER = Path(__file__).resolve().with_name("_edition.py")


def _client_marked() -> bool:
    try:
        return _CLIENT_MARKER.exists()
    except OSError:
        return True


def edition() -> str:
    if os.environ.get("PMW_EDITION", "").strip().upper() == "CLIENT":
        return "CLIENT"
    if _client_marked():                    # 1.46: an (empty) owner.py added to a client package no longer switches it to OWNER
        return "CLIENT"
    return "OWNER" if _OWNER_FILE.exists() else "CLIENT"


def dev_overrides() -> bool:
    """Zmienne testowe (podmiana klucza publicznego, pliku licencji, czasu z internetu) działają tylko w repozytorium / wersji właściciela –
    w paczce klienta (bez generatora albo ze znacznikiem edycji klienta) są ignorowane."""
    return _OWNER_FILE.exists() and not _client_marked()
