# Lista funkcji do zachowania – Etap 0.4 (Apollo23 1.46.0)

Wygenerowano skryptem `/tmp/claude-0/-home-user-1/faeab58a-3892-539a-94b1-90536dda312a/scratchpad/arch/fl/run_all.sh` → `gen_funkcje.py` z BIEŻĄCEGO kodu (`git log -1`: 0342136 Etap 0: punkt odniesienia - pełny output poleceń i wersja robocza raportu). Dokumenty projektu nie były źródłem – wyłącznie parsery argparse, dekoratory FastAPI, router.ts i pliki .bat.

## Liczby

| pozycja | liczba |
|---|---|
| CLI: polecenia głównego parsera (A.1) | 29 |
| CLI: grupy modułowe (A.2) | 15 |
| CLI: podpolecenia grup modułowych (A.2, studio liczone jako 1) | 116 |
| Inne punkty wejścia python -m (A.3) | 23 |
| Skrypty tools/*.py (A.4) | 28 |
| API: trasy (AST, wszystkie pliki api/*.py) | 520 |
| API: trasy aktywne w edycji klienta (runtime) | 511 |
| API: metody | {'GET': 289, 'POST': 199, 'PUT': 19, 'PATCH': 3, 'DELETE': 9, 'WS': 1} |
| API: trasy /api/* bez żadnego odwołania w repo | 203 |
| API: trasy /api/* używane tylko przez testy | 90 |
| API: ścieżki używane przez panel (frontend/src) | 128 |
| Panel: wywołania API w kodzie frontendu / niedopasowane do backendu | 145 / 0 |
| API Studio: trasy | 10 |
| Panel: trasy główne | 4 |
| Panel: ekrany FOREX | 4 |
| Panel: panele systemowe | 6 |
| Panel: przekierowania legacy | 53 |
| Skrypty .bat w katalogu głównym | 48 |
| Wywołania w .bat/.cmd sprawdzone parserem / błędne | 118 / 0 |
| Trening: zadania runnera (TASKS) | 20 |
| Trening: jednostki Centrum Pepe (PIPELINE+EXTRA) | 20 |
| Trening: zadania katalogu Studio | 74 |
| Trening: rodziny modeli (families) | 16 |
| Trening: rodzaje zadań SI / MM graph / trainhub KINDS | 14 / 16 / 5 |
| Eksportery w rejestrze exports/ | 15 |
| Replaye: podpolecenia CLI | 6 |
| Walidacje/oceny/diagnostyka: podpolecenia CLI / trasy API | 37 / 26 |
| Wewnętrzne wywołania podprocesów CLI | 30 |

## A. CLI – `python -m masterquo <polecenie>`

Źródło: parsery argparse przechwycone w czasie wykonania (parse_args podmienione – nic nie jest uruchamiane); `*` = argument wymagany, `{a|b}` = dozwolone wartości.

### A.1 Polecenia argparse głównego parsera (`backend/masterquo/__main__.py`)

| polecenie | argumenty | definicja | obsługa |
|---|---|---|---|
| `serve` | --demo --no-browser | backend/masterquo/__main__.py:300 | backend/masterquo/__main__.py:358 |
| `stop` |  | backend/masterquo/__main__.py:303 | backend/masterquo/__main__.py:360 |
| `doctor` |  | backend/masterquo/__main__.py:304 | backend/masterquo/__main__.py:363 |
| `clock` |  | backend/masterquo/__main__.py:305 | backend/masterquo/__main__.py:365 |
| `set-key` |  | backend/masterquo/__main__.py:306 | backend/masterquo/__main__.py:367 |
| `profile` | name{ACTIVE|ORIGINAL|show} | backend/masterquo/__main__.py:307 | backend/masterquo/__main__.py:371 |
| `export` | --from-utc* --to-utc* --out --dst-model{UNIFORM|NY_CLOSE} | backend/masterquo/__main__.py:309 | backend/masterquo/__main__.py:369 |
| `export-candles` | --months --out --dst-model{AUTO|UNIFORM|NY_CLOSE} --from --to --ticks-days | backend/masterquo/__main__.py:315 | backend/masterquo/__main__.py:373 |
| `export-scalp` | --months --out --dst-model{AUTO|UNIFORM|NY_CLOSE} --from --to --ticks-days | backend/masterquo/__main__.py:322 | backend/masterquo/__main__.py:376 |
| `scalp-replay` | --history --commission-per-lot-side --slippage-ticks --cost-stress --margin-mode{HEDGING|NETTING} --variants | backend/masterquo/__main__.py:329 | backend/masterquo/__main__.py:379 |
| `train-all` | --months --scalp-months --commission --commission-btc --instruments --ml-days --lab-bars --min-events --mt5-wait --ml-no-approx --skip-candles --skip-ml --skip-lab --quick --demo | backend/masterquo/__main__.py:336 | backend/masterquo/__main__.py:384 |
| `import-iv` | file | backend/masterquo/__main__.py:352 | backend/masterquo/__main__.py:382 |
| `export-orderflow` | --out --format{csv|jsonl|both} --market --instrument --row --tf-seconds --refresh{true|false} | backend/masterquo/exports/cli.py:28 + registry.py:86 | backend/masterquo/__main__.py:391 |
| `export-market-candles` | --out --format{csv|jsonl|both} --market --instruments --timeframes --n | backend/masterquo/exports/cli.py:28 + registry.py:91 | backend/masterquo/__main__.py:391 |
| `export-fomo-universe` | --out --format{csv|jsonl|both} | backend/masterquo/exports/cli.py:28 + registry.py:95 | backend/masterquo/__main__.py:391 |
| `export-strategy-roi` | --out --format{csv|jsonl|both} | backend/masterquo/exports/cli.py:28 + registry.py:96 | backend/masterquo/__main__.py:391 |
| `export-sfb-snapshots` | --out --format{csv|jsonl|both} | backend/masterquo/exports/cli.py:28 + registry.py:97 | backend/masterquo/__main__.py:391 |
| `export-asge-trials` | --out --format{csv|jsonl|both} | backend/masterquo/exports/cli.py:28 + registry.py:98 | backend/masterquo/__main__.py:391 |
| `export-change-points` | --out --format{csv|jsonl|both} --timeframe --lookback --min-segment --sensitivity{true|false} | backend/masterquo/exports/cli.py:28 + registry.py:99 | backend/masterquo/__main__.py:391 |
| `export-long-horizon` | --out --format{csv|jsonl|both} --timeframe --horizons | backend/masterquo/exports/cli.py:28 + registry.py:102 | backend/masterquo/__main__.py:391 |
| `export-association-rules` | --out --format{csv|jsonl|both} --timeframe --horizon | backend/masterquo/exports/cli.py:28 + registry.py:104 | backend/masterquo/__main__.py:391 |
| `export-pt-skill` | --out --format{csv|jsonl|both} | backend/masterquo/exports/cli.py:28 + registry.py:106 | backend/masterquo/__main__.py:391 |
| `export-dt-ranker` | --out --format{csv|jsonl|both} | backend/masterquo/exports/cli.py:28 + registry.py:108 | backend/masterquo/__main__.py:391 |
| `export-telegram-center` | --out --format{csv|jsonl|both} | backend/masterquo/exports/cli.py:28 + registry.py:110 | backend/masterquo/__main__.py:391 |
| `export-trader-life-game` | --out --format{csv|jsonl|both} | backend/masterquo/exports/cli.py:28 + registry.py:111 | backend/masterquo/__main__.py:391 |
| `export-bootstrap` | --out --format{csv|jsonl|both} | backend/masterquo/exports/cli.py:28 + registry.py:113 | backend/masterquo/__main__.py:391 |
| `export-store-tables` | --out --format{csv|jsonl|both} --store --tables | backend/masterquo/exports/cli.py:28 + registry.py:114 | backend/masterquo/__main__.py:391 |
| `export-list` |  | backend/masterquo/exports/cli.py:37 | backend/masterquo/__main__.py:387 |
| `import-trader-life-game` | --from* --dry-run | backend/masterquo/exports/cli.py:38 | backend/masterquo/__main__.py:389 |

### A.2 CLI modułów (rozdzielane w `main()` przed argparse – `backend/masterquo/__main__.py:234-297`)

#### `masterquo context-indicators` – masterquo/lab/context_ind/cli.py (rozdzielenie: __main__.py:236)

| podpolecenie | argumenty | definicja |
|---|---|---|
| `audit` | --asset{XAUUSD|BTC} --dataset --allow-synthetic-fixture | backend/masterquo/lab/context_ind/cli.py:85 |
| `calibrate` | --asset{XAUUSD|BTC} --dataset --allow-synthetic-fixture | backend/masterquo/lab/context_ind/cli.py:85 |
| `replay` | --asset{XAUUSD|BTC} --dataset --allow-synthetic-fixture | backend/masterquo/lab/context_ind/cli.py:85 |
| `dataset` | --asset{XAUUSD|BTC} --dataset --allow-synthetic-fixture | backend/masterquo/lab/context_ind/cli.py:85 |
| `train` | --asset{XAUUSD|BTC} --dataset --allow-synthetic-fixture --families --profile{standard|quick} | backend/masterquo/lab/context_ind/cli.py:87 |
| `pipeline` | --asset{XAUUSD|BTC} --dataset --allow-synthetic-fixture --profile{standard|quick} --families --out | backend/masterquo/lab/context_ind/cli.py:91 |
| `buffers-verify` | --report* --mapping | backend/masterquo/lab/context_ind/cli.py:96 |
| `export-fixture` | --out --files-dir | backend/masterquo/lab/context_ind/cli.py:99 |
| `native-parity` | --fixtures --native-status-file --export | backend/masterquo/lab/context_ind/cli.py:102 |

#### `masterquo flow-context` – masterquo/lab/flow_context/cli.py (rozdzielenie: __main__.py:240)

| podpolecenie | argumenty | definicja |
|---|---|---|
| `audit` | --asset{XAUUSD|BTC} --symbol --source{bridge|import} | backend/masterquo/lab/flow_context/cli.py:45 |
| `export` | --asset{XAUUSD|BTC} --symbol --months --source{bridge|import} | backend/masterquo/lab/flow_context/cli.py:49 |
| `calibrate` | --asset{XAUUSD|BTC} --latest --dataset --allow-synthetic-fixture --modules | backend/masterquo/lab/flow_context/cli.py:54 |
| `train-markov` | --asset{XAUUSD|BTC} --latest --dataset --allow-synthetic-fixture --models | backend/masterquo/lab/flow_context/cli.py:57 |
| `dataset` | --asset{XAUUSD|BTC} --latest --dataset --allow-synthetic-fixture --task | backend/masterquo/lab/flow_context/cli.py:60 |
| `train` | --asset{XAUUSD|BTC} --latest --dataset --allow-synthetic-fixture --task --families --profile{standard|quick} --no-ablation --out | backend/masterquo/lab/flow_context/cli.py:63 |
| `replay` | --asset{XAUUSD|BTC} --latest --dataset --allow-synthetic-fixture --mode{shadow} | backend/masterquo/lab/flow_context/cli.py:70 |
| `native-parity` | --fixtures --native-status-file | backend/masterquo/lab/flow_context/cli.py:73 |
| `benchmark` | --profile{cpu} | backend/masterquo/lab/flow_context/cli.py:76 |
| `report` | --asset{XAUUSD|BTC} --latest --dataset --allow-synthetic-fixture --run | backend/masterquo/lab/flow_context/cli.py:78 |
| `evaluate-holdout` | --asset{XAUUSD|BTC} --candidate-id* --protocol-id* | backend/masterquo/lab/flow_context/cli.py:81 |
| `select` | --asset{XAUUSD|BTC} --candidate-id* | backend/masterquo/lab/flow_context/cli.py:85 |
| `rollback` | --asset{XAUUSD|BTC} | backend/masterquo/lab/flow_context/cli.py:88 |
| `pipeline` | --asset{XAUUSD|BTC} --dataset --allow-synthetic-fixture --profile{standard|quick} --out | backend/masterquo/lab/flow_context/cli.py:90 |

#### `masterquo structure-intelligence` – masterquo/lab/structure_cli.py (rozdzielenie: __main__.py:244)

| podpolecenie | argumenty | definicja |
|---|---|---|
| `audit` | --asset{XAUUSD|BTC} --symbol --source{bridge|import} | backend/masterquo/lab/structure_cli.py:24 |
| `export` | --asset{XAUUSD|BTC} --symbol --months --source{bridge|import} --path | backend/masterquo/lab/structure_cli.py:28 |
| `dataset` | --asset{XAUUSD|BTC} --latest --dataset --task{STRUCTURE_MOVE_M1_V1|SCALP_STRUCTURE_CONTEXT_V1} --commission --allow-synthetic-fixture | backend/masterquo/lab/structure_cli.py:34 |
| `calibrate-indicators` | --asset{XAUUSD|BTC} --latest --profiles --dataset | backend/masterquo/lab/structure_cli.py:41 |
| `train` | --asset{XAUUSD|BTC} --latest --task{STRUCTURE_MOVE_M1_V1|SCALP_STRUCTURE_CONTEXT_V1} --families --profile{standard|quick} --experiment{MQ_NEUTRAL_REACTION_V1|MQ_QUOTE_CONTEXT_REACTION_V1} --sew-operators --encoder{BAR_EVENT_V1|QUOTE_EVENT_V1} --attention{LINEAR|SLIDING|HYBRID} --transform --out | backend/masterquo/lab/structure_cli.py:46 |
| `minirocket` | action{export-native|export-fixture|parity|native-status} --asset{XAUUSD|BTC} --model-id --output --fixtures --reference-version --reference-python --native-scores --native-status-file | backend/masterquo/lab/structure_cli.py:58 |
| `benchmark` | --families --profile{cpu} --out | backend/masterquo/lab/structure_cli.py:68 |
| `neutralize` | --asset{XAUUSD|BTC} --latest --signal{ROC20} --profile | backend/masterquo/lab/structure_cli.py:72 |
| `tick-export` | --asset{XAUUSD|BTC} --symbol --days --source{bridge|import} --path | backend/masterquo/lab/structure_cli.py:77 |
| `tick-replay` | --asset{XAUUSD|BTC} --latest --profile --tick-size --point | backend/masterquo/lab/structure_cli.py:83 |
| `report` | --asset{XAUUSD|BTC} --latest --run | backend/masterquo/lab/structure_cli.py:89 |
| `replay` | --asset{XAUUSD|BTC} --latest --run --mode{shadow} | backend/masterquo/lab/structure_cli.py:89 |
| `evaluate-holdout` | --asset{XAUUSD|BTC} --candidate-id* --protocol-id* | backend/masterquo/lab/structure_cli.py:96 |
| `select` | --asset{XAUUSD|BTC} --candidate-id* | backend/masterquo/lab/structure_cli.py:100 |
| `rollback` | --asset{XAUUSD|BTC} --task | backend/masterquo/lab/structure_cli.py:103 |
| `pipeline` | --asset{XAUUSD|BTC} --dataset --profile{standard|quick} --commission --allow-synthetic-fixture --out | backend/masterquo/lab/structure_cli.py:106 |

#### `masterquo liquidity` – masterquo/analytics/liquidity_cli.py (rozdzielenie: __main__.py:248)

| podpolecenie | argumenty | definicja |
|---|---|---|
| `status` | --asset{XAUUSD|BTC} | backend/masterquo/analytics/liquidity_cli.py:24 |
| `sessions` | --asset{XAUUSD|BTC} --profile{SCALP_OPENING_V1|LAB_XAU_REFERENCE_V1|LAB_BTC_REFERENCE_V1} | backend/masterquo/analytics/liquidity_cli.py:24 |
| `poll` | --asset{XAUUSD|BTC} | backend/masterquo/analytics/liquidity_cli.py:24 |
| `import` | --asset{XAUUSD|BTC} | backend/masterquo/analytics/liquidity_cli.py:24 |
| `evaluate` | --asset{XAUUSD|BTC} --dataset --commission --allow-synthetic-fixture | backend/masterquo/analytics/liquidity_cli.py:24 |

#### `masterquo neural-scalp` – masterquo/lab/nss_cli.py (rozdzielenie: __main__.py:252)

| podpolecenie | argumenty | definicja |
|---|---|---|
| `doctor` | --asset{XAUUSD|BTC} | backend/masterquo/lab/nss_cli.py:16 |
| `status` | --asset{XAUUSD|BTC} | backend/masterquo/lab/nss_cli.py:16 |
| `prepare` | --asset{XAUUSD|BTC} --dataset --manifest --months --commission --activate{none} --allow-synthetic-fixture --members --budget-minutes --out | backend/masterquo/lab/nss_cli.py:16 |
| `train` | --asset{XAUUSD|BTC} --dataset --manifest --months --commission --activate{none} --allow-synthetic-fixture --members --budget-minutes --out | backend/masterquo/lab/nss_cli.py:16 |
| `report` | --asset{XAUUSD|BTC} --latest --run | backend/masterquo/lab/nss_cli.py:16 |
| `rollback` | --asset{XAUUSD|BTC} | backend/masterquo/lab/nss_cli.py:16 |
| `select` | --asset{XAUUSD|BTC} --run* --role{OBSERVE|SHADOW_GATE}* | backend/masterquo/lab/nss_cli.py:16 |

#### `masterquo ml-scalp` – masterquo/ml/scalp_cli.py (rozdzielenie: __main__.py:256)

| podpolecenie | argumenty | definicja |
|---|---|---|
| `doctor` | --asset{XAUUSD|BTC} | backend/masterquo/ml/scalp_cli.py:15 |
| `status` | --asset{XAUUSD|BTC} | backend/masterquo/ml/scalp_cli.py:15 |
| `prepare` | --asset{XAUUSD|BTC} --dataset --manifest --commission --activate{none} --allow-synthetic-fixture --out --months | backend/masterquo/ml/scalp_cli.py:15 |
| `train` | --asset{XAUUSD|BTC} --dataset --manifest --commission --activate{none} --allow-synthetic-fixture --out --months | backend/masterquo/ml/scalp_cli.py:15 |
| `report` | --asset{XAUUSD|BTC} --latest --run | backend/masterquo/ml/scalp_cli.py:15 |
| `rollback` | --asset{XAUUSD|BTC} --side{BUY|SELL}* | backend/masterquo/ml/scalp_cli.py:15 |
| `select` | --asset{XAUUSD|BTC} --side{BUY|SELL}* --run* --role{OBSERVE|SHADOW_GATE}* | backend/masterquo/ml/scalp_cli.py:15 |

#### `masterquo indicator-context` – masterquo/extind/cli.py (rozdzielenie: __main__.py:260)

| podpolecenie | argumenty | definicja |
|---|---|---|
| `status` |  | backend/masterquo/extind/cli.py:57 |
| `record` | --asset{XAUUSD|BTC} | backend/masterquo/extind/cli.py:58 |
| `dataset` | --asset{XAUUSD|BTC} --dataset --latest-real --commission --allow-synthetic-fixture --groups --out | backend/masterquo/extind/cli.py:60 |
| `calibrate-sar` | --asset{XAUUSD|BTC} --dataset --latest-real --commission --allow-synthetic-fixture --groups --out | backend/masterquo/extind/cli.py:60 |
| `train` | --asset{XAUUSD|BTC} --dataset --latest-real --commission --allow-synthetic-fixture --groups --out | backend/masterquo/extind/cli.py:60 |
| `evaluate` | --asset{XAUUSD|BTC} --run* | backend/masterquo/extind/cli.py:69 |
| `activate` | --asset{XAUUSD|BTC} --run* --variant* | backend/masterquo/extind/cli.py:72 |
| `rollback` | --asset{XAUUSD|BTC} | backend/masterquo/extind/cli.py:76 |

#### `masterquo sh` – masterquo/sh/train_cli.py (rozdzielenie: __main__.py:264)

| podpolecenie | argumenty | definicja |
|---|---|---|
| `train` | --instrument{XAUUSD|BTC}* --dataset* --out* --last-m1 --allow-synthetic --strategies --no-live-write | backend/masterquo/sh/train_cli.py:94 |
| `pack-replay` | --dataset* --last-m1 --variants --commission-price-rt --commission-per-lot-side --slippage --spread-fallback --allow-synthetic --out --garch-json --no-live-write | backend/masterquo/sh/train_cli.py:102 |

#### `masterquo mm` – masterquo/mm/cli.py (rozdzielenie: __main__.py:267)

| podpolecenie | argumenty | definicja |
|---|---|---|
| `inventory` | --instrument{XAUUSD|BTC}* --json | backend/masterquo/mm/cli.py:25 |
| `train` | --dataset* --instrument{XAUUSD|BTC}* --out* --profile{quick|standard} --only --seed --cancel-file | backend/masterquo/mm/cli.py:28 |
| `status` | --instrument{XAUUSD|BTC}* | backend/masterquo/mm/cli.py:36 |
| `buzoa-bench` | --budget | backend/masterquo/mm/cli.py:38 |
| `mathbench-export` | --out* | backend/masterquo/mm/cli.py:40 |
| `export-fixtures` | --out* --parity | backend/masterquo/mm/cli.py:42 |
| `rollback` | --instrument{XAUUSD|BTC}* --model* | backend/masterquo/mm/cli.py:45 |

#### `masterquo montecarlo` – masterquo/montecarlo/cli.py (rozdzielenie: __main__.py:270)

| podpolecenie | argumenty | definicja |
|---|---|---|
| `validate` | --dataset* --horizon --stride --window --n-paths --max-points --out | backend/masterquo/montecarlo/cli.py:18 |
| `rollback` | --instrument{XAUUSD|BTC}* | backend/masterquo/montecarlo/cli.py:26 |
| `status` | --instrument{XAUUSD|BTC}* | backend/masterquo/montecarlo/cli.py:26 |

#### `masterquo studio` – masterquo/studio/app.py (rozdzielenie: __main__.py:273)

Bez argparse: `--port N` czytane ręcznie (`__main__.py:281`), wymagana ważna licencja (`__main__.py:274-279`), serwer `studio/app.py:267 serve()`.

#### `masterquo families` – masterquo/modelhub/families/cli.py (rozdzielenie: __main__.py:283)

Pozycyjne `cmd` z wyborem (wspólne opcje: --instrument{XAUUSD|BTC}* --family --profile{smoke|research|full} --run --use)

| podpolecenie | definicja |
|---|---|
| `list` | backend/masterquo/modelhub/families/cli.py:18 |
| `train` | backend/masterquo/modelhub/families/cli.py:18 |
| `train-all` | backend/masterquo/modelhub/families/cli.py:18 |
| `activate` | backend/masterquo/modelhub/families/cli.py:18 |
| `use` | backend/masterquo/modelhub/families/cli.py:18 |
| `rollback` | backend/masterquo/modelhub/families/cli.py:18 |

#### `masterquo trainhub` – masterquo/trainhub/cli.py (rozdzielenie: __main__.py:286)

Pozycyjne `cmd` z wyborem (wspólne opcje: path --instrument{XAUUSD|BTC}* --mode{incremental|historical} --from --to --lookback-days --tf --base-tf --horizon --k-atr --models --profile{smoke|research|full} --seed --commission-price --model-key --version --out --demo)

| podpolecenie | definicja |
|---|---|
| `export` | backend/masterquo/trainhub/cli.py:30 |
| `import-data` | backend/masterquo/trainhub/cli.py:30 |
| `dataset` | backend/masterquo/trainhub/cli.py:30 |
| `train` | backend/masterquo/trainhub/cli.py:30 |
| `evaluate` | backend/masterquo/trainhub/cli.py:30 |
| `full` | backend/masterquo/trainhub/cli.py:30 |
| `list` | backend/masterquo/trainhub/cli.py:30 |
| `activate` | backend/masterquo/trainhub/cli.py:30 |
| `rollback` | backend/masterquo/trainhub/cli.py:30 |
| `package-zip` | backend/masterquo/trainhub/cli.py:30 |

#### `masterquo quant` – masterquo/quant/cli.py (rozdzielenie: __main__.py:290)

Pozycyjne `cmd` z wyborem (wspólne opcje: value --instrument{XAUUSD|BTC} --task --version --out --live --confirm --n --api-n)

| podpolecenie | definicja |
|---|---|
| `status` | backend/masterquo/quant/cli.py:53 |
| `inventory` | backend/masterquo/quant/cli.py:53 |
| `train` | backend/masterquo/quant/cli.py:53 |
| `list` | backend/masterquo/quant/cli.py:53 |
| `activate` | backend/masterquo/quant/cli.py:53 |
| `rollback` | backend/masterquo/quant/cli.py:53 |
| `mode` | backend/masterquo/quant/cli.py:53 |
| `bench` | backend/masterquo/quant/cli.py:53 |

#### `masterquo training` – masterquo/training/cli.py (rozdzielenie: __main__.py:294)

| podpolecenie | argumenty | definicja |
|---|---|---|
| `menu` | --demo | backend/masterquo/training/cli.py:471 |
| `install` | --demo | backend/masterquo/training/cli.py:471 |
| `diag` | --demo | backend/masterquo/training/cli.py:471 |
| `run` | --instruments --profile{TEST_INSTALACJI|PELNY_TRENING} --months --symbol-xauusd --symbol-btc --commission-xauusd --commission-btc --tasks --no-approx --lab-bars --ml-days --min-events --threads --interactive --no-detect --demo --dataset-xauusd --dataset-btc --origin | backend/masterquo/training/cli.py:474 |
| `resume` | run_id | backend/masterquo/training/cli.py:494 |
| `cancel` | run_id | backend/masterquo/training/cli.py:494 |
| `status` | run_id | backend/masterquo/training/cli.py:494 |
| `report` | run_id | backend/masterquo/training/cli.py:494 |
| `rollback` | --instrument{XAUUSD|BTC}* --family* | backend/masterquo/training/cli.py:497 |
| `symbols` | --demo | backend/masterquo/training/cli.py:500 |
| `export` | --instrument{XAUUSD|BTC}* --symbol* --months --out* --tfs --dst-model{AUTO|UNIFORM|NY_CLOSE} --from --to --ticks-days --synthetic | backend/masterquo/training/cli.py:502 |
| `ml-offline` | --instrument{XAUUSD|BTC}* --dataset* --days --threads --include-approx --commission --out* | backend/masterquo/training/cli.py:513 |
| `lab-offline` | --instrument{XAUUSD|BTC}* --dataset* --bars --families --experiments --min-events --out* | backend/masterquo/training/cli.py:521 |

### A.3 Inne punkty wejścia `python -m …` (osobne runtime’y / procesy robocze)

| moduł | uruchamiany przez | argumenty (AST) |
|---|---|---|
| `gold_candles_runtime.plan_train` | 12_TRENING_MODELI_XAUUSD.bat:13, masterquo/training/runner.py:190 | opcje: --data-dir --latest --out --trees --data-kind --no-activate --instrument |
| `gold_candles_runtime.registry_cli` | 13_*.bat:11, 14_*.bat:13/15, 15_*.bat:14, masterquo/training/runner.py:638 | podpolecenia: list, activate, rollback, deactivate; opcje: --instrument |
| `gold_candles_runtime.validate` | 13_WALIDACJA_MODELI_XAUUSD.bat:12 | opcje: --run-id --instrument |
| `gold_candles_runtime.scalp_train` | 17_TRENING_SCALP_ML.bat:17, masterquo/training/runner.py:229 | opcje: --history --latest --data-kind --commission-per-lot-side --instrument --slippage-ticks --no-activate --small-test |
| `gold_candles_runtime.scalp_registry` | 18_*.bat:11/13, 20_*.bat:12, 21_*.bat:13/15, masterquo/training/runner.py:647 | podpolecenia: list, activate, rollback, deactivate, validate; opcje: --instrument |
| `gold_candles_runtime.worker` | masterquo/forecast/service.py:95 | bez argparse |
| `masterquo.trainhub.worker` | masterquo/trainhub/jobs.py:287 | bez argparse |
| `masterquo.studio.jobrun` | masterquo/studio/queue.py:180 | bez argparse |
| `masterquo.studio.verify` | masterquo/studio/pipeline.py:510 | bez argparse |
| `masterquo.decision.replay` | ręcznie (opis: tools/integration_matrix.py:115) | opcje: --db --required --preds --cap --requests --out |
| `masterquo.ml.trainer` | masterquo/ml/service.py:330 | bez argparse |
| `masterquo.modelhub.families.run` | masterquo/modelhub/families/service.py:201 | opcje: --family --instrument --profile --job-file --config --bars-file |
| `kronos_runtime.worker` | masterquo/kronos/service.py:184, masterquo/kronos/validation.py:106 | bez argparse |
| `kronos_runtime.install` | tools/kronos_setup.py:251/258, masterquo/kronos/service.py:735 | podpolecenia: download, verify; opcje: --weights-dir --status-file --reference --device |
| `deep_runtime.worker` | masterquo/modelhub/families/deep.py:35 | bez argparse |
| `tsfm_runtime.worker` | masterquo/tsfm/service.py:157 | opcje: --model |
| `tsfm_runtime.install` | tools/tsfm_setup.py:188/197 | opcje: --model --weights-root --from-dir --selftest --device --status-file |
| `tsfm_runtime.granite_finetune` | masterquo/tsfm/granite_train.py:113 | opcje: --data --weights-root --out --horizon --epochs --threads --stride --lr --batch --seed --run-id --status-file |
| `tabicl_runtime.worker` | masterquo/quant/tabicl.py:377 | bez argparse |
| `tabicl_runtime.install` | tools/tsfm_setup.py:188/197 (RUNTIME['tabicl'], :36) | opcje: --weights-root --status-file --selftest --from-dir |
| `sdformer_runtime.train` | masterquo/research/service.py:496 | opcje: --data --out --op --checkpoint --epochs --minutes --batch --lr --seed --threads --context --cancel-file --status-file --run-id |
| `sdformer_runtime.infer` | masterquo/research/service.py:570/597 | opcje: --checkpoint --bars --threads |
| `gold_candles (pakiet referencyjny, __main__ -> cli.main)` | brak wywołań w .bat/kodzie – biblioteka importowana przez gold_candles_runtime | podpolecenia: demo; opcje: --output --m5 --m30 --symbol --tick-size --as-of --count --model --mode --output-dir --trees --data-kind --interval |

### A.4 Skrypty `tools/*.py` (narzędzia wydania, testów, instalacji)

| skrypt | argumenty (AST) |
|---|---|
| tools/backtest_ema_pullback.py | opcje: --csv --synthetic --tf --capital --risk-pct --commission-lot-side --slippage-ticks --contract-size --point --tick-size --spread-price --report |
| tools/build_desktop.py | opcje: --offline --edition --allow-foreign-key |
| tools/build_release.py | opcje: --edition --allow-foreign-key |
| tools/check_python.py | bez argparse |
| tools/check_requirements_win.py | bez argparse |
| tools/cult_assets.py | opcje: --src |
| tools/deep_setup.py | opcje: --root --python --log |
| tools/golden_run.py | podpolecenia: run, replay, compare; opcje: --out --minutes --start --port --speed --days --m1-bars --report |
| tools/integration_matrix.py | opcje: --results --check |
| tools/kronos_setup.py | opcje: --root --weights-dir --cuda --status-file --python --log |
| tools/make_comparison_doc.py | bez argparse |
| tools/make_easy_guide.py | opcje: --shots --out |
| tools/make_install_guide.py | opcje: --shots --out |
| tools/make_manuals.py | opcje: --shots --out |
| tools/make_strategy_cards.py | bez argparse |
| tools/migration_check.py | opcje: --old-ref --keep |
| tools/minirocket_sktime_reference.py | bez argparse |
| tools/model_docs.py | bez argparse |
| tools/model_map.py | bez argparse |
| tools/mr2_native_status.py | bez argparse |
| tools/neural_city_assets.py | opcje: --menu --launcher |
| tools/ram_benchmark.py | opcje: --bars --bars15 --tsfm-weights --kronos-weights --granite-python --chronos-python --kronos-python --threads-heavy --threads-light --cycles --single --backend-pid --out |
| tools/replay_strategies.py | opcje: --csv-dir --synthetic --seed --step-tf --spread --point --slippage --commission --compare-original --walls --iv-csv --params-json --max-steps --trade-policy --out |
| tools/run_tests.py | bez argparse |
| tools/tsfm_setup.py | opcje: --model --root --weights-root --cuda --from-dir --status-file --python --log |
| tools/validate_families_synthetic.py | opcje: --out --profile --deep-python |
| tools/venv_repair.py | bez argparse |
| tools/verify_release.py | bez argparse |

## B. API HTTP (FastAPI, `create_app(rt, port)` – `backend/masterquo/api/app.py:197`)

Trasy z dekoratorów (AST) = 520; trasy zarejestrowane w aplikacji (create_app z atrapą Runtime, bez serwera) = 511 (+9 tras właściciela `owner_routes.py` tylko przy `rt.license.edition == "OWNER"`, `api/app.py:3320`). Kolumna *użycie*: FE = panel (frontend/src), backend = wywołania z kodu (np. CLI eksportu przez API), tools, tests, mql5, desktop; `—` = brak jakiegokolwiek odwołania w repozytorium (kandydat do decyzji, NIE do automatycznego usunięcia – mogło to być API starego panelu 1.41 z archive/).

### backend/masterquo/api/app.py (436 tras)

<details><summary><code>(strony/zasoby)</code> – 4</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/` | index | backend/masterquo/api/app.py:267 | przeglądarka |
| GET | `/assets/{name:path}` | assets | backend/masterquo/api/app.py:278 | przeglądarka |
| GET | `/static/{name:path}` | static | backend/masterquo/api/app.py:286 | przeglądarka |
| GET | `/media/masterquo/{slot}` | media | backend/masterquo/api/app.py:3937 | przeglądarka |

</details>

<details><summary><code>/api/v1/health</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/health` | health | backend/masterquo/api/app.py:294 | tools, desktop, backend, tests |

</details>

<details><summary><code>/api/v1/session</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/session` | session | backend/masterquo/api/app.py:300 | tools, backend, tests, frontend/src |

</details>

<details><summary><code>/api/v1/state</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/state` | state | backend/masterquo/api/app.py:334 | tools, tests, frontend/src |

</details>

<details><summary><code>/api/v1/candles</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/candles` | candles | backend/masterquo/api/app.py:338 | tests, frontend/src |

</details>

<details><summary><code>/api/v1/volatility</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/volatility` | volatility | backend/masterquo/api/app.py:344 | — |

</details>

<details><summary><code>/api/v1/timeframes</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/timeframes` | timeframes | backend/masterquo/api/app.py:349 | tests, frontend/src |

</details>

<details><summary><code>/api/v1/forecast</code> – 3</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/forecast` | forecast_get | backend/masterquo/api/app.py:364 | tools, backend, tests |
| GET | `/api/v1/forecast/shadow` | forecast_shadow | backend/masterquo/api/app.py:1400 | tools |
| POST | `/api/v1/forecast/reload` | forecast_reload | backend/masterquo/api/app.py:1404 | backend |

</details>

<details><summary><code>/api/v1/lab</code> – 40</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/lab` | lab_state | backend/masterquo/api/app.py:391 | backend, tests |
| GET | `/api/v1/lab/traceability` | lab_trace | backend/masterquo/api/app.py:395 | backend, tests |
| GET | `/api/v1/lab/memory` | lab_memory | backend/masterquo/api/app.py:400 | backend, tests |
| POST | `/api/v1/lab/train` | lab_train | backend/masterquo/api/app.py:413 | backend, tests |
| GET | `/api/v1/lab/jobs` | lab_jobs | backend/masterquo/api/app.py:438 | — |
| POST | `/api/v1/lab/jobs/{jid}/cancel` | lab_cancel | backend/masterquo/api/app.py:442 | — |
| GET | `/api/v1/lab/models` | lab_models | backend/masterquo/api/app.py:550 | — |
| GET | `/api/v1/lab/studies/{jid}` | lab_study | backend/masterquo/api/app.py:555 | — |
| GET | `/api/v1/lab/trials` | lab_trials | backend/masterquo/api/app.py:564 | — |
| POST | `/api/v1/lab/zones` | lab_zone_add | backend/masterquo/api/app.py:571 | tests |
| PATCH | `/api/v1/lab/zones/{zone_id}` | lab_zone_patch | backend/masterquo/api/app.py:580 | tests |
| DELETE | `/api/v1/lab/zones/{zone_id}` | lab_zone_delete | backend/masterquo/api/app.py:595 | tests |
| GET | `/api/v1/lab/zones/diagnostics` | lab_zone_diag | backend/masterquo/api/app.py:604 | — |
| GET | `/api/v1/lab/zones` | lab_zones | backend/masterquo/api/app.py:609 | tests |
| GET | `/api/v1/lab/repaint` | lab_repaint | backend/masterquo/api/app.py:614 | — |
| POST | `/api/v1/lab/tradepad` | lab_tradepad | backend/masterquo/api/app.py:619 | backend, tests |
| POST | `/api/v1/lab/tradepad/execute` | lab_tradepad_execute | backend/masterquo/api/app.py:645 | — |
| GET | `/api/v1/lab/context` | ctx_summary | backend/masterquo/api/app.py:892 | — |
| GET | `/api/v1/lab/vamd` | ctx_vamd | backend/masterquo/api/app.py:898 | — |
| GET | `/api/v1/lab/fractal-regime` | ctx_fd | backend/masterquo/api/app.py:902 | — |
| GET | `/api/v1/lab/smc` | ctx_smc | backend/masterquo/api/app.py:906 | — |
| GET | `/api/v1/lab/buffers/reports` | buf_reports | backend/masterquo/api/app.py:910 | — |
| GET | `/api/v1/lab/buffers/reports/{rid}` | buf_report | backend/masterquo/api/app.py:915 | — |
| POST | `/api/v1/lab/buffers/reports/import` | buf_import | backend/masterquo/api/app.py:923 | — |
| GET | `/api/v1/lab/buffers/mappings` | buf_mappings | backend/masterquo/api/app.py:940 | — |
| POST | `/api/v1/lab/buffers/mappings/validate` | buf_validate | backend/masterquo/api/app.py:945 | — |
| POST | `/api/v1/lab/buffers/mappings` | buf_save | backend/masterquo/api/app.py:950 | — |
| POST | `/api/v1/lab/buffers/mappings/{mid}/rollback` | buf_rollback | backend/masterquo/api/app.py:955 | — |
| GET | `/api/v1/lab/buffers/source` | buf_source | backend/masterquo/api/app.py:963 | — |
| POST | `/api/v1/lab/context/calibrate` | ctx_calibrate | backend/masterquo/api/app.py:967 | — |
| GET | `/api/v1/lab/neural` | nss_state | backend/masterquo/api/app.py:3661 | tests |
| GET | `/api/v1/lab/neural/history` | nss_history | backend/masterquo/api/app.py:3665 | — |
| GET | `/api/v1/lab/neural/report` | nss_report | backend/masterquo/api/app.py:3669 | — |
| GET | `/api/v1/lab/neural/jobs` | nss_jobs_list | backend/masterquo/api/app.py:3681 | — |
| POST | `/api/v1/lab/neural/prepare` | nss_prepare | backend/masterquo/api/app.py:3685 | — |
| POST | `/api/v1/lab/neural/doctor` | nss_doctor | backend/masterquo/api/app.py:3689 | tests |
| POST | `/api/v1/lab/neural/train` | nss_train | backend/masterquo/api/app.py:3703 | — |
| POST | `/api/v1/lab/neural/cancel` | nss_cancel | backend/masterquo/api/app.py:3707 | — |
| POST | `/api/v1/lab/neural/select` | nss_select | backend/masterquo/api/app.py:3716 | — |
| POST | `/api/v1/lab/neural/rollback` | nss_rollback | backend/masterquo/api/app.py:3724 | — |

</details>

<details><summary><code>/api/v1/indicator-context</code> – 7</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/indicator-context` | indicator_context_status | backend/masterquo/api/app.py:447 | tests, frontend/src |
| GET | `/api/v1/indicator-context/chart` | indicator_context_chart | backend/masterquo/api/app.py:459 | tests, frontend/src |
| GET | `/api/v1/indicator-context/inventory` | indicator_context_inventory | backend/masterquo/api/app.py:481 | — |
| PUT | `/api/v1/indicator-context/mapping` | indicator_context_mapping | backend/masterquo/api/app.py:488 | — |
| POST | `/api/v1/indicator-context/train` | indicator_context_train | backend/masterquo/api/app.py:511 | tests |
| POST | `/api/v1/indicator-context/activate` | indicator_context_activate | backend/masterquo/api/app.py:532 | tests |
| POST | `/api/v1/indicator-context/rollback` | indicator_context_rollback | backend/masterquo/api/app.py:541 | tests |

</details>

<details><summary><code>/api/v1/manual</code> – 7</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/manual/plan` | manual_plan | backend/masterquo/api/app.py:654 | — |
| POST | `/api/v1/manual/intents` | manual_intent | backend/masterquo/api/app.py:662 | — |
| GET | `/api/v1/manual/intents` | manual_intents | backend/masterquo/api/app.py:670 | — |
| GET | `/api/v1/manual/intents/{iid}` | manual_intent_get | backend/masterquo/api/app.py:674 | — |
| POST | `/api/v1/manual/intents/{iid}/execute` | manual_execute | backend/masterquo/api/app.py:689 | — |
| POST | `/api/v1/manual/intents/{iid}/manage` | manual_manage | backend/masterquo/api/app.py:698 | — |
| POST | `/api/v1/manual/reconcile` | manual_reconcile | backend/masterquo/api/app.py:710 | — |

</details>

<details><summary><code>/api/v1/structure-intelligence</code> – 21</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/structure-intelligence` | si_latest | backend/masterquo/api/app.py:720 | backend, tests |
| GET | `/api/v1/structure-intelligence/snapshots/{sid}` | si_snapshot | backend/masterquo/api/app.py:726 | — |
| GET | `/api/v1/structure-intelligence/forecasts` | si_forecasts | backend/masterquo/api/app.py:733 | tests |
| GET | `/api/v1/structure-intelligence/models` | si_models | backend/masterquo/api/app.py:737 | — |
| POST | `/api/v1/structure-intelligence/models/select` | si_select | backend/masterquo/api/app.py:745 | — |
| POST | `/api/v1/structure-intelligence/models/rollback` | si_rollback | backend/masterquo/api/app.py:753 | — |
| GET | `/api/v1/structure-intelligence/neutralization` | si_neutral | backend/masterquo/api/app.py:761 | — |
| GET | `/api/v1/structure-intelligence/quotes` | si_quotes | backend/masterquo/api/app.py:765 | — |
| GET | `/api/v1/structure-intelligence/quote-forecasts` | si_quote_fc | backend/masterquo/api/app.py:769 | — |
| GET | `/api/v1/structure-intelligence/quote-quality` | si_quote_q | backend/masterquo/api/app.py:773 | — |
| GET | `/api/v1/structure-intelligence/regimes` | si_regimes | backend/masterquo/api/app.py:787 | — |
| GET | `/api/v1/structure-intelligence/swings` | si_swings | backend/masterquo/api/app.py:791 | — |
| GET | `/api/v1/structure-intelligence/swings/{sid}` | si_swing | backend/masterquo/api/app.py:795 | — |
| GET | `/api/v1/structure-intelligence/smma` | si_smma | backend/masterquo/api/app.py:802 | — |
| GET | `/api/v1/structure-intelligence/zscore` | si_zscore | backend/masterquo/api/app.py:806 | — |
| GET | `/api/v1/structure-intelligence/native-status` | si_native | backend/masterquo/api/app.py:812 | — |
| GET | `/api/v1/structure-intelligence/model-diagnostics` | si_model_diag | backend/masterquo/api/app.py:816 | — |
| GET | `/api/v1/structure-intelligence/quality` | si_quality | backend/masterquo/api/app.py:977 | — |
| POST | `/api/v1/structure-intelligence/jobs` | si_job_start | backend/masterquo/api/app.py:981 | backend |
| GET | `/api/v1/structure-intelligence/jobs/{jid}` | si_job | backend/masterquo/api/app.py:989 | — |
| POST | `/api/v1/structure-intelligence/jobs/{jid}/cancel` | si_job_cancel | backend/masterquo/api/app.py:996 | — |

</details>

<details><summary><code>/api/v1/flow-context</code> – 7</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/flow-context` | fc_summary | backend/masterquo/api/app.py:845 | tests |
| GET | `/api/v1/flow-context/series` | fc_series | backend/masterquo/api/app.py:851 | — |
| GET | `/api/v1/flow-context/channels` | fc_channels | backend/masterquo/api/app.py:855 | — |
| GET | `/api/v1/flow-context/markov` | fc_markov | backend/masterquo/api/app.py:861 | — |
| GET | `/api/v1/flow-context/stopdistance` | fc_stop | backend/masterquo/api/app.py:865 | — |
| GET | `/api/v1/flow-context/native` | fc_native | backend/masterquo/api/app.py:869 | — |
| GET | `/api/v1/flow-context/models` | fc_models | backend/masterquo/api/app.py:874 | — |

</details>

<details><summary><code>/api/v1/black76</code> – 3</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/black76/price` | b76_price | backend/masterquo/api/app.py:1001 | — |
| POST | `/api/v1/black76/iv` | b76_iv | backend/masterquo/api/app.py:1010 | — |
| POST | `/api/v1/black76/forward` | b76_forward | backend/masterquo/api/app.py:1020 | — |

</details>

<details><summary><code>/api/v1/analytics</code> – 4</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/analytics` | analytics_get | backend/masterquo/api/app.py:1028 | frontend/src |
| GET | `/api/v1/analytics/tf/{tf}` | analytics_tf | backend/masterquo/api/app.py:1032 | — |
| GET | `/api/v1/analytics/history` | analytics_history | backend/masterquo/api/app.py:1038 | — |
| GET | `/api/v1/analytics/diagnostics` | analytics_diag | backend/masterquo/api/app.py:1042 | frontend/src |

</details>

<details><summary><code>/api/v1/patterns</code> – 17</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/patterns/samples` | pat_list | backend/masterquo/api/app.py:1046 | — |
| POST | `/api/v1/patterns/samples` | pat_add | backend/masterquo/api/app.py:1050 | — |
| GET | `/api/v1/patterns/samples/{sid}` | pat_get | backend/masterquo/api/app.py:1064 | — |
| DELETE | `/api/v1/patterns/samples/{sid}` | pat_del | backend/masterquo/api/app.py:1071 | — |
| POST | `/api/v1/patterns/samples/{sid}/validate` | pat_validate_one | backend/masterquo/api/app.py:1075 | — |
| POST | `/api/v1/patterns/validate` | pat_validate | backend/masterquo/api/app.py:1082 | — |
| GET | `/api/v1/patterns/jobs/{job_id}` | pat_job | backend/masterquo/api/app.py:1089 | — |
| POST | `/api/v1/patterns/jobs/{job_id}/cancel` | pat_cancel | backend/masterquo/api/app.py:1096 | — |
| POST | `/api/v1/patterns/jobs/{job_id}/resume` | pat_resume | backend/masterquo/api/app.py:1100 | — |
| POST | `/api/v1/patterns/jobs/{job_id}/export` | pat_export_job | backend/masterquo/api/app.py:1107 | — |
| GET | `/api/v1/patterns/jobs/{job_id}/results` | pat_job_results | backend/masterquo/api/app.py:1112 | — |
| GET | `/api/v1/patterns/results/{result_id}` | pat_result | backend/masterquo/api/app.py:1116 | — |
| GET | `/api/v1/patterns/samples/{sid}/result` | pat_sample_result | backend/masterquo/api/app.py:1124 | — |
| GET | `/api/v1/patterns/reports/{report_id}` | pat_report | backend/masterquo/api/app.py:1131 | — |
| GET | `/api/v1/patterns/export` | pat_export | backend/masterquo/api/app.py:1138 | — |
| POST | `/api/v1/patterns/import` | pat_import | backend/masterquo/api/app.py:1142 | — |
| GET | `/api/v1/patterns/live` | pat_live | backend/masterquo/api/app.py:1146 | — |

</details>

<details><summary><code>/api/v1/scalp</code> – 6</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/scalp` | scalp_get | backend/masterquo/api/app.py:1152 | tools, backend |
| GET | `/api/v1/scalp/shadow` | scalp_shadow | backend/masterquo/api/app.py:1396 | tools |
| GET | `/api/v1/scalp/dashboard` | mtf_dashboard | backend/masterquo/api/app.py:3611 | backend |
| GET | `/api/v1/scalp/dashboard/chart` | mtf_chart | backend/masterquo/api/app.py:3627 | backend |
| GET | `/api/v1/scalp/dashboard/snapshots` | mtf_snapshots | backend/masterquo/api/app.py:3634 | — |
| GET | `/api/v1/scalp/dashboard/snapshots/{sid}` | mtf_snapshot | backend/masterquo/api/app.py:3639 | — |

</details>

<details><summary><code>/api/v1/telemetry</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/telemetry` | telemetry | backend/masterquo/api/app.py:1161 | tests |

</details>

<details><summary><code>/api/v1/sh</code> – 16</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/sh` | sh_get | backend/masterquo/api/app.py:1188 | tools, tests, frontend/src |
| GET | `/api/v1/sh/scenario` | sh_scenario | backend/masterquo/api/app.py:1198 | tools, tests |
| GET | `/api/v1/sh/signals` | sh_signals | backend/masterquo/api/app.py:1225 | tools, tests, frontend/src |
| GET | `/api/v1/sh/strategies` | sh_strategies | backend/masterquo/api/app.py:1234 | tools, frontend/src |
| POST | `/api/v1/sh/strategies/config` | sh_strategies_config | backend/masterquo/api/app.py:1246 | tools |
| GET | `/api/v1/sh/pack/stats` | sh_pack_stats | backend/masterquo/api/app.py:1257 | tests |
| GET | `/api/v1/sh/pack/evaluations` | sh_pack_evaluations | backend/masterquo/api/app.py:1285 | — |
| GET | `/api/v1/sh/signals/{sid}` | sh_signal | backend/masterquo/api/app.py:1301 | tests |
| GET | `/api/v1/sh/plans` | sh_plans | backend/masterquo/api/app.py:1325 | tools, tests |
| GET | `/api/v1/sh/plans/{pid}` | sh_plan | backend/masterquo/api/app.py:1333 | tests |
| POST | `/api/v1/sh/plans/{pid}/close` | sh_plan_close | backend/masterquo/api/app.py:1342 | tests |
| GET | `/api/v1/sh/validation` | sh_validation | backend/masterquo/api/app.py:1349 | frontend/src |
| GET | `/api/v1/sh/config` | sh_config_get | backend/masterquo/api/app.py:1364 | tests, frontend/src |
| POST | `/api/v1/sh/config` | sh_config_set | backend/masterquo/api/app.py:1369 | tests, frontend/src |
| POST | `/api/v1/sh/config/rollback` | sh_config_rollback | backend/masterquo/api/app.py:1380 | tests |
| GET | `/api/v1/sh/chart` | sh_chart | backend/masterquo/api/app.py:1388 | tests |

</details>

<details><summary><code>/api/v1/plans</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/plans/chart` | plans_chart | backend/masterquo/api/app.py:1308 | tools, tests, frontend/src |

</details>

<details><summary><code>/api/v1/walls</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/walls` | walls_get | backend/masterquo/api/app.py:1410 | — |
| POST | `/api/v1/walls/iv-import` | walls_iv_import | backend/masterquo/api/app.py:1416 | — |

</details>

<details><summary><code>/api/v1/structure</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/structure` | structure | backend/masterquo/api/app.py:1432 | backend, tests, frontend/src |

</details>

<details><summary><code>/api/v1/assets</code> – 4</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/assets` | assets_state | backend/masterquo/api/app.py:1447 | backend |
| GET | `/api/v1/assets/{asset}/candidates` | assets_candidates | backend/masterquo/api/app.py:1453 | — |
| POST | `/api/v1/assets/confirm` | assets_confirm | backend/masterquo/api/app.py:1463 | — |
| POST | `/api/v1/assets/active` | assets_active | backend/masterquo/api/app.py:1476 | — |

</details>

<details><summary><code>/api/v1/execution</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/execution/lock` | exec_lock | backend/masterquo/api/app.py:1494 | — |
| POST | `/api/v1/execution/lock` | exec_lock_set | backend/masterquo/api/app.py:1499 | — |

</details>

<details><summary><code>/api/v1/markets</code> – 5</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/markets` | markets | backend/masterquo/api/app.py:1503 | tests |
| POST | `/api/v1/markets/scan` | markets_scan | backend/masterquo/api/app.py:1507 | — |
| GET | `/api/v1/markets/symbols` | markets_symbols | backend/masterquo/api/app.py:1514 | — |
| GET | `/api/v1/markets/detail` | markets_detail | backend/masterquo/api/app.py:1521 | — |
| GET | `/api/v1/markets/chart` | markets_chart | backend/masterquo/api/app.py:1532 | — |

</details>

<details><summary><code>/api/v1/signal-history</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/signal-history` | signal_history | backend/masterquo/api/app.py:1551 | tools |

</details>

<details><summary><code>/api/v1/context-tf</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/context-tf` | context_tf_view | backend/masterquo/api/app.py:1561 | — |

</details>

<details><summary><code>/api/v1/bot-signals</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/bot-signals` | bot_signals | backend/masterquo/api/app.py:1566 | tools, frontend/src |
| GET | `/api/v1/bot-signals/{signal_id}` | bot_signal_get | backend/masterquo/api/app.py:1572 | — |

</details>

<details><summary><code>/api/v1/signals</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/signals` | signals | backend/masterquo/api/app.py:1579 | tools, tests |

</details>

<details><summary><code>/api/v1/decision</code> – 3</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/decision` | decision | backend/masterquo/api/app.py:1595 | tools, frontend/src |
| GET | `/api/v1/decision/status` | decision_status | backend/masterquo/api/app.py:2659 | tools |
| GET | `/api/v1/decision/records/{record_id}` | decision_record | backend/masterquo/api/app.py:2667 | tools |

</details>

<details><summary><code>/api/v1/stats</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/stats` | get_stats | backend/masterquo/api/app.py:1599 | tools, tests, frontend/src |

</details>

<details><summary><code>/api/v1/news</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/news` | news | backend/masterquo/api/app.py:1614 | — |
| POST | `/api/v1/news/refresh` | news_refresh | backend/masterquo/api/app.py:3981 | — |

</details>

<details><summary><code>/api/v1/logs</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/logs` | logs | backend/masterquo/api/app.py:1618 | tests |

</details>

<details><summary><code>/api/v1/config</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/config` | get_config | backend/masterquo/api/app.py:1622 | tools, backend, tests, frontend/src |
| PUT | `/api/v1/config` | put_config | backend/masterquo/api/app.py:1629 | tools, backend, tests, frontend/src |

</details>

<details><summary><code>/api/v1/secrets</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/secrets/anthropic` | set_key | backend/masterquo/api/app.py:1673 | tests, frontend/src |
| POST | `/api/v1/secrets` | set_secret | backend/masterquo/api/app.py:1679 | tests, frontend/src |

</details>

<details><summary><code>/api/v1/agent</code> – 7</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/agent` | agent_status | backend/masterquo/api/app.py:1691 | frontend/src |
| GET | `/api/v1/agent/models` | agent_models | backend/masterquo/api/app.py:1697 | frontend/src |
| POST | `/api/v1/agent/test` | agent_test | backend/masterquo/api/app.py:1701 | frontend/src |
| POST | `/api/v1/agent/ask` | agent_ask | backend/masterquo/api/app.py:1705 | — |
| POST | `/api/v1/agent/analyze` | agent_analyze | backend/masterquo/api/app.py:1713 | — |
| GET | `/api/v1/agent/memory` | agent_memory | backend/masterquo/api/app.py:1722 | — |
| POST | `/api/v1/agent/memory/{mid}` | agent_memory_set | backend/masterquo/api/app.py:1726 | — |

</details>

<details><summary><code>/api/v1/mode</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/mode` | set_mode | backend/masterquo/api/app.py:1735 | tools, backend, tests, frontend/src |
| POST | `/api/v1/mode/primary-path` | set_primary_path | backend/masterquo/api/app.py:1749 | tools, frontend/src |

</details>

<details><summary><code>/api/v1/strategy</code> – 5</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/strategy/auto` | strategy_auto | backend/masterquo/api/app.py:1764 | tools, tests, frontend/src |
| POST | `/api/v1/strategy/mode` | strategy_mode | backend/masterquo/api/app.py:1768 | tests, frontend/src |
| POST | `/api/v1/strategy/toggle` | strategy_toggle | backend/masterquo/api/app.py:3867 | tests |
| POST | `/api/v1/strategy/profile` | strategy_profile | backend/masterquo/api/app.py:3883 | — |
| GET | `/api/v1/strategy/selection-log` | selection_log | backend/masterquo/api/app.py:3891 | tools |

</details>

<details><summary><code>/api/v1/prefs</code> – 3</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/prefs` | prefs_get | backend/masterquo/api/app.py:1786 | frontend/src |
| POST | `/api/v1/prefs/setup-view` | prefs_setup_view | backend/masterquo/api/app.py:1791 | — |
| POST | `/api/v1/prefs/leverage` | prefs_leverage | backend/masterquo/api/app.py:1804 | frontend/src |

</details>

<details><summary><code>/api/v1/setups</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/setups` | setups_list | backend/masterquo/api/app.py:1815 | tools, frontend/src |
| GET | `/api/v1/setups/{setup_id}/details` | setup_detail | backend/masterquo/api/app.py:1820 | — |

</details>

<details><summary><code>/api/v1/ml</code> – 21</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/ml/status` | ml_status | backend/masterquo/api/app.py:1831 | tools |
| POST | `/api/v1/ml/mode` | ml_mode | backend/masterquo/api/app.py:1835 | frontend/src |
| POST | `/api/v1/ml/collect` | ml_collect | backend/masterquo/api/app.py:1842 | — |
| POST | `/api/v1/ml/pause` | ml_pause | backend/masterquo/api/app.py:1846 | — |
| POST | `/api/v1/ml/train` | ml_train | backend/masterquo/api/app.py:1850 | — |
| GET | `/api/v1/ml/scalp` | ml_scalp_status | backend/masterquo/api/app.py:3733 | backend, tests |
| POST | `/api/v1/ml/scalp/prepare` | ml_scalp_prepare | backend/masterquo/api/app.py:3766 | — |
| POST | `/api/v1/ml/scalp/train` | ml_scalp_train | backend/masterquo/api/app.py:3773 | tests |
| GET | `/api/v1/ml/scalp/predictions` | ml_scalp_predictions | backend/masterquo/api/app.py:3784 | — |
| GET | `/api/v1/ml/scalp/explain` | ml_scalp_explain | backend/masterquo/api/app.py:3792 | backend |
| POST | `/api/v1/ml/scalp/select` | ml_scalp_select | backend/masterquo/api/app.py:3804 | tests |
| POST | `/api/v1/ml/scalp/rollback` | ml_scalp_rollback | backend/masterquo/api/app.py:3813 | tests |
| POST | `/api/v1/ml/reload` | ml_reload | backend/masterquo/api/app.py:3822 | backend |
| POST | `/api/v1/ml/backfill` | ml_backfill | backend/masterquo/api/app.py:3829 | — |
| POST | `/api/v1/ml/cancel` | ml_cancel | backend/masterquo/api/app.py:3833 | — |
| POST | `/api/v1/ml/resume` | ml_resume | backend/masterquo/api/app.py:3837 | — |
| POST | `/api/v1/ml/rollback` | ml_rollback | backend/masterquo/api/app.py:3841 | — |
| GET | `/api/v1/ml/models` | ml_models | backend/masterquo/api/app.py:3848 | — |
| GET | `/api/v1/ml/report` | ml_report | backend/masterquo/api/app.py:3852 | — |
| GET | `/api/v1/ml/explain` | ml_explain | backend/masterquo/api/app.py:3856 | backend |
| GET | `/api/v1/ml/predict` | ml_predict | backend/masterquo/api/app.py:3860 | — |

</details>

<details><summary><code>/api/v1/training</code> – 17</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/training` | training_state | backend/masterquo/api/app.py:1860 | tests |
| GET | `/api/v1/training/models` | training_models | backend/masterquo/api/app.py:1871 | tests |
| GET | `/api/v1/training/readiness` | training_readiness | backend/masterquo/api/app.py:3159 | — |
| GET | `/api/v1/training/runs` | training_runs | backend/masterquo/api/app.py:3166 | — |
| GET | `/api/v1/training/runs/{rid}` | training_run | backend/masterquo/api/app.py:3178 | — |
| GET | `/api/v1/training/runs/{rid}/log` | training_run_log | backend/masterquo/api/app.py:3183 | — |
| GET | `/api/v1/training/runs/{rid}/report` | training_run_report | backend/masterquo/api/app.py:3191 | — |
| GET | `/api/v1/training/compare` | training_compare | backend/masterquo/api/app.py:3199 | — |
| POST | `/api/v1/training/resume` | training_resume | backend/masterquo/api/app.py:3204 | tests |
| POST | `/api/v1/training/export` | training_export | backend/masterquo/api/app.py:3222 | — |
| GET | `/api/v1/training/exports/{name}` | training_export_file | backend/masterquo/api/app.py:3236 | — |
| POST | `/api/v1/training/import` | training_import | backend/masterquo/api/app.py:3246 | tests |
| POST | `/api/v1/training/sh/promote` | training_sh_promote | backend/masterquo/api/app.py:3259 | — |
| POST | `/api/v1/training/start` | training_start | backend/masterquo/api/app.py:3272 | — |
| POST | `/api/v1/training/cancel` | training_cancel | backend/masterquo/api/app.py:3481 | — |
| GET | `/api/v1/training/active` | training_active | backend/masterquo/api/app.py:3490 | — |
| POST | `/api/v1/training/rollback` | training_rollback | backend/masterquo/api/app.py:3516 | tests |

</details>

<details><summary><code>/api/v1/mm</code> – 5</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/mm/status` | mm_status | backend/masterquo/api/app.py:1884 | tests |
| GET | `/api/v1/mm/live` | mm_live | backend/masterquo/api/app.py:3118 | backend, tests |
| GET | `/api/v1/mm/job` | mm_job | backend/masterquo/api/app.py:3122 | tests |
| GET | `/api/v1/mm/ledger` | mm_ledger | backend/masterquo/api/app.py:3137 | tests |
| POST | `/api/v1/mm/rollback` | mm_rollback | backend/masterquo/api/app.py:3151 | tests |

</details>

<details><summary><code>/api/v1/zones</code> – 5</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/zones/map` | zones_map | backend/masterquo/api/app.py:1888 | backend, tests, frontend/src |
| GET | `/api/v1/zones/status` | zones_status | backend/masterquo/api/app.py:3078 | — |
| GET | `/api/v1/zones/events` | zones_events | backend/masterquo/api/app.py:3082 | — |
| GET | `/api/v1/zones/profiles` | zones_profiles | backend/masterquo/api/app.py:3086 | — |
| GET | `/api/v1/zones/context` | zones_context | backend/masterquo/api/app.py:3093 | backend, tests |

</details>

<details><summary><code>/api/v1/market-zones</code> – 9</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/market-zones` | market_zones | backend/masterquo/api/app.py:1913 | tools, tests, frontend/src |
| POST | `/api/v1/market-zones/compute` | market_zones_compute | backend/masterquo/api/app.py:1920 | tools, frontend/src |
| POST | `/api/v1/market-zones/live` | market_zones_live | backend/masterquo/api/app.py:1927 | frontend/src |
| POST | `/api/v1/market-zones/stop` | market_zones_stop | backend/masterquo/api/app.py:1934 | frontend/src |
| GET | `/api/v1/market-zones/job/{job_id}` | market_zones_job | backend/masterquo/api/app.py:1938 | — |
| GET | `/api/v1/market-zones/zone/{zone_id}` | market_zones_zone | backend/masterquo/api/app.py:1945 | — |
| GET | `/api/v1/market-zones/events` | market_zones_events | backend/masterquo/api/app.py:1952 | — |
| GET | `/api/v1/market-zones/bars` | market_zones_bars | backend/masterquo/api/app.py:1956 | tools, frontend/src |
| GET | `/api/v1/market-zones/as-of` | market_zones_as_of | backend/masterquo/api/app.py:1969 | tests |

</details>

<details><summary><code>/api/v1/trainhub</code> – 20</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/trainhub/components` | th_components | backend/masterquo/api/app.py:2012 | tests, frontend/src |
| POST | `/api/v1/trainhub/components/{cid}/jobs` | th_component_job | backend/masterquo/api/app.py:2016 | tests, frontend/src |
| POST | `/api/v1/trainhub/components/{cid}/cancel` | th_component_cancel | backend/masterquo/api/app.py:2028 | tests, frontend/src |
| POST | `/api/v1/trainhub/components/{cid}/activate` | th_component_activate | backend/masterquo/api/app.py:2032 | tests, frontend/src |
| POST | `/api/v1/trainhub/components/{cid}/rollback` | th_component_rollback | backend/masterquo/api/app.py:2040 | tests, frontend/src |
| GET | `/api/v1/trainhub/components/{cid}/export.zip` | th_component_export | backend/masterquo/api/app.py:2048 | tests, frontend/src |
| POST | `/api/v1/trainhub/components/{cid}/import` | th_component_import | backend/masterquo/api/app.py:2056 | tests, frontend/src |
| GET | `/api/v1/trainhub/status` | trainhub_status | backend/masterquo/api/app.py:2070 | frontend/src |
| POST | `/api/v1/trainhub/jobs` | trainhub_submit | backend/masterquo/api/app.py:2086 | frontend/src |
| GET | `/api/v1/trainhub/jobs` | trainhub_jobs | backend/masterquo/api/app.py:2093 | frontend/src |
| GET | `/api/v1/trainhub/jobs/{jid}` | trainhub_job | backend/masterquo/api/app.py:2097 | frontend/src |
| POST | `/api/v1/trainhub/jobs/{jid}/cancel` | trainhub_cancel | backend/masterquo/api/app.py:2104 | frontend/src |
| GET | `/api/v1/trainhub/data` | trainhub_data | backend/masterquo/api/app.py:2111 | — |
| GET | `/api/v1/trainhub/registry` | trainhub_registry | backend/masterquo/api/app.py:2118 | frontend/src |
| GET | `/api/v1/trainhub/version` | trainhub_version | backend/masterquo/api/app.py:2123 | — |
| POST | `/api/v1/trainhub/activate` | trainhub_activate | backend/masterquo/api/app.py:2137 | frontend/src |
| POST | `/api/v1/trainhub/rollback` | trainhub_rollback | backend/masterquo/api/app.py:2147 | frontend/src |
| POST | `/api/v1/trainhub/deactivate` | trainhub_deactivate | backend/masterquo/api/app.py:2155 | — |
| GET | `/api/v1/trainhub/package.zip` | trainhub_package_zip | backend/masterquo/api/app.py:2163 | — |
| GET | `/api/v1/trainhub/dataset.zip` | trainhub_dataset_zip | backend/masterquo/api/app.py:2176 | — |

</details>

<details><summary><code>/api/v1/models</code> – 20</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/models/catalog` | models_catalog | backend/masterquo/api/app.py:2190 | frontend/src |
| GET | `/api/v1/models/predictions` | models_predictions | backend/masterquo/api/app.py:2195 | tools, frontend/src |
| GET | `/api/v1/models/evidence` | models_evidence | backend/masterquo/api/app.py:2201 | tools |
| GET | `/api/v1/models/foundation` | tsfm_status | backend/masterquo/api/app.py:2355 | tools, tests |
| GET | `/api/v1/models/foundation/forecast` | tsfm_forecast | backend/masterquo/api/app.py:2366 | — |
| GET | `/api/v1/models/foundation/compare` | tsfm_compare | backend/masterquo/api/app.py:2370 | — |
| GET | `/api/v1/models/foundation/history` | tsfm_history | backend/masterquo/api/app.py:2374 | — |
| PUT | `/api/v1/models/foundation/settings` | tsfm_settings_put | backend/masterquo/api/app.py:2379 | — |
| POST | `/api/v1/models/foundation/install` | tsfm_install | backend/masterquo/api/app.py:2394 | — |
| POST | `/api/v1/models/foundation/verify` | tsfm_verify | backend/masterquo/api/app.py:2401 | — |
| POST | `/api/v1/models/foundation/refresh` | tsfm_refresh | backend/masterquo/api/app.py:2408 | — |
| POST | `/api/v1/models/foundation/validate` | tsfm_validate | backend/masterquo/api/app.py:2415 | tests |
| GET | `/api/v1/models/foundation/granite` | granite_get | backend/masterquo/api/app.py:2426 | tools |
| POST | `/api/v1/models/foundation/granite/train` | granite_train | backend/masterquo/api/app.py:2433 | — |
| POST | `/api/v1/models/foundation/granite/cancel` | granite_cancel | backend/masterquo/api/app.py:2446 | — |
| POST | `/api/v1/models/foundation/granite/activate` | granite_activate | backend/masterquo/api/app.py:2454 | — |
| POST | `/api/v1/models/foundation/granite/rollback` | granite_rollback | backend/masterquo/api/app.py:2465 | — |
| GET | `/api/v1/models/foundation/job/{name}` | tsfm_job | backend/masterquo/api/app.py:2470 | — |
| GET | `/api/v1/models/foundation/validation` | tsfm_validation | backend/masterquo/api/app.py:2476 | — |
| POST | `/api/v1/models/foundation/use` | tsfm_use | backend/masterquo/api/app.py:2484 | tests |

</details>

<details><summary><code>/api/v1/kronos</code> – 12</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/kronos` | kronos_status | backend/masterquo/api/app.py:2219 | tools, tests, frontend/src |
| GET | `/api/v1/kronos/forecast` | kronos_forecast | backend/masterquo/api/app.py:2228 | frontend/src |
| GET | `/api/v1/kronos/history` | kronos_history | backend/masterquo/api/app.py:2232 | — |
| PUT | `/api/v1/kronos/settings` | kronos_settings_put | backend/masterquo/api/app.py:2236 | frontend/src |
| POST | `/api/v1/kronos/enable` | kronos_enable | backend/masterquo/api/app.py:2247 | — |
| POST | `/api/v1/kronos/install` | kronos_install | backend/masterquo/api/app.py:2254 | — |
| POST | `/api/v1/kronos/verify` | kronos_verify | backend/masterquo/api/app.py:2264 | — |
| GET | `/api/v1/kronos/job/{name}` | kronos_job | backend/masterquo/api/app.py:2271 | — |
| POST | `/api/v1/kronos/refresh` | kronos_refresh | backend/masterquo/api/app.py:2277 | — |
| POST | `/api/v1/kronos/validate` | kronos_validate | backend/masterquo/api/app.py:2284 | tests |
| GET | `/api/v1/kronos/validation` | kronos_validation | backend/masterquo/api/app.py:2294 | — |
| POST | `/api/v1/kronos/strategy-use` | kronos_strategy_use | backend/masterquo/api/app.py:2302 | tests |

</details>

<details><summary><code>/api/v1/resources</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/resources` | resources_get | backend/masterquo/api/app.py:2328 | tools, frontend/src |
| PUT | `/api/v1/resources/profile` | resources_profile | backend/masterquo/api/app.py:2335 | tools, frontend/src |

</details>

<details><summary><code>/api/v1/indicators</code> – 9</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/indicators/status` | indicators_status | backend/masterquo/api/app.py:2499 | — |
| GET | `/api/v1/indicators/snapshot` | indicators_snapshot | backend/masterquo/api/app.py:2503 | tools |
| POST | `/api/v1/indicators/refresh` | indicators_refresh | backend/masterquo/api/app.py:2510 | — |
| GET | `/api/v1/indicators/chart` | indicators_chart | backend/masterquo/api/app.py:2514 | tools, frontend/src |
| GET | `/api/v1/indicators/dxy` | indicators_dxy | backend/masterquo/api/app.py:2518 | tools |
| GET | `/api/v1/indicators/anchors` | indicators_anchors | backend/masterquo/api/app.py:2523 | tools, tests |
| POST | `/api/v1/indicators/anchors` | indicators_anchor_add | backend/masterquo/api/app.py:2527 | tools, tests |
| DELETE | `/api/v1/indicators/anchors/{anchor_id}` | indicators_anchor_del | backend/masterquo/api/app.py:2541 | — |
| GET | `/api/v1/indicators/manifest` | indicators_manifest | backend/masterquo/api/app.py:2547 | — |

</details>

<details><summary><code>/api/v1/studio</code> – 5</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/studio/status` | studio_status | backend/masterquo/api/app.py:2578 | tools |
| POST | `/api/v1/studio/launch` | studio_launch | backend/masterquo/api/app.py:2582 | tools, tests |
| POST | `/api/v1/studio/import` | studio_import | backend/masterquo/api/app.py:2620 | tools, backend, tests |
| GET | `/api/v1/studio/imports` | studio_imports | backend/masterquo/api/app.py:2631 | tools, backend |
| DELETE | `/api/v1/studio/import/{import_id}` | studio_import_rollback | backend/masterquo/api/app.py:2636 | — |

</details>

<details><summary><code>/api/v1/families</code> – 9</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/families` | families_catalog | backend/masterquo/api/app.py:2674 | tools |
| GET | `/api/v1/families/{fid}/runs` | families_runs | backend/masterquo/api/app.py:2681 | tools |
| POST | `/api/v1/families/{fid}/train` | families_train | backend/masterquo/api/app.py:2685 | tools |
| POST | `/api/v1/families/train-all` | families_train_all | backend/masterquo/api/app.py:2689 | tools |
| POST | `/api/v1/families/{fid}/cancel` | families_cancel | backend/masterquo/api/app.py:2693 | tools |
| POST | `/api/v1/families/{fid}/activate` | families_activate | backend/masterquo/api/app.py:2697 | tools |
| POST | `/api/v1/families/{fid}/rollback` | families_rollback | backend/masterquo/api/app.py:2704 | tools |
| POST | `/api/v1/families/{fid}/use` | families_use | backend/masterquo/api/app.py:2708 | tools |
| GET | `/api/v1/families/predictions` | families_predictions | backend/masterquo/api/app.py:2712 | tools |

</details>

<details><summary><code>/api/v1/quant</code> – 14</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/quant/status` | quant_status | backend/masterquo/api/app.py:2723 | tools, backend |
| GET | `/api/v1/quant/predictions` | quant_predictions | backend/masterquo/api/app.py:2728 | tools |
| GET | `/api/v1/quant/assessment` | quant_assessments | backend/masterquo/api/app.py:2732 | tools, backend, tests |
| POST | `/api/v1/quant/assessment` | quant_assess | backend/masterquo/api/app.py:2738 | tools, backend, tests |
| GET | `/api/v1/quant/jobs` | quant_jobs | backend/masterquo/api/app.py:2751 | tests |
| POST | `/api/v1/quant/jobs` | quant_train | backend/masterquo/api/app.py:2756 | tests |
| POST | `/api/v1/quant/mode` | quant_mode | backend/masterquo/api/app.py:2767 | backend, tests |
| GET | `/api/v1/quant/tabicl` | quant_tabicl | backend/masterquo/api/app.py:2775 | tests, frontend/src |
| PUT | `/api/v1/quant/estimator` | quant_estimator | backend/masterquo/api/app.py:2779 | — |
| POST | `/api/v1/quant/tabicl/reconstruct` | quant_tabicl_reconstruct | backend/masterquo/api/app.py:2787 | tests, frontend/src |
| POST | `/api/v1/quant/tabicl/install` | quant_tabicl_install | backend/masterquo/api/app.py:2797 | frontend/src |
| POST | `/api/v1/quant/models/activate` | quant_activate | backend/masterquo/api/app.py:2948 | tests |
| POST | `/api/v1/quant/models/rollback` | quant_rollback | backend/masterquo/api/app.py:2960 | tests |
| GET | `/api/v1/quant/inventory` | quant_inventory | backend/masterquo/api/app.py:2966 | backend |

</details>

<details><summary><code>/api/v1/research-modules</code> – 10</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/research-modules` | research_status | backend/masterquo/api/app.py:2812 | tests, frontend/src |
| GET | `/api/v1/research-modules/settings` | research_settings | backend/masterquo/api/app.py:2816 | frontend/src |
| PUT | `/api/v1/research-modules/settings` | research_settings_put | backend/masterquo/api/app.py:2820 | frontend/src |
| GET | `/api/v1/research-modules/features` | research_features | backend/masterquo/api/app.py:2827 | — |
| GET | `/api/v1/research-modules/feature-graph` | research_graph | backend/masterquo/api/app.py:2833 | — |
| GET | `/api/v1/research-modules/optimizer/jobs` | research_opt_jobs | backend/masterquo/api/app.py:2837 | — |
| POST | `/api/v1/research-modules/optimizer/run` | research_opt_run | backend/masterquo/api/app.py:2841 | frontend/src |
| POST | `/api/v1/research-modules/parameters/rollback` | research_rollback | backend/masterquo/api/app.py:2850 | frontend/src |
| POST | `/api/v1/research-modules/sdformerflow/train` | research_sdf_train | backend/masterquo/api/app.py:2854 | tests, frontend/src |
| POST | `/api/v1/research-modules/sdformerflow/cancel` | research_sdf_cancel | backend/masterquo/api/app.py:2870 | frontend/src |

</details>

<details><summary><code>/api/v1/baskets</code> – 12</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/baskets` | baskets_list | backend/masterquo/api/app.py:2882 | tools, backend, tests, frontend/src |
| GET | `/api/v1/baskets/catalog` | baskets_catalog | backend/masterquo/api/app.py:2887 | tests, frontend/src |
| GET | `/api/v1/baskets/settings` | baskets_settings | backend/masterquo/api/app.py:2892 | backend, frontend/src |
| PUT | `/api/v1/baskets/settings` | baskets_settings_put | backend/masterquo/api/app.py:2896 | backend, frontend/src |
| GET | `/api/v1/baskets/signals` | baskets_signals | backend/masterquo/api/app.py:2903 | tools, backend, frontend/src |
| GET | `/api/v1/baskets/declared/{profile}` | baskets_declared | backend/masterquo/api/app.py:2907 | tests |
| POST | `/api/v1/baskets/declared/{profile}` | baskets_declare | backend/masterquo/api/app.py:2911 | tests |
| DELETE | `/api/v1/baskets/declared/{item_id}` | baskets_undeclare | backend/masterquo/api/app.py:2923 | tests |
| GET | `/api/v1/baskets/otc` | baskets_otc | backend/masterquo/api/app.py:2931 | backend, tests |
| PUT | `/api/v1/baskets/otc/meta` | baskets_otc_meta | backend/masterquo/api/app.py:2936 | — |
| POST | `/api/v1/baskets/otc/ticks` | baskets_otc_ticks | backend/masterquo/api/app.py:2940 | backend, tests |
| POST | `/api/v1/baskets/otc/payoff` | baskets_otc_payoff | backend/masterquo/api/app.py:2944 | — |

</details>

<details><summary><code>/api/v1/svp</code> – 20</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/svp/status` | svp_status | backend/masterquo/api/app.py:2982 | — |
| GET | `/api/v1/svp/profiles` | svp_profiles | backend/masterquo/api/app.py:2986 | tools, tests |
| POST | `/api/v1/svp/profiles` | svp_profile_create | backend/masterquo/api/app.py:2990 | tools, tests |
| PATCH | `/api/v1/svp/profiles/{pid}` | svp_profile_update | backend/masterquo/api/app.py:2994 | tools |
| DELETE | `/api/v1/svp/profiles/{pid}` | svp_profile_delete | backend/masterquo/api/app.py:2998 | tools |
| POST | `/api/v1/svp/profiles/{pid}/copy-settings` | svp_profile_copy | backend/masterquo/api/app.py:3004 | tools |
| GET | `/api/v1/svp/profiles/{pid}/compute` | svp_profile_compute | backend/masterquo/api/app.py:3008 | tools |
| POST | `/api/v1/svp/profiles/{pid}/freeze` | svp_profile_freeze | backend/masterquo/api/app.py:3012 | tools |
| POST | `/api/v1/svp/profiles/{pid}/live` | svp_profile_live | backend/masterquo/api/app.py:3016 | tools |
| POST | `/api/v1/svp/profiles/{pid}/ai-live` | svp_profile_ai_live | backend/masterquo/api/app.py:3020 | tools |
| POST | `/api/v1/svp/profiles/{pid}/zones-now` | svp_zones_now | backend/masterquo/api/app.py:3024 | tools |
| POST | `/api/v1/svp/profiles/{pid}/ai-propose` | svp_ai_propose | backend/masterquo/api/app.py:3028 | tools |
| GET | `/api/v1/svp/visible` | svp_visible | backend/masterquo/api/app.py:3034 | frontend/src |
| GET | `/api/v1/svp/zones` | svp_zones | backend/masterquo/api/app.py:3041 | tools, tests, frontend/src |
| POST | `/api/v1/svp/zones` | svp_zone_create | backend/masterquo/api/app.py:3052 | tools, tests, frontend/src |
| PATCH | `/api/v1/svp/zones/{zid}` | svp_zone_edit | backend/masterquo/api/app.py:3056 | — |
| DELETE | `/api/v1/svp/zones/{zid}` | svp_zone_delete | backend/masterquo/api/app.py:3060 | — |
| GET | `/api/v1/svp/zones/{zid}/history` | svp_zone_history | backend/masterquo/api/app.py:3066 | — |
| POST | `/api/v1/svp/clear-auto` | svp_clear_auto | backend/masterquo/api/app.py:3070 | — |
| GET | `/api/v1/svp/ai-jobs` | svp_ai_jobs | backend/masterquo/api/app.py:3074 | — |

</details>

<details><summary><code>/api/v1/eval</code> – 4</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/eval/status` | eval_status | backend/masterquo/api/app.py:3099 | tools |
| GET | `/api/v1/eval/assessments` | eval_assessments | backend/masterquo/api/app.py:3103 | tools |
| GET | `/api/v1/eval/report` | eval_report | backend/masterquo/api/app.py:3110 | tools |
| GET | `/api/v1/eval/exposure` | eval_exposure | backend/masterquo/api/app.py:3114 | — |

</details>

<details><summary><code>/api/v1/license</code> – 3</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/license/status` | license_status | backend/masterquo/api/app.py:3327 | tests, frontend/src |
| POST | `/api/v1/license/activate` | license_activate | backend/masterquo/api/app.py:3331 | tests, frontend/src |
| POST | `/api/v1/license/require` | license_require | backend/masterquo/api/app.py:3338 | tests, frontend/src |

</details>

<details><summary><code>/api/v1/pepe-training</code> – 6</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/pepe-training` | pepe_training_status | backend/masterquo/api/app.py:3346 | frontend/src |
| POST | `/api/v1/pepe-training/train` | pepe_training_train | backend/masterquo/api/app.py:3350 | frontend/src |
| PUT | `/api/v1/pepe-training/settings` | pepe_training_settings | backend/masterquo/api/app.py:3360 | frontend/src |
| POST | `/api/v1/pepe-training/cancel` | pepe_training_cancel | backend/masterquo/api/app.py:3367 | frontend/src |
| POST | `/api/v1/pepe-training/remove` | pepe_training_remove | backend/masterquo/api/app.py:3371 | frontend/src |
| GET | `/api/v1/pepe-training/log` | pepe_training_log | backend/masterquo/api/app.py:3375 | frontend/src |

</details>

<details><summary><code>/api/v1/export</code> – 5</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/export/start` | export_start | backend/masterquo/api/app.py:3392 | — |
| GET | `/api/v1/export/status` | export_status | backend/masterquo/api/app.py:3400 | — |
| POST | `/api/v1/export/cancel` | export_cancel | backend/masterquo/api/app.py:3405 | — |
| GET | `/api/v1/export/datasets` | export_datasets | backend/masterquo/api/app.py:3410 | — |
| GET | `/api/v1/export/readiness` | export_readiness | backend/masterquo/api/app.py:3417 | — |

</details>

<details><summary><code>/api/v1/montecarlo</code> – 4</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/montecarlo/status` | montecarlo_status | backend/masterquo/api/app.py:3426 | tests, frontend/src |
| GET | `/api/v1/montecarlo/validations/{run_id}/report` | montecarlo_validation_report | backend/masterquo/api/app.py:3430 | frontend/src |
| GET | `/api/v1/montecarlo/scenarios` | montecarlo_scenarios | backend/masterquo/api/app.py:3453 | tests |
| POST | `/api/v1/montecarlo/run` | montecarlo_run | backend/masterquo/api/app.py:3458 | backend, tests |

</details>

<details><summary><code>/api/v1/liquidity</code> – 6</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/liquidity/sessions` | liq_sessions | backend/masterquo/api/app.py:3545 | frontend/src |
| GET | `/api/v1/liquidity/heatmap` | liq_heatmap | backend/masterquo/api/app.py:3559 | — |
| GET | `/api/v1/liquidity/context` | liq_context | backend/masterquo/api/app.py:3563 | — |
| PUT | `/api/v1/liquidity/source` | liq_source | backend/masterquo/api/app.py:3578 | — |
| PUT | `/api/v1/liquidity/key` | liq_key | backend/masterquo/api/app.py:3592 | tests |
| POST | `/api/v1/liquidity/poll` | liq_poll | backend/masterquo/api/app.py:3600 | tests |

</details>

<details><summary><code>/api/v1/playbook</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/playbook` | playbook | backend/masterquo/api/app.py:3895 | tests |

</details>

<details><summary><code>/api/v1/appearance</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/appearance/assets` | appearance_assets | backend/masterquo/api/app.py:3910 | tests, frontend/src |
| POST | `/api/v1/appearance/upload` | appearance_upload | backend/masterquo/api/app.py:3922 | tests |

</details>

<details><summary><code>/api/v1/auto</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/auto` | set_auto | backend/masterquo/api/app.py:3947 | — |

</details>

<details><summary><code>/api/v1/kill</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/kill` | kill | backend/masterquo/api/app.py:3954 | frontend/src |

</details>

<details><summary><code>/api/v1/execute</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/execute` | execute | backend/masterquo/api/app.py:3960 | — |

</details>

<details><summary><code>/api/v1/positions</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/positions/close` | close_positions | backend/masterquo/api/app.py:3964 | frontend/src |
| POST | `/api/v1/positions/{ticket}/adopt` | adopt | backend/masterquo/api/app.py:3970 | frontend/src |

</details>

<details><summary><code>/api/v1/mt5</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/mt5/reconnect` | reconnect | backend/masterquo/api/app.py:3976 | frontend/src |

</details>

<details><summary><code>/api/v1/diagnostics</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/diagnostics` | diagnostics | backend/masterquo/api/app.py:3986 | tests |

</details>

<details><summary><code>/api/v1/telegram</code> – 6</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/telegram` | telegram_status | backend/masterquo/api/app.py:3999 | backend, tests |
| GET | `/api/v1/telegram/template` | telegram_template_get | backend/masterquo/api/app.py:4003 | tests |
| PUT | `/api/v1/telegram/template` | telegram_template_put | backend/masterquo/api/app.py:4008 | tests |
| POST | `/api/v1/telegram/preview` | telegram_preview | backend/masterquo/api/app.py:4017 | tests |
| POST | `/api/v1/telegram/test` | telegram_test | backend/masterquo/api/app.py:4025 | tests |
| POST | `/api/v1/telegram/stats-now` | telegram_stats_now | backend/masterquo/api/app.py:4034 | — |

</details>

<details><summary><code>/api/v1/system</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/system/resources` | system_resources | backend/masterquo/api/app.py:4040 | tests |

</details>

<details><summary><code>/api/v1/presets</code> – 4</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/presets/strategy` | presets_list | backend/masterquo/api/app.py:4046 | tests |
| POST | `/api/v1/presets/strategy` | presets_save | backend/masterquo/api/app.py:4054 | tests |
| POST | `/api/v1/presets/strategy/load` | presets_load | backend/masterquo/api/app.py:4063 | tests |
| POST | `/api/v1/presets/strategy/reset` | presets_reset | backend/masterquo/api/app.py:4072 | tests |

</details>

<details><summary><code>/api/v1/desktop</code> – 3</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/desktop` | desktop_get | backend/masterquo/api/app.py:4090 | tests |
| POST | `/api/v1/desktop/prefs` | desktop_prefs | backend/masterquo/api/app.py:4094 | tests |
| POST | `/api/v1/desktop/restart-engine` | desktop_restart | backend/masterquo/api/app.py:4106 | tests |

</details>

<details><summary><code>/api/v1/admin</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/admin/shutdown` | shutdown | backend/masterquo/api/app.py:4116 | desktop, backend, frontend/src |

</details>

<details><summary><code>/api/v1/ws</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| WS | `/api/v1/ws` | ws | backend/masterquo/api/app.py:4124 | tests, frontend/src |

</details>

### backend/masterquo/api/export_routes.py (4 tras)

<details><summary><code>/api/v1/exports</code> – 4</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/exports` | exports_index | backend/masterquo/api/export_routes.py:31 | backend, tests |
| GET | `/api/v1/exports/{name}/{export_id}/manifest` | export_manifest | backend/masterquo/api/export_routes.py:39 | backend, tests |
| GET | `/api/v1/exports/{name}` | export_run | backend/masterquo/api/export_routes.py:52 | backend, tests |
| POST | `/api/v1/exports/trader-life-game/import` | tlg_import | backend/masterquo/api/export_routes.py:70 | tests |

</details>

### backend/masterquo/api/owner_routes.py (9 tras)

<details><summary><code>/api/v1/owner</code> – 9</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/owner/license/state` | owner_license_state | backend/masterquo/api/owner_routes.py:22 | tests, frontend/src |
| POST | `/api/v1/owner/license/keys` | owner_license_create_keys | backend/masterquo/api/owner_routes.py:26 | tests, frontend/src |
| POST | `/api/v1/owner/license/keys/export` | owner_license_export_key | backend/masterquo/api/owner_routes.py:30 | tests, frontend/src |
| POST | `/api/v1/owner/license/keys/import` | owner_license_import_key | backend/masterquo/api/owner_routes.py:34 | tests, frontend/src |
| GET | `/api/v1/owner/license/hwid` | owner_license_hwid | backend/masterquo/api/owner_routes.py:40 | tests, frontend/src |
| POST | `/api/v1/owner/license/generate` | owner_license_generate | backend/masterquo/api/owner_routes.py:44 | tests, frontend/src |
| POST | `/api/v1/owner/license/check` | owner_license_check | backend/masterquo/api/owner_routes.py:52 | tests, frontend/src |
| GET | `/api/v1/owner/licenses` | owner_licenses | backend/masterquo/api/owner_routes.py:59 | tests, frontend/src |
| DELETE | `/api/v1/owner/licenses/{rid}` | owner_license_delete | backend/masterquo/api/owner_routes.py:63 | tests, frontend/src |

</details>

### backend/masterquo/api/wf32_routes.py (71 tras)

<details><summary><code>/api/v1/tlg</code> – 36</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/tlg/meta` | tlg_meta | backend/masterquo/api/wf32_routes.py:41 | tests, frontend/src |
| GET | `/api/v1/tlg/state` | tlg_state | backend/masterquo/api/wf32_routes.py:45 | tests, frontend/src |
| POST | `/api/v1/tlg/profile` | tlg_profile_create | backend/masterquo/api/wf32_routes.py:52 | tests, frontend/src |
| PUT | `/api/v1/tlg/profile` | tlg_profile_update | backend/masterquo/api/wf32_routes.py:56 | tests, frontend/src |
| GET | `/api/v1/tlg/xp` | tlg_xp | backend/masterquo/api/wf32_routes.py:60 | tests |
| GET | `/api/v1/tlg/journal` | tlg_journal | backend/masterquo/api/wf32_routes.py:64 | frontend/src |
| PUT | `/api/v1/tlg/journal/{ref}` | tlg_annotate | backend/masterquo/api/wf32_routes.py:68 | frontend/src |
| GET | `/api/v1/tlg/notes` | tlg_notes | backend/masterquo/api/wf32_routes.py:72 | tests, frontend/src |
| POST | `/api/v1/tlg/notes/{kind}` | tlg_note | backend/masterquo/api/wf32_routes.py:76 | tests, frontend/src |
| GET | `/api/v1/tlg/academy` | tlg_academy | backend/masterquo/api/wf32_routes.py:80 | frontend/src |
| POST | `/api/v1/tlg/academy/lesson/{lesson_id}` | tlg_lesson | backend/masterquo/api/wf32_routes.py:84 | frontend/src |
| POST | `/api/v1/tlg/academy/quiz/{level}` | tlg_quiz | backend/masterquo/api/wf32_routes.py:88 | frontend/src |
| GET | `/api/v1/tlg/academy/risk` | tlg_risk | backend/masterquo/api/wf32_routes.py:92 | frontend/src |
| POST | `/api/v1/tlg/academy/risk` | tlg_risk_submit | backend/masterquo/api/wf32_routes.py:96 | frontend/src |
| GET | `/api/v1/tlg/quests` | tlg_quests | backend/masterquo/api/wf32_routes.py:100 | tests, frontend/src |
| POST | `/api/v1/tlg/quests/{quest_id}/claim` | tlg_claim | backend/masterquo/api/wf32_routes.py:104 | tests, frontend/src |
| GET | `/api/v1/tlg/skills` | tlg_skills | backend/masterquo/api/wf32_routes.py:108 | frontend/src |
| POST | `/api/v1/tlg/skills/{skill_id}` | tlg_unlock | backend/masterquo/api/wf32_routes.py:112 | frontend/src |
| GET | `/api/v1/tlg/calendar` | tlg_calendar | backend/masterquo/api/wf32_routes.py:116 | frontend/src |
| GET | `/api/v1/tlg/coach` | tlg_coach | backend/masterquo/api/wf32_routes.py:120 | frontend/src |
| POST | `/api/v1/tlg/coach/memory` | tlg_mem_add | backend/masterquo/api/wf32_routes.py:124 | frontend/src |
| DELETE | `/api/v1/tlg/coach/memory` | tlg_mem_del | backend/masterquo/api/wf32_routes.py:128 | frontend/src |
| GET | `/api/v1/tlg/sim` | tlg_sims | backend/masterquo/api/wf32_routes.py:132 | tests, frontend/src |
| POST | `/api/v1/tlg/sim` | tlg_sim_start | backend/masterquo/api/wf32_routes.py:136 | tests, frontend/src |
| GET | `/api/v1/tlg/sim/{sid}` | tlg_sim_view | backend/masterquo/api/wf32_routes.py:141 | tests, frontend/src |
| POST | `/api/v1/tlg/sim/{sid}/step` | tlg_sim_step | backend/masterquo/api/wf32_routes.py:145 | tests, frontend/src |
| POST | `/api/v1/tlg/sim/{sid}/open` | tlg_sim_open | backend/masterquo/api/wf32_routes.py:149 | tests, frontend/src |
| POST | `/api/v1/tlg/sim/{sid}/close/{trade_id}` | tlg_sim_close | backend/masterquo/api/wf32_routes.py:154 | tests, frontend/src |
| POST | `/api/v1/tlg/sim/{sid}/finish` | tlg_sim_finish | backend/masterquo/api/wf32_routes.py:158 | tests, frontend/src |
| GET | `/api/v1/tlg/lifestyle` | tlg_life | backend/masterquo/api/wf32_routes.py:162 | frontend/src |
| POST | `/api/v1/tlg/lifestyle/{item_id}/buy` | tlg_buy | backend/masterquo/api/wf32_routes.py:166 | frontend/src |
| POST | `/api/v1/tlg/lifestyle/{item_id}/equip` | tlg_equip | backend/masterquo/api/wf32_routes.py:170 | frontend/src |
| GET | `/api/v1/tlg/leaderboard` | tlg_board | backend/masterquo/api/wf32_routes.py:174 | tests, frontend/src |
| GET | `/api/v1/tlg/loot/catalog` | loot_catalog | backend/masterquo/api/wf32_routes.py:651 | tests |
| POST | `/api/v1/tlg/loot/evaluate` | loot_evaluate | backend/masterquo/api/wf32_routes.py:665 | tests |
| POST | `/api/v1/tlg/loot/grant` | loot_grant | backend/masterquo/api/wf32_routes.py:669 | — |

</details>

<details><summary><code>/api/v1/indicators</code> – 3</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/indicators/catalog` | ind_catalog | backend/masterquo/api/wf32_routes.py:192 | tests |
| POST | `/api/v1/indicators/calculate` | ind_calculate | backend/masterquo/api/wf32_routes.py:196 | tests |
| GET | `/api/v1/indicators/diagnostics` | ind_diag | backend/masterquo/api/wf32_routes.py:222 | tests |

</details>

<details><summary><code>/api/v1/session-context</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/session-context` | session_ctx | backend/masterquo/api/wf32_routes.py:240 | tests |
| GET | `/api/v1/session-context/boxes` | session_boxes | backend/masterquo/api/wf32_routes.py:250 | tests |

</details>

<details><summary><code>/api/v1/markets</code> – 5</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/markets/v2` | markets_v2 | backend/masterquo/api/wf32_routes.py:289 | tests |
| GET | `/api/v1/markets/v2/fomo-universe` | fomo_universe | backend/masterquo/api/wf32_routes.py:294 | — |
| GET | `/api/v1/markets/v2/{market}/instruments` | market_instruments | backend/masterquo/api/wf32_routes.py:305 | — |
| GET | `/api/v1/markets/v2/{market}/candles` | market_candles | backend/masterquo/api/wf32_routes.py:309 | — |
| GET | `/api/v1/markets/v2/{market}/context` | market_context | backend/masterquo/api/wf32_routes.py:313 | — |

</details>

<details><summary><code>/api/v1/orderflow</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/orderflow/{market}/workspace` | orderflow_workspace | backend/masterquo/api/wf32_routes.py:317 | tests |

</details>

<details><summary><code>/api/v1/models</code> – 5</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/models/pt/evaluate` | pt_evaluate | backend/masterquo/api/wf32_routes.py:351 | backend, tests |
| GET | `/api/v1/models/association/snapshot` | ar_snapshot | backend/masterquo/api/wf32_routes.py:365 | tests |
| GET | `/api/v1/models/dt-ranker/status` | dtr_status | backend/masterquo/api/wf32_routes.py:382 | tests |
| POST | `/api/v1/models/dt-ranker/rank` | dtr_rank | backend/masterquo/api/wf32_routes.py:387 | backend, tests |
| GET | `/api/v1/models/bat/shadow` | bat_shadow | backend/masterquo/api/wf32_routes.py:400 | tests |

</details>

<details><summary><code>/api/v1/strategy-roi</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/strategy-roi` | strategy_roi | backend/masterquo/api/wf32_routes.py:410 | tests |

</details>

<details><summary><code>/api/v1/forecast</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/forecast/long-horizon` | long_horizon | backend/masterquo/api/wf32_routes.py:417 | tests |

</details>

<details><summary><code>/api/v1/change-points</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/change-points` | change_points | backend/masterquo/api/wf32_routes.py:432 | tests |

</details>

<details><summary><code>/api/v1/bootstrap</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/bootstrap` | bootstrap_status | backend/masterquo/api/wf32_routes.py:446 | tests |
| PUT | `/api/v1/bootstrap` | bootstrap_profile | backend/masterquo/api/wf32_routes.py:454 | tests |

</details>

<details><summary><code>/api/v1/desktop</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/desktop/display` | desktop_display | backend/masterquo/api/wf32_routes.py:464 | — |

</details>

<details><summary><code>/api/v1/telegram</code> – 5</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/telegram/account` | tg_account | backend/masterquo/api/wf32_routes.py:557 | backend, tests |
| POST | `/api/v1/telegram/account/bind` | tg_bind | backend/masterquo/api/wf32_routes.py:561 | — |
| POST | `/api/v1/telegram/account/unbind` | tg_unbind | backend/masterquo/api/wf32_routes.py:565 | — |
| PUT | `/api/v1/telegram/account` | tg_update | backend/masterquo/api/wf32_routes.py:569 | backend, tests |
| PUT | `/api/v1/telegram/account/templates/{kind}` | tg_template | backend/masterquo/api/wf32_routes.py:573 | tests |

</details>

<details><summary><code>/api/v1/strategy-filter</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/strategy-filter/status` | sfb_status | backend/masterquo/api/wf32_routes.py:582 | tests |
| PUT | `/api/v1/strategy-filter/config` | sfb_config | backend/masterquo/api/wf32_routes.py:589 | tests |

</details>

<details><summary><code>/api/v1/relationships</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/relationships/candidates` | rel_candidates | backend/masterquo/api/wf32_routes.py:611 | tests |
| GET | `/api/v1/relationships/pair` | rel_pair | backend/masterquo/api/wf32_routes.py:615 | — |

</details>

<details><summary><code>/api/v1/market-trap</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/market-trap` | market_trap | backend/masterquo/api/wf32_routes.py:619 | tests |

</details>

<details><summary><code>/api/v1/smma-cci</code> – 1</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| GET | `/api/v1/smma-cci` | smma_cci | backend/masterquo/api/wf32_routes.py:625 | tests |

</details>

<details><summary><code>/api/v1/asge</code> – 2</summary>

| metoda | ścieżka | handler | miejsce | użycie |
|---|---|---|---|---|
| POST | `/api/v1/asge/run` | asge_run | backend/masterquo/api/wf32_routes.py:633 | tests |
| GET | `/api/v1/asge/ledger` | asge_ledger | backend/masterquo/api/wf32_routes.py:647 | tests |

</details>

### Studio – osobna aplikacja `backend/masterquo/studio/app.py` (10 tras + mount /assets)

| metoda | ścieżka | handler | miejsce |
|---|---|---|---|
| GET | `/api/studio/health` | health | backend/masterquo/studio/app.py:134 |
| GET | `/api/studio/connections` | connections | backend/masterquo/studio/app.py:139 |
| POST | `/api/studio/settings` | settings_save | backend/masterquo/studio/app.py:153 |
| GET | `/api/studio/models` | models | backend/masterquo/studio/app.py:160 |
| GET | `/api/studio/matrix` | matrix | backend/masterquo/studio/app.py:165 |
| POST | `/api/studio/jobs` | submit | backend/masterquo/studio/app.py:171 |
| GET | `/api/studio/jobs` | jobs | backend/masterquo/studio/app.py:190 |
| POST | `/api/studio/jobs/{jid}/{action}` | job_action | backend/masterquo/studio/app.py:194 |
| GET | `/api/studio/jobs/{jid}/report` | report | backend/masterquo/studio/app.py:209 |
| GET | `/` | index | backend/masterquo/studio/app.py:253 |

## C. Panel (frontend/src)

Routing hash: `frontend/src/router.ts` (parse:38, navigate:51); rozdzielenie widoków: `frontend/src/App.tsx:45-60`.

| trasa | etykieta | komponent |
|---|---|---|
| `#/menu` | Menu główne | features/cinematic/CinematicMenu.tsx (+ SystemBar ExecStatus/SystemIcons) |
| `#/forex` | FOREX | features/forex/ForexScene.tsx |
| `#/system` | Panele systemowe | features/system/SystemDrawer.tsx (szuflada nad ekranem źródłowym, `?p=…&from=…`) |
| `#/trader-life-game` | TraderLifeGame | features/trader-life-game/TraderLifeGame.tsx |

| ekran FOREX `#/forex?s=` | komponent |
|---|---|
| `charts` | features/forex/screens/charts/ChartsScreen.tsx |
| `signals` | features/forex/screens/SignalsScreen.tsx |
| `models` | features/forex/screens/ModelsScreen.tsx |
| `roi` | features/forex/screens/RoiScreen.tsx |

| panel systemowy `#/system?p=` | komponent (SystemDrawer.tsx:52-58) |
|---|---|
| `settings` | components/Dialogs.tsx SettingsModal |
| `mode` | components/Dialogs.tsx ModeDialog |
| `stop` | components/Dialogs.tsx PowerDialog |
| `diagnostics` | features/system/DiagnosticsPanel.tsx |
| `training` | features/system/TrainingCenterPanel.tsx |
| `license` | features/system/LicensePanel.tsx (OWNER: LicenseGeneratorPanel.tsx) |

Przekierowania starych adresów 1.41 (`LEGACY_REDIRECTS`, router.ts:19-33): 53 – `galaxy`→menu, `neural-city`→menu, `lightning`→menu, `wind`→menu, `control`→menu, `strategy-lab`→menu, `nc`→menu, `pepe-wtc`→forex?s=charts, `wtc`→forex?s=charts, `wykresy`→forex?s=charts, `precision`→forex?s=charts, `strefy`→forex?s=charts, `scalp-mtf`→forex?s=charts, `indykatory`→forex?s=charts, `dxy`→forex?s=charts, `svp`→forex?s=charts, `kontekst`→forex?s=charts, `market-news`→forex?s=charts, `trading-intelligence`→forex?s=charts, `pepe-signal`→forex?s=signals, `signal`→forex?s=signals, `brain-signal`→forex?s=signals, `sygnal`→forex?s=signals, `setupy`→forex?s=signals, `warunki`→forex?s=signals, `strategie`→forex?s=signals, `ai`→forex?s=signals, `formacje`→forex?s=signals, `dyscypline`→forex?s=signals, `decyzje`→forex?s=signals, `modele`→forex?s=models, `trening`→forex?s=models, `training-lab`→forex?s=models, `neural`→forex?s=models, `struktura`→forex?s=models, `testy`→forex?s=models, `badania`→forex?s=models, `ai-neural-lab`→forex?s=models, `profits`→forex?s=roi, `pepe-roi`→forex?s=roi, `leaderboard`→forex?s=roi, `pozycje`→forex?s=roi, `dziennik`→forex?s=roi, `pulpit`→forex?s=roi, `pepe-bank`→forex?s=roi, `ustawienia`→system?p=settings, `settings`→system?p=settings, `licencje`→system?p=settings, `dane`→system?p=settings, `system-control`→system?p=mode, `diagnostyka`→system?p=diagnostics, `otc`→menu?retired=otc, `otc-gold`→menu?retired=otc

Osobne wejścia Vite (`frontend/vite.config.ts`): `index.html` (panel), `studio.html` → `src/studio/main.tsx` (Studio, API `/api/studio/*`), `charts-test.html` (tylko `--mode test`). Licencja: `src/license/LicenseGate.tsx`, `LicenseScreen.tsx`. WebSocket: `src/api.ts:54 LiveSocket` (jeden, w `store.tsx`).

Wywołania API z panelu (unikalne ścieżki backendu): `/api/studio/connections`, `/api/studio/jobs`, `/api/studio/jobs/{jid}/report`, `/api/studio/jobs/{jid}/{action}`, `/api/studio/models`, `/api/v1/admin/shutdown`, `/api/v1/agent/models`, `/api/v1/agent/test`, `/api/v1/analytics/diagnostics`, `/api/v1/appearance/assets`, `/api/v1/baskets`, `/api/v1/baskets/catalog`, `/api/v1/baskets/settings`, `/api/v1/baskets/signals`, `/api/v1/bot-signals`, `/api/v1/candles`, `/api/v1/config`, `/api/v1/decision`, `/api/v1/indicator-context/chart`, `/api/v1/indicators/chart`, `/api/v1/kill`, `/api/v1/kronos`, `/api/v1/kronos/forecast`, `/api/v1/kronos/settings`, `/api/v1/license/activate`, `/api/v1/license/require`, `/api/v1/license/status`, `/api/v1/liquidity/sessions`, `/api/v1/market-zones`, `/api/v1/market-zones/bars`, `/api/v1/market-zones/compute`, `/api/v1/market-zones/live`, `/api/v1/market-zones/stop`, `/api/v1/ml/mode`, `/api/v1/mode`, `/api/v1/mode/primary-path`, `/api/v1/models/catalog`, `/api/v1/models/predictions`, `/api/v1/montecarlo/status`, `/api/v1/montecarlo/validations/{run_id}/report`, `/api/v1/mt5/reconnect`, `/api/v1/owner/license/check`, `/api/v1/owner/license/generate`, `/api/v1/owner/license/hwid`, `/api/v1/owner/license/keys`, `/api/v1/owner/license/keys/export`, `/api/v1/owner/license/keys/import`, `/api/v1/owner/license/state`, `/api/v1/owner/licenses`, `/api/v1/owner/licenses/{rid}`, `/api/v1/pepe-training`, `/api/v1/pepe-training/cancel`, `/api/v1/pepe-training/log`, `/api/v1/pepe-training/remove`, `/api/v1/pepe-training/settings`, `/api/v1/pepe-training/train`, `/api/v1/plans/chart`, `/api/v1/positions/close`, `/api/v1/prefs`, `/api/v1/prefs/leverage`, `/api/v1/quant/tabicl`, `/api/v1/quant/tabicl/install`, `/api/v1/quant/tabicl/reconstruct`, `/api/v1/research-modules`, `/api/v1/research-modules/optimizer/run`, `/api/v1/research-modules/parameters/rollback`, `/api/v1/research-modules/sdformerflow/cancel`, `/api/v1/research-modules/sdformerflow/train`, `/api/v1/research-modules/settings`, `/api/v1/resources`, `/api/v1/resources/profile`, `/api/v1/secrets`, `/api/v1/secrets/anthropic`, `/api/v1/session`, `/api/v1/setups`, `/api/v1/sh/config`, `/api/v1/sh/signals`, `/api/v1/sh/strategies`, `/api/v1/sh/validation`, `/api/v1/state`, `/api/v1/stats`, `/api/v1/strategy/auto`, `/api/v1/strategy/mode`, `/api/v1/structure`, `/api/v1/svp/visible`, `/api/v1/svp/zones`, `/api/v1/timeframes`, `/api/v1/tlg/academy`, `/api/v1/tlg/academy/lesson/{lesson_id}`, `/api/v1/tlg/academy/quiz/{level}`, `/api/v1/tlg/academy/risk`, `/api/v1/tlg/calendar`, `/api/v1/tlg/coach`, `/api/v1/tlg/coach/memory`, `/api/v1/tlg/journal`, `/api/v1/tlg/journal/{ref}`, `/api/v1/tlg/leaderboard`, `/api/v1/tlg/lifestyle`, `/api/v1/tlg/lifestyle/{item_id}/buy`, `/api/v1/tlg/lifestyle/{item_id}/equip`, `/api/v1/tlg/meta`, `/api/v1/tlg/notes/{kind}`, `/api/v1/tlg/profile`, `/api/v1/tlg/quests`, `/api/v1/tlg/quests/{quest_id}/claim`, `/api/v1/tlg/sim`, `/api/v1/tlg/sim/{sid}`, `/api/v1/tlg/sim/{sid}/close/{trade_id}`, `/api/v1/tlg/sim/{sid}/finish`, `/api/v1/tlg/sim/{sid}/open`, `/api/v1/tlg/sim/{sid}/step`, `/api/v1/tlg/skills`, `/api/v1/tlg/skills/{skill_id}`, `/api/v1/tlg/state`, `/api/v1/trainhub/activate`, `/api/v1/trainhub/components`, `/api/v1/trainhub/components/{cid}/activate`, `/api/v1/trainhub/components/{cid}/cancel`, `/api/v1/trainhub/components/{cid}/export.zip`, `/api/v1/trainhub/components/{cid}/import`, `/api/v1/trainhub/components/{cid}/jobs`, `/api/v1/trainhub/components/{cid}/rollback`, `/api/v1/trainhub/jobs`, `/api/v1/trainhub/jobs/{jid}/cancel`, `/api/v1/trainhub/registry`, `/api/v1/trainhub/rollback`, `/api/v1/trainhub/status`, `/api/v1/zones/map`

## D. Skrypty `*.bat` (katalog główny) i `tools/*.cmd`

Każde wywołanie `-m masterquo …` / `-m gold_candles_runtime.*` zostało sprawdzone prawdziwym parserem argparse (zmienne %ASSET%, %COMM% … podstawione przykładowymi wartościami); `call`/uruchomienia plików – sprawdzone istnienie pliku.

| plik | co uruchamia (linia: polecenie) | wynik sprawdzenia |
|---|---|---|
| 00_TRENING_START.bat | 23: `tools/trening.cmd menu` | OK×1 |
| 01_INSTALUJ.bat | 36: `tools/check_python.py `<br>46: `tools/check_python.py `<br>57: `tools/check_python.py `<br>75: `tools/check_python.py `<br>88: `-m venv "%ROOT%.venv"`<br>100: `-m pip install --disable-pip-version-check --no-input --require-hashes --only-binary=:all: -r "%ROOT%requirements\req` | — |
| 02_DIAGNOSTYKA.bat | 14: `-m masterquo doctor` | OK×1 |
| 03_START_MASTERQUO.bat | 5: `masterquo_start.bat %*`<br>5: start `%~dp0masterquo_start.bat` | — |
| 04_STOP_MASTERQUO.bat | 14: `-m masterquo stop`<br>18: `-m masterquo stop` | OK×2 |
| 05_TESTY_OFFLINE.bat | 14: `tools/run_tests.py %*` | — |
| 06_DIAGNOZA_CZASU_MT5.bat | 15: `-m masterquo clock` | OK×1 |
| 07_START_DEMO_DANE_SYNTETYCZNE.bat | 5: `03_START_MASTERQUO.bat --demo` | — |
| 08_PROFIL_ORIGINAL.bat | 17: `-m masterquo profile %P%` | OK×1 |
| 10_PROGNOZY_INSTALUJ.bat | 19: `tools/check_python.py `<br>32: `tools/venv_repair.py "%ROOT%.venv_candles"`<br>35: `-m venv "%ROOT%.venv_candles"`<br>39: `-m pip install --disable-pip-version-check --no-input --require-hashes --only-binary=:all: -r "%ROOT%requirements\req`<br>48: `-m unittest discover -s . -p "test_*.py"` | — |
| 11_EKSPORT_HISTORII_XAUUSD.bat | 10: `tools/pmwpy.cmd `<br>18: `-m masterquo export-candles --months %MONTHS%` | OK×1 |
| 12_TRENING_MODELI_XAUUSD.bat | 13: `-m gold_candles_runtime.plan_train --latest` | OK×1 |
| 13_WALIDACJA_MODELI_XAUUSD.bat | 11: `-m gold_candles_runtime.registry_cli list`<br>12: `-m gold_candles_runtime.validate %*` | OK×2 |
| 14_ROLLBACK_MODELU_PROGNOZ.bat | 13: `-m gold_candles_runtime.registry_cli deactivate`<br>15: `-m gold_candles_runtime.registry_cli rollback` | OK×2 |
| 15_START_PROGNOZ_SHADOW.bat | 14: `-m gold_candles_runtime.registry_cli list`<br>17: `03_START_MASTERQUO.bat ` | OK×1 |
| 16_EKSPORT_HISTORII_SCALP.bat | 10: `tools/pmwpy.cmd `<br>15: `-m masterquo export-scalp --months %MONTHS%` | OK×1 |
| 17_TRENING_SCALP_ML.bat | 17: `-m gold_candles_runtime.scalp_train --latest --commission-per-lot-side %COMM%` | OK×1 |
| 18_WALIDACJA_SCALP.bat | 11: `-m gold_candles_runtime.scalp_registry validate`<br>13: `-m gold_candles_runtime.scalp_registry list` | OK×2 |
| 19_REPLAY_SCALP.bat | 15: `tools/pmwpy.cmd `<br>18: `-m masterquo scalp-replay --commission-per-lot-side %COMM%`<br>20: `-m masterquo scalp-replay --commission-per-lot-side %COMM% --cost-stress 1.5`<br>21: `-m masterquo scalp-replay --commission-per-lot-side %COMM% --margin-mode NETTING`<br>22: `-m masterquo scalp-replay --commission-per-lot-side %COMM% --variants` | OK×4 |
| 20_START_SCALP_SHADOW.bat | 12: `-m gold_candles_runtime.scalp_registry list`<br>17: `03_START_MASTERQUO.bat ` | OK×1 |
| 21_ROLLBACK_MODELU_SCALP.bat | 13: `-m gold_candles_runtime.scalp_registry deactivate`<br>15: `-m gold_candles_runtime.scalp_registry rollback` | OK×2 |
| 22_TRENUJ_WSZYSTKIE_MODELE.bat | 9: `tools/trening.cmd run --instruments XAUUSD,BTC --commission-xauusd %COMM% --origin 22_TRENUJ_WSZYS` | OK×1 |
| 23_NEURAL_SCALP.bat | 11: `tools/pmwpy.cmd `<br>30: `-m masterquo neural-scalp doctor --asset %ASSET%`<br>31: `-m masterquo neural-scalp prepare --asset %ASSET% --months 12`<br>32: `-m masterquo neural-scalp train --asset %ASSET% --manifest latest --activate none`<br>33: `-m masterquo neural-scalp status --asset %ASSET%`<br>34: `-m masterquo neural-scalp report --asset %ASSET% --latest`<br>35: `-m masterquo neural-scalp rollback --asset %ASSET%` | OK×6 |
| 24_SCALP_ML.bat | 11: `tools/pmwpy.cmd `<br>31: `-m masterquo ml-scalp doctor --asset %ASSET%`<br>32: `-m masterquo ml-scalp status --asset %ASSET%`<br>33: `-m masterquo ml-scalp prepare --asset %ASSET%`<br>34: `-m masterquo ml-scalp train --asset %ASSET% --activate none`<br>35: `-m masterquo ml-scalp report --asset %ASSET% --latest`<br>36: `-m masterquo ml-scalp rollback --asset %ASSET% --side BUY`<br>37: `-m masterquo ml-scalp rollback --asset %ASSET% --side SELL` | OK×7 |
| 25_LIQUIDITY.bat | 10: `tools/pmwpy.cmd `<br>28: `-m masterquo liquidity status --asset %ASSET%`<br>29: `-m masterquo liquidity poll --asset %ASSET%`<br>30: `-m masterquo liquidity import --asset %ASSET%`<br>31: `-m masterquo liquidity sessions --asset %ASSET%`<br>32: `-m masterquo liquidity evaluate --asset %ASSET%` | OK×5 |
| 26_STRUCTURE_INTELLIGENCE.bat | 11: `tools/pmwpy.cmd `<br>44: `-m masterquo structure-intelligence audit --asset %ASSET%`<br>45: `-m masterquo structure-intelligence dataset --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1`<br>46: `-m masterquo structure-intelligence dataset --asset %ASSET% --latest --task SCALP_STRUCTURE_CONTEXT_V1`<br>47: `-m masterquo structure-intelligence calibrate-indicators --asset %ASSET% --latest`<br>48: `-m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --profile standard`<br>49: `-m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --profile quick`<br>50: `-m masterquo structure-intelligence report --asset %ASSET% --latest`<br>51: `-m masterquo structure-intelligence replay --asset %ASSET% --latest --mode shadow`<br>52: `-m masterquo structure-intelligence neutralize --asset %ASSET% --latest --signal ROC20`<br>53: `-m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --experiment MQ_NEUTRAL_REAC`<br>54: `-m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_SEW_RESNET1D_V`<br>55: `-m masterquo structure-intelligence tick-replay --asset %ASSET% --latest`<br>56: `-m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --experiment MQ_QUOTE_CONTEX`<br>57: `-m masterquo structure-intelligence calibrate-indicators --asset %ASSET% --latest --profiles MQ_REGIME_MULTI_V2,STRUCTURE_C`<br>58: `-m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_SPIKE_BRAIN_FI`<br>59: `-m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_SPIKE_BRAIN_FI`<br>60: `-m masterquo structure-intelligence train --asset %ASSET% --latest --task STRUCTURE_MOVE_M1_V1 --families MQ_MINIROCKET_RID`<br>61: `-m masterquo structure-intelligence minirocket parity --reference-version sktime==1.2.0`<br>62: `-m masterquo structure-intelligence benchmark --families MQ_SPIKE_BRAIN_FINANCE_V1,MQ_MINIROCKET_RIDGE_V2 --profile cpu`<br>63: `-m masterquo structure-intelligence minirocket export-fixture --output "%ROOT%\exports\minirocket_fixture"` | OK×20 |
| 27_MINIROCKET_NATIVE.bat | 11: `tools/pmwpy.cmd `<br>31: `tools/mr2_native_status.py "%DATA%" !ERR! "%LOG%"` | — |
| 28_FLOW_CONTEXT.bat | 11: `tools/pmwpy.cmd `<br>35: `-m masterquo flow-context audit --asset %ASSET%`<br>36: `-m masterquo flow-context calibrate --asset %ASSET% --latest --modules heikin,sr-channels,stopdistance`<br>37: `-m masterquo flow-context train-markov --asset %ASSET% --latest --models MQ_MARKOV3_FLOW_V1,MQ_MARKOV_DIFF_FLOW_V1`<br>38: `-m masterquo flow-context dataset --asset %ASSET% --latest --task FLOW_CONTEXT_MOVE_M1_V1`<br>39: `-m masterquo flow-context train --asset %ASSET% --latest --task FLOW_CONTEXT_MOVE_M1_V1 --families LOGREG,XGB --profile sta`<br>40: `-m masterquo flow-context train --asset %ASSET% --latest --task FLOW_CONTEXT_MOVE_M1_V1 --families LOGREG,XGB --profile qui`<br>41: `-m masterquo flow-context report --asset %ASSET% --latest`<br>42: `-m masterquo flow-context replay --asset %ASSET% --latest --mode shadow`<br>43: `-m masterquo flow-context benchmark --profile cpu`<br>44: `-m masterquo flow-context native-parity`<br>68: `tools/mr2_native_status.py "%DATA%" !ERR! "flow" --flow` | OK×10 |
| 29_CONTEXT_INDICATORS.bat | 11: `tools/pmwpy.cmd `<br>33: `-m masterquo context-indicators audit --asset %ASSET%`<br>34: `-m masterquo context-indicators calibrate --asset %ASSET%`<br>35: `-m masterquo context-indicators replay --asset %ASSET%`<br>36: `-m masterquo context-indicators dataset --asset %ASSET%`<br>37: `-m masterquo context-indicators train --asset %ASSET% --families LOGREG,XGB --profile standard`<br>38: `-m masterquo context-indicators train --asset %ASSET% --families LOGREG,XGB --profile quick`<br>40: `-m masterquo context-indicators native-parity`<br>49: `-m masterquo context-indicators buffers-verify --report "%MQ_MT5_FILES_DIR%\PMW\PWM_BUFFER_REPORT.json"`<br>80: `tools/mr2_native_status.py "%DATA%" !ERR! "context %MEVER%" --context`<br>82: `-m masterquo context-indicators export-fixture --files-dir "%DATA%\MQL5\Files"` | OK×9 |
| 30_SH_WALIDACJA.bat | 11: `tools/pmwpy.cmd `<br>21: `-m masterquo training run --instruments %ASSET% --profile PELNY_TRENING --tasks sh_models` | OK×1 |
| 31_MONTE_CARLO_WALIDACJA.bat | 10: `tools/pmwpy.cmd `<br>26: `-m masterquo montecarlo validate --dataset "%DS%"` | OK×1 |
| 32_CENTRUM_TRENINGU.bat | 10: `tools/pmwpy.cmd `<br>29: `-m masterquo trainhub full --instrument XAUUSD`<br>30: `-m masterquo trainhub full --instrument BTC`<br>31: `-m masterquo families list --instrument XAUUSD`<br>32: `-m masterquo families train-all --instrument XAUUSD --profile smoke`<br>33: `-m masterquo trainhub export --instrument XAUUSD`<br>34: `-m masterquo trainhub export --instrument BTC`<br>35: `-m masterquo trainhub list --instrument XAUUSD`<br>36: `-m masterquo trainhub list --instrument BTC`<br>48: `-m masterquo trainhub activate --instrument "%INS%" --model-key "%KEY%" --version "%VER%"` | OK×9 |
| 33_KRONOS_INSTALUJ.bat | 21: `tools/check_python.py `<br>37: `tools/kronos_setup.py --root "%ROOT%." --weights-dir auto --python "%PYEXE%" --log "%LOG%" %CUDA_ARG%` | — |
| 34_DEEP_INSTALUJ.bat | 18: `tools/check_python.py `<br>29: `tools/deep_setup.py --root "%ROOT%." --python "%PYEXE%" --log "%LOG%"` | — |
| 35_RODZINY_MODELI.bat | 14: `tools/pmwpy.cmd `<br>25: `-m masterquo families train-all --instrument %INST% --profile %PROF%` | OK×1 |
| 36_STUDIO.bat | 9: `tools/pmwpy.cmd `<br>22: start `http://127.0.0.1:8780/`<br>23: `-m masterquo studio` | OK×1 |
| 37_QUANT_CORE.bat | 10: `tools/pmwpy.cmd `<br>30: `-m masterquo quant status`<br>31: `-m masterquo quant inventory`<br>32: `-m masterquo quant inventory --live`<br>33: `-m masterquo quant train --instrument XAUUSD`<br>34: `-m masterquo quant list --instrument XAUUSD`<br>35: `-m masterquo quant bench`<br>36: `-m masterquo quant mode SHADOW --instrument XAUUSD`<br>38: `-m masterquo quant mode OFF --instrument XAUUSD`<br>45: `-m masterquo quant mode ASSIST --confirm --instrument XAUUSD` | OK×9 |
| 38_MODELE_CHRONOS2_GRANITE.bat | 27: `tools/check_python.py `<br>50: `tools/tsfm_setup.py --model %MODEL% --root "%ROOT%." --weights-root auto --python "%PYEXE%" --log "%` | — |
| 39_PAKIET_20_WALIDACJA.bat | 12: `tools/pmwpy.cmd `<br>20: `-m masterquo training run --instruments XAUUSD --profile PELNY_TRENING --tasks sh_pack` | OK×1 |
| 41_AI_TABICL_TIREX_INSTALUJ.bat | 24: `tools/check_python.py `<br>40: `tools/tsfm_setup.py --model %MODEL% --root "%ROOT%." --weights-root auto --python "%PYEXE%" --log "%` | — |
| 42_MODELE_8GB_GRANITE_TIREX.bat | 21: `tools/check_python.py `<br>35: `tools/tsfm_setup.py --model %MODEL% --root "%ROOT%." --weights-root auto --python "%PYEXE%" --log "%` | — |
| DIAGNOSTYKA_TRENINGU.bat | 6: `tools/trening.cmd diag` | OK×1 |
| INSTALUJ_TRENING.bat | 28: `01_INSTALUJ.bat `<br>34: `10_PROGNOZY_INSTALUJ.bat `<br>39: `tools/trening.cmd install` | OK×1 |
| MODULY_IQ_PAL_SAR.bat | 12: `tools/ic.cmd %%C --asset %ASSET%` | OK×5 |
| TRENUJ_BTCUSDT.bat | 6: `tools/trening.cmd run --instruments BTC --interactive --origin TRENUJ_BTCUSDT.bat` | OK×1 |
| TRENUJ_OBA.bat | 6: `tools/trening.cmd run --instruments XAUUSD,BTC --interactive --origin TRENUJ_OBA.bat` | OK×1 |
| TRENUJ_XAUUSD.bat | 6: `tools/trening.cmd run --instruments XAUUSD --interactive --origin TRENUJ_XAUUSD.bat` | OK×1 |
| masterquo_start.bat | 16: `-m masterquo serve %*` | OK×1 |
| tools/ic.cmd | 6: `tools/pmwpy.cmd `<br>11: `-m masterquo indicator-context status` | OK×1 |
| tools/pmwpy.cmd | (tylko echo/menu) | — |
| tools/trening.cmd | 7: `tools/pmwpy.cmd `<br>17: `-m masterquo training %*` | passthrough %*×1 |

## E. Zadania treningowe, eksportery, replaye, walidacje

### E.1 Orkiestratory treningu i ich rodzaje zadań

**training/runner.py** (`masterquo training run`, API `/api/v1/training/start`, 00/22/30/39/TRENUJ_*.bat, Centrum Pepe, Studio): `TASKS` runner.py:18 (20), `STEPS` runner.py:727 (18; scalp_B/C powstają w procesie scalp_A). Profile `config/training_profiles_v1.json`: TEST_INSTALACJI, PELNY_TRENING.

| zadanie | tytuł | funkcja |
|---|---|---|
| `export` | Eksport historii z MT5 | t_export |
| `quality` | Kontrola jakości danych | t_quality |
| `forecast` | Prognozy świec gold_candles 5/15/30 min | t_forecast |
| `scalp_A` | Scalp A: kierunek 1/3/5 min (LR/HGB/MLP) | t_scalp |
| `scalp_B` | Scalp B: jakość setupu P(TP1 przed SL) | (w scalp_A) |
| `scalp_C` | Scalp C: ocena polityki hedge vs REDUCE w replayu (to nie jest sieć) | (w scalp_A) |
| `ml` | Legacy ML: Decision Tree + XGBoost (setupy S01–S12) | t_ml |
| `lab` | Lab: LOGREG/TREE/MiniRocket/XGB/ResNet1D/SEW-SNN (+eksperymenty), strona LONG | t_lab |
| `indicator_context` | Kontekst wskaźników (SAR + IQ/PAL): kalibracja SAR i model reakcji P(TP1 przed SL) | t_indicator_context |
| `ml_scalp` | Scalp ML: XGBoost P(dodatni wynik netto cyklu) + net_R, osobno LONG/SHORT | t_ml_scalp |
| `neural_scalp` | Neural Scalp System: TCN M1/M5 + kontekst – P(TP1/SL/TIMEOUT) i net_R kandydata scalp | t_neural_scalp |
| `structure_intelligence` | Structure Intelligence: ruch M1 h=3/5/15 (LOGREG/XGB/ResNeXt/SEW/SEW-EB/SpikingBrain/MiniRocket V2) + kontekst setupu | t_structure_intelligence |
| `flow_context` | Flow context: kalibracja Heikin/S-R/StopDistance, Markov3 + koszyki, model reakcji FLOW_CONTEXT_MOVE_M1_V1 | t_flow_context |
| `context_indicators` | Kontekst VAMD / FD / Pullback+SMC: kalibracja dev (<=24 konfiguracje), model CONTEXT_MOVE_M5_V1 + ablacje | t_context_indicators |
| `sh_models` | SCALPING/HEDGING: replay strategii + model zdarzenia P(TP2 przed SL) + raport walidacji | t_sh_models |
| `sh_pack` | Pakiet 20 strategii SC/HG: replay walk-forward (te same detektory, solver i polityki hedge) + werdykt per wariant | t_sh_pack |
| `monte_carlo` | Monte Carlo ścieżek: walidacja wariantów IID/BLOCK/REGIME, P(TP przed SL) i kalibracja poza próbą | t_monte_carlo |
| `master_models` | Master models (XXX.rar): HDC/GPR/event engine+STFS/STE-FlowNet + ewaluacja Kalman/Breakout/SMC/Multi-Indicator/TSVP/BUZOA | t_master_models |
| `activate` | Aktywacja w rejestrach + zgodność loaderów | t_activate |
| `bot` | Przekazanie do działającego bota (przeładowanie) | t_bot |

**training/pepe_center.py** (API `/api/v1/pepe-training/*`, panel Centrum Treningowe): `PIPELINE` pepe_center.py:31 (16) + `EXTRA` pepe_center.py:49 (4: trainhub, families, granite, sdformer).

**studio/** (Studio, `/api/studio/jobs`): katalog `studio/registry.py tasks()` = 74 zadań ({'TRAINHUB': 12, 'FAMILY': 26, 'RUNNER_GROUP': 28, 'DETERMINISTIC': 6, 'PRETRAINED': 2}); grupy runnera `RUNNER_GROUPS` registry.py:13 (14): forecast, scalp_A, ml, lab, indicator_context, ml_scalp, neural_scalp, structure_intelligence, flow_context, context_indicators, sh_models, sh_pack, monte_carlo, master_models.

**trainhub/** (`masterquo trainhub`, API `/api/v1/trainhub/*`, 32_CENTRUM_TRENINGU.bat): rodzaje zadań `KINDS` jobs.py:25 = EXPORT, DATASET, TRAIN, EVALUATE, FULL; komponenty badawcze `research/components.py:33` = TH_SDFORMERFLOW, ETC_LOG_CHANNEL.

**modelhub/families** (`masterquo families`, API `/api/v1/families/*`, 35_RODZINY_MODELI.bat): 16 rodzin – TS_ARIMA, TS_SARIMAX, VOL_GARCH, MICROSTRUCTURE, PAIR_COINT, STATARB, KALMAN_LS, BREAKOUT, TH_RF, TH_XGB, TH_SVM, SEQ_LSTM, SEQ_GRU, RL_PPO, NLP_SENTIMENT, SEQ_GRU_EVENT.

**lab/service** (API `/api/v1/lab/train`, zadanie runnera `lab`): rodziny `lab/protocol.py` FAMILIES (8) = DUMMY, RULE, LOGREG, TREE, MINIROCKET, XGB, RESNET1D, SEW_SNN; EXPERIMENTS = LOGREG_PCA, LOGREG_GMM_AUG, LOGREG_NEUTRALIZED.

**lab/si_service.py** (API `/api/v1/structure-intelligence/jobs`): rodzaje `start_job` si_service.py:410 (14) = dataset, train, calibrate, calibrate_market, tick_export, tick_replay, experiment, flow_calibrate, flow_markov, flow_dataset, flow_train, context_calibrate, context_dataset, context_train.

**mm/orchestrator.py** (`masterquo mm train`, zadanie runnera `master_models`, API `/api/v1/mm/*`): `GRAPH` orchestrator.py:25 (16) = snapshot, align_mean, kalman, kalman_calibration, breakout_zones, multi_indicator, smc_fvg, tsvp, buzoa, hdc, gpr, event_engine, stfs, ste_flownet, mathbench, fusion_board.

**quant** (`masterquo quant train`, API `POST /api/v1/quant/jobs` kind=TRAIN_METAMODEL – api/app.py:2756).

**Pozostałe procesy treningowe z API**: neural-scalp (`/api/v1/lab/neural/train`, api/app.py:3703 → `masterquo neural-scalp`), ml-scalp (`/api/v1/ml/scalp/train`, api/app.py:3773 → `masterquo ml-scalp`), indicator-context (`/api/v1/indicator-context/train`, api/app.py:511), legacy ML (`/api/v1/ml/train`, api/app.py:1850), Granite TTM (`/api/v1/models/foundation/granite/train`, api/app.py:2433), SDformerFlow (`/api/v1/research-modules/sdformerflow/train`, api/app.py:2854), Monte Carlo (`/api/v1/montecarlo/run`, api/app.py:3458).

<details><summary>Trasy API uruchamiające / sterujące zadaniami (49)</summary>

| metoda | ścieżka | miejsce |
|---|---|---|
| POST | `/api/v1/lab/train` | backend/masterquo/api/app.py:413 |
| GET | `/api/v1/lab/jobs` | backend/masterquo/api/app.py:438 |
| POST | `/api/v1/lab/jobs/{jid}/cancel` | backend/masterquo/api/app.py:442 |
| POST | `/api/v1/indicator-context/train` | backend/masterquo/api/app.py:511 |
| POST | `/api/v1/structure-intelligence/jobs` | backend/masterquo/api/app.py:981 |
| GET | `/api/v1/structure-intelligence/jobs/{jid}` | backend/masterquo/api/app.py:989 |
| POST | `/api/v1/structure-intelligence/jobs/{jid}/cancel` | backend/masterquo/api/app.py:996 |
| GET | `/api/v1/patterns/jobs/{job_id}` | backend/masterquo/api/app.py:1089 |
| POST | `/api/v1/patterns/jobs/{job_id}/cancel` | backend/masterquo/api/app.py:1096 |
| POST | `/api/v1/patterns/jobs/{job_id}/resume` | backend/masterquo/api/app.py:1100 |
| POST | `/api/v1/patterns/jobs/{job_id}/export` | backend/masterquo/api/app.py:1107 |
| GET | `/api/v1/patterns/jobs/{job_id}/results` | backend/masterquo/api/app.py:1112 |
| POST | `/api/v1/ml/train` | backend/masterquo/api/app.py:1850 |
| GET | `/api/v1/market-zones/job/{job_id}` | backend/masterquo/api/app.py:1938 |
| POST | `/api/v1/trainhub/components/{cid}/jobs` | backend/masterquo/api/app.py:2016 |
| POST | `/api/v1/trainhub/components/{cid}/cancel` | backend/masterquo/api/app.py:2028 |
| POST | `/api/v1/trainhub/jobs` | backend/masterquo/api/app.py:2086 |
| GET | `/api/v1/trainhub/jobs` | backend/masterquo/api/app.py:2093 |
| GET | `/api/v1/trainhub/jobs/{jid}` | backend/masterquo/api/app.py:2097 |
| POST | `/api/v1/trainhub/jobs/{jid}/cancel` | backend/masterquo/api/app.py:2104 |
| GET | `/api/v1/kronos/job/{name}` | backend/masterquo/api/app.py:2271 |
| POST | `/api/v1/models/foundation/granite/train` | backend/masterquo/api/app.py:2433 |
| POST | `/api/v1/models/foundation/granite/cancel` | backend/masterquo/api/app.py:2446 |
| GET | `/api/v1/models/foundation/job/{name}` | backend/masterquo/api/app.py:2470 |
| POST | `/api/v1/families/{fid}/train` | backend/masterquo/api/app.py:2685 |
| POST | `/api/v1/families/train-all` | backend/masterquo/api/app.py:2689 |
| POST | `/api/v1/families/{fid}/cancel` | backend/masterquo/api/app.py:2693 |
| GET | `/api/v1/quant/jobs` | backend/masterquo/api/app.py:2751 |
| POST | `/api/v1/quant/jobs` | backend/masterquo/api/app.py:2756 |
| GET | `/api/v1/research-modules/optimizer/jobs` | backend/masterquo/api/app.py:2837 |
| POST | `/api/v1/research-modules/optimizer/run` | backend/masterquo/api/app.py:2841 |
| POST | `/api/v1/research-modules/sdformerflow/train` | backend/masterquo/api/app.py:2854 |
| POST | `/api/v1/research-modules/sdformerflow/cancel` | backend/masterquo/api/app.py:2870 |
| GET | `/api/v1/mm/job` | backend/masterquo/api/app.py:3122 |
| POST | `/api/v1/training/resume` | backend/masterquo/api/app.py:3204 |
| POST | `/api/v1/training/start` | backend/masterquo/api/app.py:3272 |
| POST | `/api/v1/pepe-training/train` | backend/masterquo/api/app.py:3350 |
| POST | `/api/v1/pepe-training/cancel` | backend/masterquo/api/app.py:3367 |
| POST | `/api/v1/export/start` | backend/masterquo/api/app.py:3392 |
| POST | `/api/v1/export/cancel` | backend/masterquo/api/app.py:3405 |
| POST | `/api/v1/montecarlo/run` | backend/masterquo/api/app.py:3458 |
| POST | `/api/v1/training/cancel` | backend/masterquo/api/app.py:3481 |
| GET | `/api/v1/lab/neural/jobs` | backend/masterquo/api/app.py:3681 |
| POST | `/api/v1/lab/neural/train` | backend/masterquo/api/app.py:3703 |
| POST | `/api/v1/lab/neural/cancel` | backend/masterquo/api/app.py:3707 |
| POST | `/api/v1/ml/scalp/train` | backend/masterquo/api/app.py:3773 |
| POST | `/api/v1/ml/cancel` | backend/masterquo/api/app.py:3833 |
| POST | `/api/v1/ml/resume` | backend/masterquo/api/app.py:3837 |
| POST | `/api/v1/asge/run` | backend/masterquo/api/wf32_routes.py:633 |

</details>

### E.2 Eksportery

**Rejestr eksporterów danych** `backend/masterquo/exports/registry.py` (15) – jedna tabela steruje CLI `export-<nazwa>` i API `GET /api/v1/exports/<nazwa>` (export_routes.py:52); lista: `export-list` / `GET /api/v1/exports`; import: `import-trader-life-game` / `POST /api/v1/exports/trader-life-game/import`.

| eksporter | tytuł | zadanie | wymaga działającej aplikacji | parametry | registry.py |
|---|---|---|---|---|---|
| `orderflow` | Ledger transakcji, footprint, Volume Profile, DOM i heatmapa (order flow) | TASK 001/002/004 | tak | market, instrument, row, tf_seconds, refresh | 86 |
| `market-candles` | Świece CRYPTO / INDICES / FOMO_STOCK_PERPS (10 interwałów) | TASK 003 | nie | market, instruments, timeframes, n | 91 |
| `fomo-universe` | Rozpoznanie FOMO 101 z wersją metadanych venue | TASK 003 | nie | — | 95 |
| `strategy-roi` | ROI strategii (TASK 014) – PAPER / AUTO_DEMO / AUTO_LIVE osobno | TASK 014 | nie | — | 96 |
| `sfb-snapshots` | Snapshoty Strategy Filter Bucket | TASK 018 | tak | — | 97 |
| `asge-trials` | Ledger prób generatora strategii (ASGE) | TASK 024 | nie | — | 98 |
| `change-points` | Wyniki PELT (punkty zmiany) | TASK 015 | tak | timeframe, lookback, min_segment, sensitivity | 99 |
| `long-horizon` | Prognozy 24–72 h (rozkład, SHADOW) | TASK 012 | tak | timeframe, horizons | 102 |
| `association-rules` | Reguły asocjacyjne (OBSERVE) | TASK 011 | tak | timeframe, horizon | 104 |
| `pt-skill` | Wyniki testu Pesarana–Timmermanna (dziennik od startu aplikacji) | TASK 010 | tak | — | 106 |
| `dt-ranker` | Rankingi DT (SHADOW, dziennik od startu aplikacji) | TASK 005 | tak | — | 108 |
| `telegram-center` | Zdarzenia i outbox centrum Telegram rachunku (bez tokenu) | TASK 017 | nie | — | 110 |
| `trader-life-game` | TraderLifeGame – kopia zapasowa (profil, XP, Gold, questy, dziennik, symulator, inwentarz) | TASK 019 | nie | — | 111 |
| `bootstrap` | Stan bootstrapu (komponenty, stany) | TASK 013 | nie | — | 113 |
| `store-tables` | Tabele trwałych magazynów SQLite bez eksportu zbiorczego (biała lista; tryby i dane syntetyczne osobno) | inwentarz X6 | nie | store, tables | 114 |

**Eksport historii MT5 / danych treningowych (osobne implementacje):**

- `masterquo export` → `diagnostics.export_history` (diagnostics.py:263) – format M06R, 8 TF.
- `masterquo export-candles` / `export-scalp` / `training export` / `POST /api/v1/export/start` (training/export_job.py:118 → `training export`) → `forecast/export.export_candles` (training/cli.py:231, __main__.py:378-382).
- `masterquo trainhub export|import-data` / Studio (adapter TRAINHUB/FAMILY) → `marketdata/export` (trainhub/cli.py:86, studio/pipeline.py:stage_export).
- `flow-context export` (lab/flow_context/cli.py:104 – tylko komunikat, kod 2), `structure-intelligence export|tick-export` (lab/structure_cli.py:135 – bridge: komunikat; import: weryfikacja bez rejestracji).
- Paczki: `trainhub package-zip`, `GET /api/v1/trainhub/package.zip`, `dataset.zip`, `components/{cid}/export.zip`, `POST /api/v1/training/export`, `GET /api/v1/patterns/export`, `POST /api/v1/patterns/jobs/{job_id}/export`, `mm mathbench-export|export-fixtures`, `context-indicators export-fixture`, `structure-intelligence minirocket export-fixture|export-native`.

### E.3 Replaye

- CLI: `scalp-replay`, `context-indicators replay`, `flow-context replay`, `structure-intelligence tick-replay`, `structure-intelligence replay`, `sh pack-replay`
- Zadanie runnera `sh_pack` (runner.py:534 → `sh pack-replay`), `sh_models` (replay SH + model), `scalp_C` (ocena polityki w replayu).
- `python -m masterquo.decision.replay` (decision/replay.py), `tools/replay_strategies.py`, `tools/backtest_ema_pullback.py`.
- .bat: 19_REPLAY_SCALP.bat (4 warianty scalp-replay), 26 (opcje 8, 13), 28 (8), 29 (3), 39_PAKIET_20_WALIDACJA.bat.

### E.4 Walidacje / oceny / diagnostyka

- CLI: `doctor`, `context-indicators audit`, `context-indicators calibrate`, `context-indicators buffers-verify`, `context-indicators native-parity`, `flow-context audit`, `flow-context calibrate`, `flow-context native-parity`, `flow-context benchmark`, `flow-context report`, `flow-context evaluate-holdout`, `structure-intelligence audit`, `structure-intelligence calibrate-indicators`, `structure-intelligence benchmark`, `structure-intelligence report`, `structure-intelligence evaluate-holdout`, `liquidity status`, `liquidity evaluate`, `neural-scalp doctor`, `neural-scalp status`, `neural-scalp report`, `ml-scalp doctor`, `ml-scalp status`, `ml-scalp report`, `indicator-context status`, `indicator-context calibrate-sar`, `indicator-context evaluate`, `mm status`, `mm buzoa-bench`, `mm mathbench-export`, `montecarlo validate`, `montecarlo status`, `trainhub evaluate`, `quant status`, `quant bench`, `training status`, `training report`
- Runtime prognoz: `gold_candles_runtime.validate`, `gold_candles_runtime.scalp_registry validate`.
- tools: verify_release.py, run_tests.py (05_TESTY_OFFLINE.bat), golden_run.py, validate_families_synthetic.py, check_requirements_win.py, migration_check.py, integration_matrix.py, check_python.py.

- API (26): GET `/api/v1/lab/zones/diagnostics` (app.py:604), GET `/api/v1/structure-intelligence/quote-quality` (app.py:773), GET `/api/v1/structure-intelligence/model-diagnostics` (app.py:816), POST `/api/v1/lab/buffers/mappings/validate` (app.py:945), GET `/api/v1/structure-intelligence/quality` (app.py:977), GET `/api/v1/analytics/diagnostics` (app.py:1042), POST `/api/v1/patterns/samples/{sid}/validate` (app.py:1075), POST `/api/v1/patterns/validate` (app.py:1082), GET `/api/v1/sh/pack/evaluations` (app.py:1285), GET `/api/v1/sh/validation` (app.py:1349), POST `/api/v1/kronos/verify` (app.py:2264), POST `/api/v1/kronos/validate` (app.py:2284), GET `/api/v1/kronos/validation` (app.py:2294), GET `/api/v1/models/foundation/compare` (app.py:2370), POST `/api/v1/models/foundation/verify` (app.py:2401), POST `/api/v1/models/foundation/validate` (app.py:2415), GET `/api/v1/models/foundation/validation` (app.py:2476), GET `/api/v1/training/readiness` (app.py:3159), GET `/api/v1/training/compare` (app.py:3199), GET `/api/v1/export/readiness` (app.py:3417), GET `/api/v1/montecarlo/validations/{run_id}/report` (app.py:3430), POST `/api/v1/lab/neural/doctor` (app.py:3689), GET `/api/v1/diagnostics` (app.py:3986), GET `/api/v1/indicators/diagnostics` (wf32_routes.py:222), POST `/api/v1/models/pt/evaluate` (wf32_routes.py:351), POST `/api/v1/tlg/loot/evaluate` (wf32_routes.py:665)

## F. Wewnętrzne wywołania CLI (kto woła kogo – podprocesy `[python, -m, …]` w backendzie)

Sprawdzone tym samym parserem (wartości dynamiczne podstawione; `--profile` runnera = quick/standard sprawdzone osobno – OK).

```
backend/masterquo/training/pepe_center.py:631 masterquo training run --instruments 1 --profile PELNY_TRENING --origin pepe-center => OK {"tcmd": "run", "instruments": "1", "profile": "PELNY_TRENING", "origin": "pepe-center"
backend/masterquo/training/runner.py:190 gold_candles_runtime.plan_train --instrument XAUUSD --data-dir 1 --out 1 --trees 1 --data-kind 1 --no-activate => ARGPARSE_ERROR: internal_cli.py: error: argument --data-kind: invalid choice: '1' (choose 
backend/masterquo/training/runner.py:314 masterquo training lab-offline --instrument XAUUSD --dataset 1 --bars 1 --families 1 --experiments 1 --min-events 1 --ou => OK {"tcmd": "lab-offline", "instrument": "XAUUSD", "dataset": "1", "bars": 1, "families": 
backend/masterquo/training/runner.py:503 masterquo montecarlo validate --dataset 1 --out 1 => OK {"cmd": "validate", "dataset": "1", "horizon": 60, "stride": 30, "window": 3000, "n_pat
backend/masterquo/training/runner.py:534 masterquo sh pack-replay --dataset 1 --out 1 => OK {"cmd": "pack-replay", "dataset": "1", "variants": "", "slippage": 0.05, "spread_fallba
backend/masterquo/training/runner.py:567 masterquo sh train --instrument XAUUSD --dataset 1 --out 1 => OK {"cmd": "train", "instrument": "XAUUSD", "dataset": "1", "out": "1", "strategies": "SCA
backend/masterquo/training/runner.py:603 masterquo mm train --dataset 1 --instrument XAUUSD --out 1 --profile __DYN__ --cancel-file 1 => DYNAMIC_PROFILE (checked manually)
backend/masterquo/training/runner.py:453 masterquo flow-context pipeline --asset XAUUSD --dataset 1 --out 1 --profile __DYN__ => DYNAMIC_PROFILE (checked manually)
backend/masterquo/training/runner.py:477 masterquo context-indicators pipeline --asset XAUUSD --dataset 1 --out 1 --profile __DYN__ => DYNAMIC_PROFILE (checked manually)
backend/masterquo/training/runner.py:112 masterquo training export --instrument XAUUSD --symbol 1 --months 1 --out 1 --tfs 1 => OK {"tcmd": "export", "instrument": "XAUUSD", "symbol": "1", "months": 1, "out": "1", "tfs
backend/masterquo/training/runner.py:229 gold_candles_runtime.scalp_train --instrument XAUUSD --history 1 --data-kind 1 --no-activate => ARGPARSE_ERROR: internal_cli.py: error: argument --data-kind: invalid choice: '1' (choose 
backend/masterquo/training/runner.py:277 masterquo training ml-offline --instrument XAUUSD --dataset 1 --days 1 --threads 1 --out 1 => OK {"tcmd": "ml-offline", "instrument": "XAUUSD", "dataset": "1", "days": 1, "threads": 1,
backend/masterquo/training/runner.py:346 masterquo indicator-context train --asset XAUUSD --dataset 1 --out 1 => OK {"c": "train", "asset": "XAUUSD", "dataset": "1", "out": "1"}
backend/masterquo/training/runner.py:373 masterquo ml-scalp train --asset XAUUSD --dataset 1 --out 1 --activate none => OK {"c": "train", "asset": "XAUUSD", "dataset": "1", "manifest": "latest", "activate": "no
backend/masterquo/training/runner.py:399 masterquo neural-scalp train --asset XAUUSD --dataset 1 --out 1 --activate none => OK {"c": "train", "asset": "XAUUSD", "dataset": "1", "manifest": "latest", "months": 12, "
backend/masterquo/training/runner.py:426 masterquo structure-intelligence pipeline --asset XAUUSD --dataset 1 --out 1 --profile __DYN__ => DYNAMIC_PROFILE (checked manually)
backend/masterquo/training/runner.py:638 gold_candles_runtime.registry_cli --instrument XAUUSD activate 1 => OK {"cmd": "activate", "instrument": "XAUUSD", "run_id": "1"}
backend/masterquo/training/runner.py:647 gold_candles_runtime.scalp_registry --instrument XAUUSD activate 1 => OK {"cmd": "activate", "instrument": "XAUUSD", "run_id": "1"}
backend/masterquo/training/export_job.py:118 masterquo training export --instrument XAUUSD --symbol 1 --out 1 --tfs 1 --ticks-days 1 => OK {"tcmd": "export", "instrument": "XAUUSD", "symbol": "1", "months": 12, "out": "1", "tf
backend/masterquo/api/app.py:521 masterquo indicator-context train --asset XAUUSD => OK {"c": "train", "asset": "XAUUSD"}
backend/masterquo/api/app.py:3283 masterquo training run --instruments 1 --profile __DYN__ --origin panel => DYNAMIC_PROFILE (checked manually)
backend/masterquo/api/app.py:2601 masterquo studio --port 1 => OK (studio)
backend/masterquo/api/app.py:3218 masterquo training resume 1 => OK {"tcmd": "resume", "run_id": "1"}
backend/masterquo/api/app.py:3657 masterquo neural-scalp => STARRED (partial) ARGPARSE_ERROR: masterquo neural-scalp: error: the following arguments a
backend/masterquo/api/app.py:3536 masterquo training rollback --instrument XAUUSD --family 1 => OK {"tcmd": "rollback", "instrument": "XAUUSD", "family": "1"}
backend/masterquo/api/app.py:3694 masterquo neural-scalp doctor --asset XAUUSD => OK {"c": "doctor", "asset": "XAUUSD"}
backend/masterquo/api/app.py:3761 masterquo ml-scalp => STARRED (partial) ARGPARSE_ERROR: masterquo ml-scalp: error: the following arguments are r
backend/masterquo/forecast/service.py:95 gold_candles_runtime.worker  => NO_ARGPARSE_MAIN (main() takes 0 positional arguments but 1 was given)
backend/masterquo/studio/pipeline.py:166 masterquo training export --instrument XAUUSD --symbol 1 --months 1 --out 1 --tfs 1 => OK {"tcmd": "export", "instrument": "XAUUSD", "symbol": "1", "months": 1, "out": "1", "tfs
backend/gold_candles_runtime/scalp_train.py:288 gold_candles_runtime.scalp_train  => OK {"data_kind": "REAL_USER_DATA", "slippage_ticks": 2.0}
```

