"""Licencje offline PMW1 (1.43.0 / 1.44.0): klucze podpisane Ed25519, HWID komputera.

  hwid.py           get_hwid() – MachineGuid + UUID płyty głównej -> SHA-256 -> XXXXX-XXXXX-XXXXX-XXXXX (to samo w obu edycjach)
  license_key.py    format klucza "PMW1-…": odczyt i weryfikacja (wystarczy klucz publiczny)
  edition.py        edycja programu: OWNER (wersja właściciela) / CLIENT (paczka klienta – wymaga licencji)
  client_config.py  PUBLIC_KEY_HEX – klucz publiczny wydawcy (wersja klienta)
  nettime.py        czas z internetu (nagłówek Date HTTPS) do sprawdzania wygaśnięcia
  gate.py           CENTRALNA kontrola licencji: start, przed trybem, bramka wykonania, API, co 10 min
Wersja właściciela ma dodatkowo wydawanie kluczy i historię – tych plików nie ma w paczce klienta.
"""
