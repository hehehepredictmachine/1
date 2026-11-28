"""Mapping between the three vocabularies of training profiles (arch146 I0134) - written out by hand in four places of runner.py and in
studio/pipeline.py until 1.46 (the Studio copy was wrong in 1.46.0: 'quick' / 'standard' given to the runner, KeyError for every Studio
runner-group task). Parameters of the profiles are unchanged - only the names are translated, in one place:

  runner (config/training_profiles_v1.json): TEST_INSTALACJI | PELNY_TRENING
  module CLIs (flow-context, context-indicators, structure-intelligence, mm, ...): quick | standard
  Studio / families / trainhub: smoke | research | full
"""
from __future__ import annotations

RUNNER_PROFILES = ("TEST_INSTALACJI", "PELNY_TRENING")
MODULE_PROFILES = ("quick", "standard")
STUDIO_PROFILES = ("smoke", "research", "full")
# Studio profile -> runner profile (smoke = the short install test, research / full = the real training); any other name -> PELNY_TRENING
STUDIO_TO_RUNNER = {"smoke": "TEST_INSTALACJI", "research": "PELNY_TRENING", "full": "PELNY_TRENING"}
# runner profile -> profile of the module CLIs (synthetic data always run the quick variant, see is_quick)
RUNNER_TO_MODULE = {"TEST_INSTALACJI": "quick", "PELNY_TRENING": "standard"}


def is_quick(plan: dict) -> bool:
    """The short variant of a runner step: the install test profile or synthetic data (the same rule in every step)."""
    return plan["profile"] == "TEST_INSTALACJI" or bool(plan["synthetic"])


def module_profile(plan: dict) -> str:
    """Profile given to a module CLI by a runner step: 'quick' for the install test / synthetic data, otherwise 'standard'."""
    return "quick" if is_quick(plan) else "standard"


def runner_profile_for_studio(profile: str | None) -> str:
    """Runner profile of a Studio runner-group task (Studio never activates - its pipeline sets plan['activate'] = False itself)."""
    return STUDIO_TO_RUNNER.get(profile or "", "PELNY_TRENING")
