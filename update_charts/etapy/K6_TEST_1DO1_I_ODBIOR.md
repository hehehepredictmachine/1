# K6 – Test 1:1 i odbiór panelu

## 1. Test pikselowy (obowiązkowy)

1. Uruchom aplikację w trybie testowym (dev server albo backend z buildem testowym) – adres ekranu CHARTS, np. `http://127.0.0.1:8000/#/forex?s=charts&pmw_test=1`.
2. Wzorce wyrenderowane na tym komputerze (K0): `node update_charts/narzedzia/charts_1do1/wzorzec_z_ref_b.mjs --tylko-wzorce`.
3. Test:
   ```
   node update_charts/narzedzia/charts_1do1/porownaj.mjs --app "<adres ekranu CHARTS w trybie testowym>"
   ```
4. Wynik: `update_charts/raport/charts_1do1/` – zrzut aplikacji, mapa różnic (czerwone piksele), `wynik.json`.
5. Progi (`progi.json`): cały ekran ≤ 0,1 % różnych pikseli **i** każdy obszar (nagłówek, wykres główny, karta planu, Kronos, stopka Kronos, zakładki, opcje, odczyt) ≤ 0,3 %. Wzorzec porównany sam ze sobą daje 0–0,02 %, a zmiana rozmiaru czcionki samego tytułu daje błąd – progi są celowo ciasne.
6. **Nie wolno** podnosić progów, dodawać masek ani zmieniać fixtures, żeby test przeszedł. Jedyna maska: znacznik źródła danych w nagłówku. Jeśli różnica wynika ze środowiska (np. inna czcionka systemowa), opisz to i zapytaj użytkownika.

## 2. Przegląd ręczny z wzorcem (zrzuty obok siebie w raporcie)

Otwórz `referencje/REF_B_kula_forex_i_ekrany.html` (kula → planeta 01) i aplikację, sprawdź interakcje, których zrzut nie obejmuje:
- przejście wejścia i wyjścia (2400 / 1500 ms), linie świecą dopiero po przejściu;
- hover: odczyt pod kursorem, sygnały danej świecy, krzyż;
- przeciąganie, kółko = zoom, 2× klik = teraz;
- klik w marker → wybór planu; zwijanie karty;
- przełączanie TF i instrumentu (płynna podmiana serii jak `CH.swap`);
- ograniczenie ruchu.

## 3. Kryteria odbioru
Cała lista `spec/O1_KRYTERIA_ODBIORU.md` z wynikiem ✅ / ❌ / ⚠️ i opisem. **Czekaj na „dalej”.**
