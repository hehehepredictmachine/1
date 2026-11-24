"""Konfiguracja licencji wersji KLIENTA (1.44.0).

PUBLIC_KEY_HEX – klucz PUBLICZNY wydawcy licencji (64 znaki 0-9 a-f). Skąd go wziąć: wersja właściciela → panel systemowy →
zakładka „Generator licencji” → „Klucz publiczny (hex)” → Kopiuj, i wklej poniżej między cudzysłowy.

* Pusty klucz: paczka klienta się NIE zbuduje (tools/build_release.py --edition client podaje czytelny błąd), a uruchomiona wersja
  klienta pokaże błąd konfiguracji licencji zamiast ekranu aktywacji.
* To klucz publiczny – może być w paczce klienta. Klucza PRYWATNEGO (plik private.key) nigdy tu nie wklejaj; build sprawdza, czy wpis nie
  jest kluczem prywatnym z folderu właściciela na tym komputerze.
* Zmiana klucza = wszystkie licencje wydane poprzednim kluczem przestają działać w nowej paczce.
"""

PUBLIC_KEY_HEX = "9e83abb1659c063ffab4eb039910311a286398b5b87dfb26feec00a8336e5bba"
