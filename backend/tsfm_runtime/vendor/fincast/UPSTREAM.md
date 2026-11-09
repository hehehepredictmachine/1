# FinCast – kod inferencji dołączony do PepeMarketWizard (1.37)

Źródło: oficjalne repozytorium https://github.com/vincent05r/FinCast-fts, commit `488b19d1d85fa2b3d4b93469530cefdcf1cc97a4`
(2026-06-22). Licencja: Apache-2.0 – pełny tekst w `LICENSE` obok.

Skopiowane BEZ ZMIAN katalogi `src/ffm/` i `src/st_moe_pytorch/` (klasa `FFmTorch`, ładowanie checkpointu
`torch.load(..., weights_only=True)` + `load_state_dict(..., strict=True)`, metoda `forecast`). Bot wywołuje wyłącznie te oryginalne
funkcje (`tsfm_runtime/engines.py`). Kod działa tylko w osobnym procesie `.venv_fincast` – katalog `vendor/fincast` jest dodawany do
`sys.path` wyłącznie w tym procesie, więc ogólne nazwy pakietów (`ffm`, `st_moe_pytorch`) nie kolidują z modułami bota.

Wagi NIE są częścią paczki: `Vincent05R/FinCast` @ `2d7d90b159db8961d27c2cf165d51195902ef92b`, plik `v1.pth`
(3 966 703 063 B, SHA-256 `d5ca999b02c944effa60d2b94174dc4d5a0cd2c0543ae289b2e36f37431492a8`) – pobiera instalator.

Sumy SHA-256 skopiowanych plików (identyczne z commitem upstream):

| Plik | SHA-256 |
|---|---|
| `LICENSE` | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |
| `ffm/__init__.py` | `d34f04310fbc42fb6a35d1b0cb033356da617a8cbbd5a3228f07e3089c379434` |
| `ffm/data_loader.py` | `cf8ec42ff3ffeff4aff67706541e31fbedaf3bbdae358cd91f6ed0c8739865ef` |
| `ffm/ffm_base.py` | `f8f63b61d2bfa3654ec915595f3fe79b20182a67e7a3ec9b4cede2e2f172601a` |
| `ffm/ffm_torch_moe.py` | `1eff27a6578be7c57d820692d111b197e458a3954c2c28d8ed86a71e987d14fa` |
| `ffm/pytorch_patched_decoder_MOE.py` | `58c8d5dfea859c87958e1b35fa2b2eb9c9a1d8bd99813be528adbdaf37c15dbe` |
| `ffm/time_features.py` | `5291e03af7ac35284b17fca36b411ef7f0a7395fb24a1435246f08abff348b08` |
| `ffm/xreg_lib.py` | `d31579a5a79560114b9d4836866bf3a210006404e0313b4fa9dbbeb55876257c` |
| `st_moe_pytorch/__init__.py` | `5d67d4f81d080199049af3217f947fa1e6de83671675e1543801995f4c602553` |
| `st_moe_pytorch/distributed.py` | `3a3742c3389be59305c3eb22e88cbaef3fcfec514687856b7b1954a3a5db129a` |
| `st_moe_pytorch/st_moe_pytorch.py` | `c38a8789120f6d5009be4fd91cce1a9d75011adb1ddb73f45060b99f0d7ae477` |
