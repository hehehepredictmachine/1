# Weryfikacja programu

29 testów unittest: PASS. Ostatni pełny przebieg: 6.135 s.

Sprawdzono przyczynowość cech, zamknięcie świec, UTC, geometrię OHLC,
pełne M30, luki, symetrię formacji, chronologiczne purge, eksport JSON
i odmowę wykonania bez pełnej integracji strategii.

Model w testach używa wyłącznie danych SYNTHETIC_TEST. Nie ma treningu
na danych brokera, testu terminala Windows ani backtestu rentowności.

Wersje: Python 3.12.14, NumPy 2.3.5, pandas 2.2.3, scikit-learn 1.8.0.

Polecenie: python3 -m unittest discover -s tests -v
