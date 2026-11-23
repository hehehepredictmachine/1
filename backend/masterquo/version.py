"""Single source of version identifiers used across API, DB and agent records."""

APP_NAME = "PepeMarketWizard"        # STABLE engine identity (health "app", desktop handshake, data paths) - do not rename
DISPLAY_NAME = "Apollo23"            # 1.45 (TASK 019): user-visible product name
APP_VERSION = "1.44.1"
# Backend <-> frontend contract. Bump on any breaking change of /api/v1 or WS payloads.
API_CONTRACT_VERSION = "1.0.0"
# Decision record schema produced by the backend (engine + risk + agent).
DECISION_SCHEMA_VERSION = "mq-decision-1.0.0"
# Agent output schema (see agent/schema.py).
AGENT_SCHEMA_VERSION = "mq-agent-1.0.0"
# Reconstructed MasterQUO specification (docs/MASTERQUO_SPEC_REKONSTRUKCJA_v1.0.0.md).
SPEC_VERSION = "MQ-SPEC-RECON-1.0.0"
# Legacy contract versions carried by the vendored engines (unchanged).
LEGACY_SCHEMA_VERSION = "2.0.0"
LEGACY_PROMPT_VERSION = "4.1.0"
