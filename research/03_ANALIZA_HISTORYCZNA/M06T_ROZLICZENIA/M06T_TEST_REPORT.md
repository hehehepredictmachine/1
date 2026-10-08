# M06T — raport z audytu technicznego

Weryfikowany zakres: mapowanie M06R → referencyjny M06, dostępność informacji w czasie, rejestrowanie ex ante parametrów, przeliczenie kosztów, OOS, kontrola luk ticków, zgodność wyliczeń z niezmienionym M06, archiwum M06H oraz CLI na danych syntetycznych.

Testy są uruchamiane `py -3 -m unittest M06T_TESTS -v`. Demonstracja w `examples/SYNTHETIC_ONLY` zawiera fikcyjne ticki XAUUSD, fikcyjne setupy i scenariuszowe koszty. Test demonstracyjny nie potwierdza skuteczności handlowej.

**Nieprzetestowane:** Windows / rzeczywisty terminal MT5 DEMO, historyczne ticki realnego brokera, prawdziwa prowizja Zero i koszty swap, realna ścieżka osiągalności Entry/SL/TP, kompletność kalendarzy FF/MM/BLS, forward DEMO, trwałość rynkowa strategii na OOS.

Założenia eksperymentu nie są obietnicą skuteczności. Parametry handlowe przykładu mają wyłącznie charakter testowy. Prawdziwy backtest powinien być liczony na rzeczywistej, audytowalnej historii brokera, z wyłączonymi danymi przyszłymi i nieprzekraczalnymi granicami prób.

## Ostateczny test integracji

- `M06T_TESTS.py`: 64 testy offline PASS (pełny łańcuch, wiadomości, parytet oryginalnego M06, koszt i brak fałszywej autoryzacji).
- `M06H_TESTS.py` z wcześniejszego, zachowanego M06H: 76 testów offline PASS osobno, bez zmian silnika.
- Przykładowe dwa hipotetyczne rozliczenia stanowią wyłącznie syntetyczny fixture, nie mają znaczenia inwestycyjnego.
- Wynik makro z kalendarza wyłącznie syntetycznego: NOT_RUN.
