# I4 – Test 1:1 i odbiór

1. Uruchom aplikację w trybie testowym (np. `http://127.0.0.1:8000/?pmw_test=1#/menu` – strona w fazie `boot` z intro).
2. Wzorce na tym komputerze: `node update_intro3d/narzedzia/intro_1do1/wzorzec.mjs`.
3. Test:
   ```
   node update_intro3d/narzedzia/intro_1do1/porownaj.mjs --app "<adres strony testowej>"
   ```
4. Progi (`progi.json`): różne piksele (kanał > 8) ≤ 0,5 % **i** średni błąd ≤ 0,12 na kanał – w każdej z 9 klatek. Wzorzec sam ze sobą: 0. Zmiana jasności jednego światła o 11 %: błąd od klatki T04.
5. **Nie wolno** podnosić progów, zmieniać `klatki.json` ani wzorca, żeby test przeszedł. Różnica środowiska → opisz i zapytaj.
6. Nagranie całości (aplikacja i REF_C) – w raporcie.
7. Lista `spec/O1_KRYTERIA_ODBIORU.md` z wynikami. **Czekaj na „dalej”.**
