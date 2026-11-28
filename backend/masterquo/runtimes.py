"""Registry of the separate Python environments of the model runtimes and of the environment variables the backend reads (1.46 arch I0117).

Before 1.46 the lookup 'variable -> python_path from the settings -> <root>/.venv_X/Scripts/python.exe -> <root>/.venv_X/bin/python' was
copied into every model module (kronos/settings, tsfm/settings, quant/tabicl, modelhub/families/deep, forecast/service, training/core),
the fallback RAM budget of a training child differed between the training paths (8192 vs 6144 MB) and most variables were documented
nowhere. One registry now:

* ``ENVIRONMENTS``      name -> venv folder, overriding variable, settings key (where the user can type the interpreter path);
* ``python_candidates`` the candidate interpreters of one environment, in the SAME order as each module used before;
* ``find_python``       the first existing candidate (``check`` = the test each module used: is_file, or exists for the candles one);
* ``DEFAULT_RAM_BUDGET_MB`` the one fallback memory budget of a training child (MQ_RAM_BUDGET_MB overrides it);
* ``ENV_VARS``          every MQ_* / PMW_* process variable the backend reads or passes to its child processes, with its purpose -
                        ``env_example_section()`` renders the documented block of .env.example from it (a test keeps them equal).
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from . import paths

DEFAULT_RAM_BUDGET_MB = 8192

# name -> (venv folder under the installation root, overriding environment variable, settings key with a user-typed interpreter or None)
ENVIRONMENTS: dict[str, tuple[str, str, str | None]] = {
    "candles": (".venv_candles", "MQ_CANDLES_PYTHON", "forecast.python_path (config.json)"),
    "kronos": (".venv_kronos", "MQ_KRONOS_PYTHON", "python_path (data/kronos/settings.json)"),
    "chronos2": (".venv_chronos2", "MQ_CHRONOS2_PYTHON", "models.chronos2.python_path (data/tsfm/settings.json)"),
    "granite_ttm": (".venv_granite", "MQ_GRANITE_TTM_PYTHON", "models.granite_ttm.python_path (data/tsfm/settings.json)"),
    "tirex2": (".venv_tirex2", "MQ_TIREX2_PYTHON", "models.tirex2.python_path (data/tsfm/settings.json)"),
    "tabicl": (".venv_tabicl", "MQ_TABICL_PYTHON", None),
    "deep": (".venv_deep", "MQ_DEEP_PYTHON", None),
}


def venv_pythons(venv: str) -> list[str]:
    """The interpreter of a venv under the installation root: Windows layout first, then POSIX."""
    root = paths.ROOT_DIR
    return [str(root / venv / "Scripts" / "python.exe"), str(root / venv / "bin" / "python")]


def python_candidates(name: str, settings_path: str | None = None) -> list[str]:
    """[overriding variable, interpreter from the settings, <root>/<venv>/Scripts/python.exe, <root>/<venv>/bin/python] - empty
    entries dropped. Same order as the former per-module copies."""
    venv, var, _ = ENVIRONMENTS[name]
    return [c for c in (os.environ.get(var), settings_path, *venv_pythons(venv)) if c]


def find_python(name: str, settings_path: str | None = None, *, check: Callable[[Path], bool] = Path.is_file) -> str | None:
    """The first candidate that passes `check` (Path.is_file by default; the candles lookups used Path.exists), or None."""
    return next((c for c in python_candidates(name, settings_path) if check(Path(c))), None)


# MQ_* / PMW_* process variables (NOT read from the .env file - _load_dotenv in __main__.py accepts only the keys listed above them in
# .env.example). Set them in the system / launcher environment. name -> purpose.
ENV_VARS: dict[str, str] = {
    **{var: f"interpreter środowiska {venv} (zamiast wyszukiwania; patrz runtimes.ENVIRONMENTS)" for venv, var, _ in ENVIRONMENTS.values()},
    "MQ_SDF_PYTHON": "interpreter z torch dla SDformerFlow, gdy żadne środowisko modeli go nie ma",
    "MQ_RAM_BUDGET_MB": f"budżet pamięci jednego procesu treningu w MB (domyślnie {DEFAULT_RAM_BUDGET_MB})",
    "MQ_MT5_FILES_DIR": "folder MQL5\\Files terminala MT5 (wskaźniki natywne, MiniRocket, kontekst przepływu)",
    "MQ_MINIROCKET_EXPORT_DIR": "folder eksportu MiniRocket (domyślnie <instalacja>/exports/minirocket)",
    "MQ_EXTIND_INBOX": "dodatkowy folder skrzynki wskaźników zewnętrznych",
    "MQ_INSTRUMENT": "instrument procesu potomnego treningu / inferencji (ustawia bot)",
    "MQ_STUDIO_DATA_DIR": "folder danych Studio (ustawia bot przy uruchamianiu PepeTrainingStudio)",
    "MQ_BOT_DATA_DIR": "folder danych bota widziany ze Studio (ustawia bot przy uruchamianiu Studio)",
    "MQ_NO_BROWSER": "1 = raport treningu nie otwiera przeglądarki (ustawia bot dla procesów potomnych)",
    "MQ_NO_PAUSE": "1 = proces potomny treningu nie czeka na klawisz (ustawia bot)",
    "MQ_TRAINING": "1 = proces treningu Centrum TH (ustawia bot)",
    "MQ_BASKETS_OFFLINE": "1 = koszyki bez zapytań do Hyperliquid (testy)",
    "MQ_FAKE_MARKET_ALWAYS_OPEN": "1 = symulator MT5 nie zamyka rynku w weekend (testy / models check)",
    "MQ_FORECAST_TEST_ALLOW_SYNTHETIC": "1 = test prognoz dopuszcza dane syntetyczne (tylko obszar models check)",
    "MQ_KRONOS_ALLOW_FIXTURE": "1 = środowisko Kronos przyjmuje atrapę wag (testy)",
    "MQ_TSFM_ALLOW_FIXTURE": "1 = środowiska TSFM przyjmują atrapę wag (testy)",
    "PMW_BOOTSTRAP": "0 = bez automatycznej instalacji środowisk przy starcie",
    "PMW_HOME": "folder domowy aplikacji Windows (dane: <PMW_HOME>/data; ustawia powłoka)",
    "PMW_DESKTOP": "1 = backend uruchomiony przez powłokę Windows (ustawia powłoka)",
    "PMW_DESKTOP_EXE": "ścieżka PepeMarketWizardDesktop.exe (ustawia powłoka)",
    "PMW_EDITION": "CLIENT = wymuszenie edycji klienta",
    "PMW_FAMILIES_DIR": "folder rodzin modeli (domyślnie <dane>/model_families; models check)",
    "PMW_TIREX_COMPILE": "1 = kompilacja TiRex-2 (torch.compile) w środowisku TSFM",
    "PMW_OWNER_DIR": "folder właściciela licencji (testy)",
    "PMW_LICENSE_FILE": "plik licencji (tylko wersja deweloperska, testy)",
    "PMW_TEST_HWID_SOURCES": "źródła identyfikatora sprzętu „guid|uuid” (tylko testy)",
    "PMW_TEST_NET_OFFSET": "przesunięcie czasu sieciowego / none (tylko testy)",
    "PMW_TEST_PUBLIC_KEY_HEX": "klucz publiczny wydawcy licencji (tylko testy repozytorium)",
}

ENV_EXAMPLE_BEGIN = "# --- Zmienne środowiskowe procesu (NIE z pliku .env) - generowane z backend/masterquo/runtimes.py ---"
ENV_EXAMPLE_END = "# --- koniec listy z runtimes.py ---"


def env_example_section() -> str:
    """The documented block of .env.example (commented lines only - _load_dotenv never reads them)."""
    lines = [ENV_EXAMPLE_BEGIN,
             "# Te zmienne bot czyta ze środowiska systemu / launchera, nie z tego pliku. Nieustawione = zachowanie domyślne."]
    lines += [f"# {k}: {v}" for k, v in sorted(ENV_VARS.items())]   # no "=": not a .env entry (I0118 keeps KEY= for DOTENV_VARS only)
    lines.append(ENV_EXAMPLE_END)
    return "\n".join(lines) + "\n"
