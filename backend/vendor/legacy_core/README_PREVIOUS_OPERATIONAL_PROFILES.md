# MasterQUO — M07/M03E Operational Strategy Profiles v1.0.0

**Najpierw przeczytaj [README_OPERATIONAL_PROFILES.md](README_OPERATIONAL_PROFILES.md).**

Nowy etap: automatyczne przypisywanie istniejących dowodów M02/M03 do trzech badawczych profili (MVP/SMC/SCALPING) i przepływ M10A→M14→M15. Archiwum zachowuje wcześniejszą integrację M01–M15 oraz jej regresję. Własne skrypty tego etapu zaczynają się od `M07_M03E_` albo `RUN_MT5_OPERATIONAL_PROFILES_READONLY.py`.

Domyślny start Windows: `START_OPERATIONAL_PROFILES_AUTO_READONLY.bat`. Tryby: `--mode MVP|SMC|SCALPING|AUTO`. Python: `py -3 RUN_MT5_OPERATIONAL_PROFILES_READONLY.py --mode AUTO --symbol XAUUSD`.

Konto: MT5 Zero (zadeklarowany, koszty nieweryfikowane). Sygnały: badawcze, brak sprawdzonej przewagi. Rynek: MT5 PRIMARY, TradingView SUPPLEMENTAL, zero screenshotów. **Wysyłanie zleceń zawsze wyłączone.**

Testy: `py -3 RUN_ALL_OPERATIONAL_PROFILE_TESTS.py` (85 nowych); z pełną regresją: `py -3 RUN_ALL_OPERATIONAL_PROFILE_TESTS.py --with-regression` (dodatkowo 794 dotychczasowe).
