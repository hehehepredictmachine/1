# MasterQUO M04N v1.1.0 — rejestr zmian i audyt

**Status CANDIDATE / READ-ONLY.** Źródła: Forex Factory (`FF_CALENDAR`) i Metals Mine (`MM_CALENDAR`), poprzez publiczne, tygodniowe eksporty JSON na `nfs.faireconomy.media`.

Zmiany: osobny parser danych z walidacją TZ, filtering USD/CNY/metals, stabilne klucze wydarzeń; trwałe magazynowanie w SQLite; źródła i statusy health; 30-minutowy polling i backoff; pomijanie nieaktualnych kalendarzy; deduplikacja między portalami i zachowanie pochodzenia; rozszerzenie eksportu do M04; uaktualnienie podglądu i dokumentacji. Brak połączeń do prywatnych API; brak pobierania HTML news i składania zleceń.

Przepływ testowany na syntetycznych próbkach JSON, błędnych danych i symulowanych błędach HTTP. Rezultat w `M04N_AUDIT_CHANGELOG_TEST_REPORT.md` nie oznacza gwarantowanego dostępu z terminala użytkownika. Prawdziwa dostępność endpointów w Windows: NOT TESTED.
