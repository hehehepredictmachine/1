"""Provenance of the six MQL5 materials (downloaded 2026-11-16 in the implementation environment; files read, not executed).
The original archives are NOT redistributed in the package - the PMW code is a port with its own implementation id per module.
License: the MQL5 articles / CodeBase do not state an open-source license in these files (license_verified = False); the ports keep
the authors' attribution and the source URL. Checkpoints: none were provided by any source (checkpoint_verified = False)."""
SOURCES = {
    "sdformerflow": {"id": "20404", "kind": "article", "url": "https://www.mql5.com/en/articles/20404", "author": "Dmitriy Gizlyk",
                     "attachment": "MQL5.zip", "attachment_sha256": "576eb8726c1cde36fb1270c16bc2bb80b9683023a6ebbf8ce04be3ad2786055d",
                     "files_read": ["MQL5/Experts/SDformerFlow/Trajectory.mqh (CreateDescriptions: layer graph)", "MQL5/Experts/SDformerFlow/Study.mq5 (bar descriptor, STFS target)"],
                     "not_in_attachment": "NeuroNet library (CNeuronSDformerFlow / UBlock / SDSA kernels) - internals taken from the article text",
                     "implementation_id": "PMW_SDFORMERFLOW_TORCH_PORT_V1", "license_verified": False, "checkpoint_verified": False},
    "coa_coyote": {"id": "23053", "kind": "article", "url": "https://www.mql5.com/en/articles/23053", "author": "Andrey Dik",
                   "attachment": "COA_Coyote.zip", "attachment_sha256": "36eb82a9cc789bf16a34152416c28c47932a823c259a049564ddc20a9c8c172b",
                   "files_read": ["Include/Math/AOs/PopulationAO/AO_COA_CoyoteOptimizationAlgorithm.mqh"],
                   "implementation_id": "PMW_COA_PORT_V1", "license_verified": False, "checkpoint_verified": False},
    "cellular_feature_graph": {"id": "23135", "kind": "article", "url": "https://www.mql5.com/en/articles/23135", "author": "Yevgeniy Koshtenko",
                               "attachment": "Cellular10K_LearnableFeatureGraph_GraphCA.zip",
                               "attachment_sha256": "ea9611794593f822e39a280a0a855d693530afb2713a9bf541536112cbb9fe1c",
                               "files_read": ["CellularNeuralNet10K.mqh (features, graph layer, Hebbian update, CA rules, vote)"],
                               "implementation_id": "PMW_GRAPH50_PORT_V1", "license_verified": False, "checkpoint_verified": False},
    "bchimp": {"id": "23132", "kind": "article", "url": "https://www.mql5.com/en/articles/23132", "author": "Andrey Dik",
               "attachment": "BChimp.zip", "attachment_sha256": "29ce4067e3a00920d0b6d4e1d59168b8fc7f586f4148adc1765c19e3ca40298d",
               "files_read": ["Include/Math/AOs/PopulationAO/AO_BChimp_ChimpOptimizationAlgorithm.mqh"],
               "implementation_id": "PMW_BCHIMP_CONTINUOUS_PORT_V1", "license_verified": False, "checkpoint_verified": False},
    "g7_smc_radar": {"id": "79287", "kind": "code", "url": "https://www.mql5.com/en/code/79287", "author": "Sophea Khin",
                     "attachment": "G7_Indicato7.mq5", "attachment_sha256": "58875e800c36aa77e89429963c5985c1e61d821fef82d6c52ba51d0810b218b4",
                     "files_read": ["G7_Indicato7.mq5 (CheckFVG, CheckOB, CalculateCorrelation, DrawRadar score)"],
                     "implementation_id": "PMW_G7_SRC_PORT_V1", "license_verified": False, "checkpoint_verified": False},
    "exponential_trend_channel": {"id": "79188", "kind": "code", "url": "https://www.mql5.com/en/code/79188", "author": "Bruno_Myrrha",
                                  "attachment": "ExponentialTrendChannelIndicator.mq5 (v1.06)",
                                  "attachment_sha256": "17d6b6746c7b59c3f625d5adb0c48e8f3abc740c21a15b518ae94a369e3aeb08",
                                  "files_read": ["ExponentialTrendChannelIndicator.mq5 (FitWindow, ScanWindows, Position, SignedFit)"],
                                  "implementation_id": "PMW_ETC_SRC_PORT_V1", "license_verified": False, "checkpoint_verified": False},
}
