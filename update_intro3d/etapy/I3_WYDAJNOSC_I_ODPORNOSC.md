# I3 – Wydajność i odporność

Scena: 3 postacie ze skórowaniem, 2 mapy cieni, odbicie podłogi, bloom, ~10 tys. cząstek. Na zwykłej karcie graficznej to ~1–3 ms GPU; na słabym zintegrowanym GPU może być ciężej.

## Poziomy jakości (PROPOZYCJA – tylko gdy pomiar tego wymaga)
| Poziom | Kiedy | Zmiana |
|---|---|---|
| PEŁNY | domyślnie | jak wzorzec |
| ŚREDNI | średni czas klatki > 22 ms przez 1 s | `reflections:false`, DPR ≤ 1,25 |
| NISKI | nadal > 28 ms | dodatkowo `shadows:false`, DPR 1,0 |

- Poziom wybierany w pierwszych 1,5 s (w czerni – niewidoczne dla widza) i zapamiętany w `localStorage "pmw.intro.quality"`.
- **Test 1:1 zawsze na poziomie PEŁNY** (tryb testowy wymusza PEŁNY).
- Przy odtwarzaniu oś czasu idzie zegarem rzeczywistym (`dt ≤ 0,1 s` jak wzorzec), więc słaby komputer nie wydłuża animacji ponad miarę.

## Odporność
- Brak WebGL lub wyjątek przy budowie sceny → `error` → menu przechodzi do `enter` i pokazuje komunikat jak przy błędzie filmu („Nie udało się uruchomić animacji. Menu pozostaje dostępne.”).
- `webglcontextlost` w trakcie intro → to samo.
- Watchdog: jeśli `readyState !== 4` po 8 s → menu.
- Ukryta karta → pauza; powrót → wznowienie od tego samego `t`.

## Kryteria I3
- [ ] Pomiar czasu klatki w oknie Windows (WebView2) i w przeglądarce – w raporcie.
- [ ] Symulacja braku WebGL (np. flaga uruchomienia / wymuszenie wyjątku) → menu z komunikatem.
- [ ] 10× powtórka intro → stała liczba kontekstów WebGL.
