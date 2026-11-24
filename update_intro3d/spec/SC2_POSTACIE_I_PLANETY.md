# SC2 – Postacie i planety

## 1. Postacie (`figure2.js`, `tools/build_body.mjs`, `motion.js`)

**Bryła ludzka w garniturze** wygenerowana z pola odległości (SDF: 56 gładko łączonych brył anatomicznych i elementów ubioru) metodą Surface Nets (krok 5,5 mm), z rzutem wierzchołków na powierzchnię i normalnymi z gradientu pola. Wynik: `body.bin.gz` (~96 tys. wierzchołków, ~192 tys. trójkątów, 1,5 MB) + `skeleton.json`. Jedna bryła dla trzech postaci (różnią się skalą i kolorem kominiarki).

| Strefa | Materiał |
|---|---|
| marynarka (watowane barki, poła, klapy z satyny), spodnie | wełna – `MeshPhysicalMaterial`, połysk tkaniny, normalne tkaniny |
| koszula (wycięcie V, kołnierzyk, mankiety) | jasna bawełna |
| krawat (węzeł + pas) | czarny jedwab |
| rękawice | czarna skóra |
| buty (oxford, płaska podeszwa) | lakierowana skóra |
| kominiarka | dzianina: **czerwona** (środkowa), czarna (boczne); szczelina na oczy z widoczną skórą i oczami (kule na kości głowy) |

Szkielet 18 kości, poza spoczynkowa z ramionami odwiedzonymi o 0,17 rad; wagi kości z odległości do brył przypisanych kościom (płynne przejścia na stawach).

| Kość | Rodzic | | Kość | Rodzic |
|---|---|---|---|---|
| root | – | | upperArm_L/R | chest |
| hips | root | | foreArm_L/R | upperArm |
| spine | hips | | hand_L/R | foreArm |
| chest | spine | | upLeg_L/R | hips |
| neck | chest | | leg_L/R | upLeg |
| head | neck | | foot_L/R | leg |

**Chód** wg wzoru od użytkownika (`referencje/wzor_chodu_od_uzytkownika.gif`): ~1,85 kroku/s, kołysanie i skręt bioder, wymach rąk ~0,34 rad z **wyraźnie zgiętym łokciem przy wymachu w przód**, tułów w kontrze. Po zatrzymaniu: oddech i przenoszenie ciężaru. Sięgnięcie: IK CCD prawej ręki, dłoń ustawiana z kierunków spoczynkowych (wnętrze w dół, palce od ciała).

PROPOZYCJA na później (nie w tej aktualizacji): podmiana bryły na profesjonalne modele `.glb` z riggiem – jedynym miejscem do zmiany jest `createFigure()`.

## 2. Planety (`planets.js`)

Trzy rzeźby z cząstek (`Points`, shader addytywny, test głębi włączony – dłoń zasłania planety):

| Planeta | Kształt | Kolor |
|---|---|---|
| FOREX | kula 2200 cząstek, pierścień nachylony 0,3, 4 księżyce | zimny błękit `(.62,.74,1)` |
| CRYPTO | siatka bloków w kuli + łańcuch 20 bloków | fiolet `(.74,.68,1)` |
| OTC | rdzeń 0,56 R + 9 południków + równik | ciepła biel `(1,.95,.88)` |

Promień 0,046 m. Składanie z rozproszenia (`uK`), obrót, puls przy dotyku (`uPulse`), poświata (sprite), światło punktowe pod spodem, pierścień fali po dotyku.
