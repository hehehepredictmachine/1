# Referencje
- `REF_C_intro_3d_i_menu.html` – intro 3D + menu główne v1.2 (offline). „PRZEJDŹ DO MENU” pomija intro, ikona ⟲ odtwarza je ponownie. Hak przeglądu: `PMW_PREVIEW.intro` (obiekt Intro3D: `pause()`, `currentTime = t`).
- `kod/intro3d/src/` – źródła wzorca: `intro.js` (scena, oś czasu, światła, kamera, postprocessing), `figure2.js` (postacie w garniturach), `motion.js` (chód, IK), `planets.js`, `galaxy.js`, `textures.js`, `assets/body.bin.gz` + `skeleton.json`.
- `kod/intro3d/tools/build_body.mjs` – generator bryły (SDF → Surface Nets): `node tools/build_body.mjs 0.0055`.
- `kod/intro3d/package.wzorzec.json` – wersje (three 0.187.0, fflate 0.8.2, isosurface 1.0.0, esbuild 0.28.2); bundel: `build.sh`.
- `wzor_chodu_od_uzytkownika.gif` – wzór chodu.
- `zrzuty/00_storyboard.png` – 9 klatek kluczowych; pełne klatki 1280×720: `narzedzia/intro_1do1/wzorce/`.
