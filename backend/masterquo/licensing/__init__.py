"""Licencje offline PMW1 (1.43.0): klucze podpisane Ed25519, HWID komputera, generator właściciela.

  hwid.py         get_hwid() – MachineGuid + UUID płyty głównej -> SHA-256 -> XXXXX-XXXXX-XXXXX-XXXXX
  license_key.py  format klucza "PMW1-…", podpis i odczyt (weryfikacja potrzebuje tylko klucza publicznego)
  owner.py        generator właściciela: para kluczy poza folderem programu, historia (SQLite), sprawdzanie kluczy
Ten moduł niczego nie blokuje w bocie – sprawdzanie licencji po stronie klienta to osobny, późniejszy krok.
"""
