"""Route modules of the bot API (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5: api/app.py - 436 routes in ONE function).

api/app.create_app(rt, port) keeps the security middleware (Guard), the lifespan and the page + session part (/, _index,
/assets, /static, /api/v1/health, /api/v1/session) and then calls register_all(app, ctx): REGISTRATION keeps the order of
the blocks of create_app before the split (Starlette matches routes in registration order: /x/{id} vs /x/special); after it
create_app mounts wf32_routes and export_routes as before. Each register(app, ctx) defines the SAME handlers (function
names, signatures, decorators, Pydantic models, error codes, body); the create_app locals a block used (rt, sec, port,
helpers such as _asset / _th_inst, handlers called by name such as get_config) are bound at the top of register from ctx under
the same local names - the handler text is unchanged and the runtime variable is still `rt` (tools/routes_inventory.ORDER_PATH
reads handler sources). Line numbers in REGISTRATION = create_app of the base 7ba7ab0 (before the split).
"""
from __future__ import annotations

from types import SimpleNamespace

from . import (
    _shared,
    agent,
    analytics,
    appearance,
    baskets,
    core,
    evaluation,
    families,
    history_export,
    indicators,
    kronos_tsfm,
    lab,
    licensing,
    liquidity,
    market,
    ml,
    mm,
    models,
    montecarlo,
    nss,
    quant,
    research,
    scalp,
    settings,
    sh,
    strategy,
    structure,
    studio,
    svp,
    system,
    telegram,
    trading,
    trainhub,
    training,
    ws,
    zones,
)


class Ctx(SimpleNamespace):
    """What ONE create_app call shares between its route blocks (closures over the same rt): rt, sec (LocalSecurity), port and
    the helpers / handlers a later block uses by name - published by the block that defines them (routes/_shared.py for the
    three used before their own block)."""


REGISTRATION = (
    core.register,                      # 284-375
    lab.register,                       # 377-607
    trading.register_manual,            # 609-702
    structure.register,                 # 705-993
    analytics.register,                 # 996-1145
    scalp.register,                     # 1147-1151
    sh.register,                        # 1154-1404
    market.register,                    # 1406-1621
    settings.register,                  # 1623-1689
    agent.register,                     # 1692-1733
    trading.register_modes,             # 1736-1757
    strategy.register,                  # 1760-1829
    ml.register,                        # 1832-1858
    training.register_installer,        # 1861-1877
    mm.register_status,                 # 1880-1885
    zones.register,                     # 1887-1978
    trainhub.register,                  # 1981-2185
    models.register,                    # 2187-2209
    kronos_tsfm.register_kronos,        # 2214-2313
    kronos_tsfm.register_foundation,    # 2316-2493
    indicators.register,                # 2496-2552
    studio.register,                    # 2555-2665
    families.register,                  # 2668-2734
    quant.register,                     # 2737-2824
    research.register,                  # 2833-2893
    baskets.register,                   # 2897-2967
    quant.register_models,              # 2969-2996
    svp.register,                       # 2999-3122
    evaluation.register,                # 3124-3141
    mm.register_live,                   # 3143-3178
    training.register_runs,             # 3180-3335
    licensing.register,                 # 3341-3365
    training.register_pepe,             # 3367-3405
    history_export.register,            # 3408-3444
    montecarlo.register,                # 3447-3500
    training.register_active,           # 3502-3569
    liquidity.register,                 # 3572-3635
    scalp.register_dashboard,           # 3638-3671
    nss.register,                       # 3688-3757
    ml.register_scalp,                  # 3760-3892
    strategy.register_selection,        # 3894-3937
    appearance.register,                # 3939-3974
    trading.register_execution,         # 3976-4013
    system.register_diagnostics,        # 4015-4025
    telegram.register,                  # 4028-4065
    system.register,                    # 4069-4150
    ws.register,                        # 4153-4195
)


def register_all(app, ctx: Ctx) -> None:
    """Mount every route block on `app` in the order of create_app before the split."""
    _shared.define(ctx)
    for register in REGISTRATION:
        register(app, ctx)
