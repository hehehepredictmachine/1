# Karta sygnału i checklista (monitor 1.7.1)

## Jak czytać kartę (w kilka sekund)
| Napis | Kolor | Znaczenie | Co robić |
|---|---|---|---|
| **BUY** | zielony | aktualny, potwierdzony sygnał **otwarcia LONG** – przeszedł reguły strategii i decyzji | wejście / SL / TP / RR są na karcie |
| **SELL** | czerwony | aktualny, potwierdzony sygnał **otwarcia SHORT** (nigdy sprzedaż zamykająca LONG) | jw. |
| **OCZEKIWANIE** + „Plan: BUY/SELL” | bursztynowy | setup w przygotowaniu | sprawdź „Do potwierdzenia brakuje: …” – nie wchodzić |
| **BRAK SYGNAŁU** | neutralny | żadna strategia nie ma zakwalifikowanego setupu | lista „dlaczego” pod opisem |
| **BLOKADA** | czerwona ramka | setup potwierdzony, ale wejście zablokowane | „Powód blokady” |
| **NIEAKTUALNY** | neutralny | wygasł albo unieważniony | nie wchodzić |
| **BRAK DANYCH** | neutralny | brak aktualnych danych lub połączenia | sprawdź MT5 / połączenie |

* **WEJŚCIE** – przy BUY/SELL planowana cena rynkowa (Ask dla BUY, Bid dla SELL) w chwili potwierdzenia; przy OCZEKIWANIU poziom
  wyzwalacza („wejście dopiero po potwierdzeniu”). **Wykonanie** pokazuje fill dopiero po potwierdzonej transakcji.
* **SL** – stop loss, **TP** – take profit (dla S11 liczony od ceny wejścia), **RR** – stosunek zysku do ryzyka po kosztach
  (w nawiasie brutto). Najedź na nazwę, żeby zobaczyć objaśnienie.
* **Kopiuj plan** – kierunek, symbol, wejście, SL, TP, RR, ważność i identyfikator sygnału – te same wartości co na karcie.
* Źródło: **STRATEGIA** albo **STRATEGIA + AI** (tylko przy aktualnej ocenie AI tego samego stanu setupu). „AI NIEDOSTĘPNE” bez klucza.
  Procent prawdopodobieństwa – tylko z walidowanego modelu ML (w „Szczegóły”), inaczej „—”.

## Skąd dane
Silnik → `engine/signal_contract.py` (sygnał) → `engine/signal_view.py` (model karty) → zdarzenie `decision` (WebSocket) → monitor
(`frontend/src/components/SignalTop.tsx`). Karta, checklista i uzasadnienie pochodzą z tej samej decyzji (snapshot / decyzja / sygnał –
widoczne w „Szczegóły”). Monitor nigdy nie podnosi stanu; obniża go, gdy upłynie ważność, zniknie połączenie albo decyzja jest
starsza niż 2 minuty.

## Uruchomienie i sprawdzenie
* Start: `masterquo_start.bat` – karta jest na górze monitora `http://127.0.0.1:8765/`.
* Testy: `05_TESTY_OFFLINE.bat` – m.in. `tests/test_signal_view.py` (model karty) i `tests/test_ui_signal_card.py`
  (prawdziwy monitor w Chromium: BUY, SELL, oczekiwanie, brak sygnału, blokada, brak danych, AI niedostępne, spóźniona odpowiedź AI,
  wygaśnięcie, reconnect, kopiowanie, rozmiary okna). Zrzuty: `data\logs\ui_signal_card\`.
