# Mapowanie grafik monitora

| Rola | Oryginalny plik (wg zlecenia) | Co otrzymałem | Plik w aplikacji | Kadr statyczny (OFF/LIGHT) |
|---|---|---|---|---|
| **Tło całego pulpitu** (pierwszy GIF) | `4FDC48DF-6C65-4AF7-9C88-3AA720BEAEB4.gif`, 800×792, 20 klatek, ~1,40 s | **statyczny WebP 800×792, 1 klatka** – czat przekonwertował GIF przy przesyłaniu; animowanego oryginału nie otrzymałem | brak animowanej wersji w paczce (nie generuję zastępczych klatek); po wgraniu oryginału: `data/assets/masterquo/background-matrix.gif` | `frontend/public/assets/masterquo/background-matrix-static.webp` (otrzymany kadr) |
| **Tańcząca żaba obok BALANCE** (drugi GIF) | `2C98C50C-2BB4-41B6-B4E6-34C84B21BB55.gif`, 336×468, 22 klatki, ~1,54 s, przezroczystość | GIF 336×468, **22 klatki, 1540 ms, przezroczystość** – zgodny (sprawdzone parserem `media/gifinfo.py` i Pillow) | `frontend/public/assets/masterquo/frog-dance.gif` (bajt w bajt = oryginał, SHA-256 441db359…) | `frog-dance-static.png` (klatka 0, kanał alfa zachowany) |

Oryginały w paczce: `assets/masterquo/originals/` (żaba: GIF bez zmian; tło: plik w postaci otrzymanej, nazwany `…_AS_RECEIVED_STATIC.webp`).

## Jak włączyć animowane tło
Monitor → ⚙ Ustawienia → **Wygląd** → „Wgraj oryginalny GIF tła” → wybierz `4FDC48DF-6C65-4AF7-9C88-3AA720BEAEB4.gif`.
Backend sprawdza, czy to poprawny GIF (struktura bloków, liczba klatek, czas pętli), zapisuje go lokalnie w `data/assets/masterquo/`
i od razu używa w trybie FULL. Kadr statyczny dla OFF/LIGHT jest wtedy wyliczany w przeglądarce (ImageDecoder, klatka 0).

## Tryby animacji (Ustawienia → Wygląd, zapis w tej przeglądarce)
* **FULL** – animowane tło (jeśli dostępny animowany oryginał) + tańcząca żaba,
* **LIGHT** – statyczny kadr tła, żaba animowana, bez dodatkowych efektów,
* **OFF** – statyczne kadry obu grafik (rzeczywista podmiana zasobu `<img>` na kadr – nie CSS), bez animacji dekoracyjnych.
Początkowo: `prefers-reduced-motion: reduce` → OFF, inaczej FULL. Ukryta karta (Page Visibility API) → kadry statyczne; backend działa dalej,
po powrocie monitor pobiera pełny stan. Zmiana ceny nie przeładowuje GIF-ów (stały `src`, komponenty memo).
Regulacje: przyciemnienie tła 0–90%, kadrowanie poziome/pionowe (domyślnie 22%/45%, aby twarz była widoczna).
Tło: `position: fixed`, `pointer-events: none`, `object-fit: cover`, pod całym interfejsem (nie przechwytuje kliknięć, nie zmienia układu).
Żaba: zarezerwowane pole 92 px (desktop) / 80 px (≤1500 px) / 60 px (≤760 px) × proporcja 336/468, `object-fit: contain`, w jednej grupie z kartą BALANCE.
