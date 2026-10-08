"""MasterQUO M11 1.0.0 — offline/read-only risk evaluator.
Never sends orders; outputs are preliminary research gates only.
Python >=3.10, stdlib only.
"""
from __future__ import annotations
import argparse
import json
import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from pathlib import Path
from typing import Callable, Optional

SCHEMA = '2.0.0'
POLICY = 'MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS'

class RiskInputError(ValueError):
    pass


def dec(value, name: str, *, min_value: Optional[Decimal] = None, positive=False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise RiskInputError('INVALID_' + name.upper())
    try:
        v = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise RiskInputError('INVALID_' + name.upper()) from None
    if not v.is_finite() or (positive and v <= 0) or (min_value is not None and v < min_value):
        raise RiskInputError('INVALID_' + name.upper())
    return v


def ts(v, field: str):
    if not isinstance(v, str):
        raise RiskInputError('MISSING_' + field.upper())
    try:
        d = datetime.fromisoformat(v.replace('Z', '+00:00'))
    except ValueError:
        raise RiskInputError('INVALID_' + field.upper()) from None
    if d.tzinfo is None or d.utcoffset() is None:
        raise RiskInputError('TIMEZONE_REQUIRED_' + field.upper())
    return d.astimezone(timezone.utc)


def require(cond, code: str):
    if not cond:
        raise RiskInputError(code)


def floorsize(size: Decimal, step: Decimal, maximum: Decimal) -> Decimal:
    """Broker volume grids are multiples of step from zero; round down only."""
    return (min(size, maximum) / step).to_integral_value(rounding=ROUND_FLOOR) * step


def fmt(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def result_base(payload: dict) -> dict:
    return {
        'module_id': 'M11', 'module_version': '1.0.0-CANDIDATE',
        'schema_version': SCHEMA, 'analysis_id': payload.get('analysis_id'),
        'as_of': payload.get('as_of'), 'setup_id': (payload.get('plan') or {}).get('setup_id'),
        'run_status': 'COMPLETED', 'status': 'PENDING',
        'risk_gate': 'BLOCKED', 'risk_gate_reason': 'NOT_EVALUATED',
        'preliminary_risk_eligible': False, 'position_size_lots': None,
        'risk_budget_ccy': None, 'modeled_loss_ccy': None, 'modeled_reward_ccy': None,
        'rr_net': None, 'margin_estimate_ccy': None, 'portfolio_risk_after_ccy': None,
        'execution_permission': 'BLOCKED', 'execution_eligible': False,
        'live_execution_allowed': False, 'submitted_order_id': None,
        'order_actions': [], 'broker_order_sent': False,
        'execution_authorization_required': ['M08', 'M09', 'M10', 'M11', 'M14', 'MT5_ORDER_ADAPTER'],
        'validation_scope': 'OFFLINE_REFERENCE', 'cost_model': 'BROKER_BID_ASK_NO_DOUBLE_SPREAD',
        'reason_codes': [], 'limitations': ['NOT_CONNECTED_TO_BROKER', 'NO_ORDER_SEND'],
    }


def evaluate(payload: dict, *, profit_calc: Optional[Callable] = None,
             margin_calc: Optional[Callable] = None) -> dict:
    """Evaluate hypothetical MARKET plan, broker pluggable read-only calculations.

    profit_calc(direction, volume_decimal, entry_decimal, exit_decimal) -> numeric account ccy.
    margin_calc(direction, volume_decimal, entry_decimal) -> numeric account ccy.
    Callbacks are not authenticated: even a PASS never authorizes live trade.
    """
    out = result_base(payload)
    try:
        require(isinstance(payload, dict), 'INVALID_PAYLOAD')
        require(payload.get('schema_version') == SCHEMA, 'SCHEMA_MISMATCH')
        require(payload.get('data_source_policy') == POLICY, 'SOURCE_POLICY_MISMATCH')
        require(payload.get('visual_capture_enabled') is False, 'SCREENSHOT_POLICY_VIOLATION')
        as_of = ts(payload.get('as_of'), 'as_of')
        snapshot = payload['data_snapshot']
        runtime = payload['runtime']
        plan = payload['plan']
        account = payload['account']
        portfolio = payload['portfolio']
        policy = payload['risk_policy']
        calc = payload['broker_calculation']
        for field, obj in [('data_snapshot', snapshot), ('runtime', runtime), ('plan', plan),
                           ('account', account), ('portfolio', portfolio), ('risk_policy', policy),
                           ('broker_calculation', calc)]:
            require(isinstance(obj, dict), 'INVALID_' + field.upper())
        require(snapshot.get('snapshot_id') == plan.get('snapshot_id'), 'SNAPSHOT_MISMATCH')
        require(snapshot.get('instrument_id') == plan.get('instrument_id') == account.get('instrument_id') == portfolio.get('instrument_id'), 'INSTRUMENT_MISMATCH')
        require(ts(snapshot.get('as_of'), 'snapshot_as_of') == as_of, 'SNAPSHOT_TIME_MISMATCH')
        require(ts(portfolio.get('as_of'), 'portfolio_as_of') <= as_of, 'FUTURE_PORTFOLIO')
        require(ts(account.get('as_of'), 'account_as_of') <= as_of, 'FUTURE_ACCOUNT')
        require(ts(plan.get('as_of'), 'plan_as_of') <= as_of, 'FUTURE_PLAN')
        require(snapshot.get('source') == 'MT5_PRIMARY', 'NO_MT5_PRIMARY')
        require(snapshot.get('execution_gate') == 'PASS', 'DATA_EXECUTION_GATE_FAIL')
        require(runtime.get('status') == 'HEALTHY', 'RUNTIME_NOT_HEALTHY')
        require(runtime.get('snapshot_id') == snapshot.get('snapshot_id'), 'RUNTIME_SNAPSHOT_MISMATCH')
        require(snapshot.get('calendar_gate') == 'PASS', 'CALENDAR_GATE_NOT_PASS')
        require(snapshot.get('trap_gate') == 'PASS', 'TRAP_GATE_NOT_PASS')
        require(snapshot.get('quote_status') == 'VERIFIED', 'QUOTE_NOT_VERIFIED')
        require(account.get('source') == 'MT5_PRIMARY' and account.get('verified') is True, 'ACCOUNT_NOT_VERIFIED')
        require(portfolio.get('source') == 'MT5_PRIMARY' and portfolio.get('verified') is True, 'PORTFOLIO_NOT_VERIFIED')
        require(account.get('currency') and account.get('currency') == portfolio.get('currency'), 'CURRENCY_MISMATCH')
        require(account.get('account_type') in ('ZERO_SPREAD', 'OTHER', 'UNKNOWN'), 'INVALID_ACCOUNT_TYPE')
        require(account.get('account_type') == 'ZERO_SPREAD', 'ACCOUNT_PROFILE_DIFFERS_FROM_USER_DECLARATION')
        require(portfolio.get('netting_mode') in ('NETTING', 'HEDGING'), 'NETTING_MODE_UNKNOWN')
        max_age = dec(policy.get('max_age_quote_seconds'), 'max_age_quote_seconds', min_value=Decimal(0))
        portfolio_age = dec(policy.get('max_age_portfolio_seconds'), 'max_age_portfolio_seconds', min_value=Decimal(0))
        account_age = dec(policy.get('max_age_account_seconds'), 'max_age_account_seconds', min_value=Decimal(0))
        q_time = ts(snapshot.get('quote_time'), 'quote_time')
        require(q_time <= as_of, 'FUTURE_QUOTE')
        require(Decimal(str((as_of-q_time).total_seconds())) <= max_age, 'STALE_QUOTE')
        require(Decimal(str((as_of-ts(portfolio['as_of'],'portfolio_as_of')).total_seconds())) <= portfolio_age, 'STALE_PORTFOLIO')
        require(Decimal(str((as_of-ts(account['as_of'],'account_as_of')).total_seconds())) <= account_age, 'STALE_ACCOUNT')
        if plan.get('signal_status') != 'CONFIRMED' or plan.get('setup_state') != 'CONFIRMED':
            raise RiskInputError('SETUP_NOT_CONFIRMED')
        require(plan.get('entry_type') == 'MARKET', 'ENTRY_TYPE_NOT_SUPPORTED_REFERENCE')
        require(plan.get('direction') in ('LONG', 'SHORT'), 'INVALID_DIRECTION')
        require(plan.get('source') == 'MT5_DERIVED', 'PLAN_NOT_MT5_DERIVED')
        require(plan.get('strategy_spec_frozen') is True and bool(plan.get('spec_hash')), 'SPEC_NOT_FROZEN')
        require(plan.get('expired') is False and plan.get('invalidated') is False, 'SETUP_EXPIRED_OR_INVALIDATED')
        require(plan.get('setup_id') and plan.get('horizon_id'), 'MISSING_SETUP_ID_OR_HORIZON')
        require(ts(plan.get('trigger_available_at'), 'trigger_available_at') <= as_of, 'FUTURE_TRIGGER')
        require(plan.get('trigger_source') == 'MT5_PRIMARY', 'TRIGGER_NOT_MT5')
        require(plan.get('entry_bar_closed') is True, 'TRIGGER_BAR_NOT_CLOSED')
        side = plan['direction']
        bid = dec(snapshot.get('bid'), 'bid', positive=True)
        ask = dec(snapshot.get('ask'), 'ask', positive=True)
        require(bid <= ask, 'CROSSED_BID_ASK')
        spread = ask - bid
        require(spread <= dec(policy.get('max_spread_price'), 'max_spread_price', min_value=Decimal(0)), 'SPREAD_LIMIT')
        entry = dec(plan.get('entry_price'), 'entry_price', positive=True)
        require(entry == (ask if side == 'LONG' else bid), 'ENTRY_NOT_AT_BROKER_QUOTE')
        stop = dec(plan.get('stop'), 'stop', positive=True)
        if side == 'LONG':
            require(stop < entry, 'INVALID_STOP_GEOMETRY')
        else:
            require(stop > entry, 'INVALID_STOP_GEOMETRY')
        require(plan.get('stop_is_structural') is True, 'STOP_NOT_STRUCTURAL')
        point = dec(account.get('point'), 'point', positive=True)
        stops_level = dec(account.get('trade_stops_level'), 'trade_stops_level', min_value=Decimal(0))
        min_sep = stops_level * point
        if side == 'LONG':
            require(stop < bid-min_sep or (min_sep == 0 and stop < bid), 'BROKER_STOPS_LEVEL')
        else:
            require(stop > ask+min_sep or (min_sep == 0 and stop > ask), 'BROKER_STOPS_LEVEL')
        require(account.get('trade_allowed') is True and account.get('symbol_trade_allowed') is True, 'BROKER_TRADING_DISABLED')
        require(portfolio.get('position_state_reconciled') is True, 'PORTFOLIO_RECONCILIATION_REQUIRED')
        require(policy.get('policy_frozen') is True and policy.get('policy_version'), 'RISK_POLICY_NOT_FROZEN')
        parts = plan.get('take_profits')
        require(isinstance(parts, list) and bool(parts), 'NO_TAKE_PROFITS')
        weights = Decimal(0)
        legs = []
        for i, row in enumerate(parts):
            require(isinstance(row, dict), 'INVALID_TP_LEG')
            price = dec(row.get('price'), f'tp_{i}_price', positive=True)
            weight = dec(row.get('weight'), f'tp_{i}_weight', positive=True)
            if side == 'LONG':
                require(price > entry and price > bid+min_sep, 'TP_GEOMETRY_OR_STOP_LEVEL')
            else:
                require(price < entry and price < ask-min_sep, 'TP_GEOMETRY_OR_STOP_LEVEL')
            weights += weight
            legs.append((price, weight))
        require(abs(weights - Decimal(1)) <= Decimal('0.000000001'), 'TP_WEIGHTS_NOT_ONE')
        equity = dec(account.get('equity_ccy'), 'equity_ccy', positive=True)
        free_margin = dec(account.get('free_margin_ccy'), 'free_margin_ccy', min_value=Decimal(0))
        fraction = dec(policy.get('risk_fraction'), 'risk_fraction', positive=True)
        require(fraction < Decimal(1), 'RISK_FRACTION_TOO_HIGH')
        max_daily_loss = dec(policy.get('daily_loss_limit_ccy'), 'daily_loss_limit_ccy', positive=True)
        daily_used = dec(account.get('daily_loss_used_ccy'), 'daily_loss_used_ccy', min_value=Decimal(0))
        max_total_open = dec(policy.get('max_portfolio_risk_ccy'), 'max_portfolio_risk_ccy', positive=True)
        max_cluster = dec(policy.get('max_cluster_risk_ccy'), 'max_cluster_risk_ccy', positive=True)
        reserved = dec(portfolio.get('open_positions_risk_ccy'), 'open_positions_risk_ccy', min_value=Decimal(0))
        pending = dec(portfolio.get('pending_orders_risk_ccy'), 'pending_orders_risk_ccy', min_value=Decimal(0))
        cluster = dec(portfolio.get('cluster_reserved_risk_ccy'), 'cluster_reserved_risk_ccy', min_value=Decimal(0))
        require(portfolio.get('open_positions_count') is not None and portfolio.get('pending_orders_count') is not None, 'PORTFOLIO_COUNTS_UNKNOWN')
        n_positions_dec = dec(portfolio['open_positions_count'], 'open_positions_count', min_value=Decimal(0))
        n_pending_dec = dec(portfolio['pending_orders_count'], 'pending_orders_count', min_value=Decimal(0))
        max_positions_dec = dec(policy.get('max_position_orders'), 'max_position_orders', positive=True)
        require(all(x == x.to_integral_value() for x in (n_positions_dec, n_pending_dec, max_positions_dec)), 'POSITION_COUNTS_NOT_INTEGERS')
        n_positions, n_pending = int(n_positions_dec), int(n_pending_dec)
        require(n_positions + n_pending < int(max_positions_dec), 'MAX_POSITIONS_REACHED')
        require(account.get('daily_loss_provenance') == 'MT5_RECONCILED_POLICY', 'DAILY_LOSS_NOT_RECONCILED')
        require(portfolio.get('reservation_provenance') == 'MT5_RECONCILED', 'EXPOSURE_NOT_RECONCILED')
        commission = dec(calc.get('commission_round_turn_per_lot_ccy'), 'commission_round_turn_per_lot_ccy', min_value=Decimal(0))
        slippage = dec(calc.get('stress_slippage_round_turn_per_lot_ccy'), 'stress_slippage_round_turn_per_lot_ccy', min_value=Decimal(0))
        fees = dec(calc.get('other_fees_round_turn_per_lot_ccy'), 'other_fees_round_turn_per_lot_ccy', min_value=Decimal(0))
        swap = dec(calc.get('estimated_swap_per_lot_ccy'), 'estimated_swap_per_lot_ccy', min_value=Decimal(0))
        require(calc.get('commission_verified') is True and calc.get('slippage_profile_approved') is True and calc.get('swap_policy_verified') is True, 'COST_MODEL_UNVERIFIED')
        require(calc.get('currency') == account['currency'], 'CALC_CURRENCY_MISMATCH')
        volume_step = dec(account.get('volume_step'), 'volume_step', positive=True)
        volume_min = dec(account.get('volume_min'), 'volume_min', positive=True)
        volume_max = dec(account.get('volume_max'), 'volume_max', positive=True)
        require(volume_max >= volume_min, 'INVALID_VOLUME_LIMITS')
        # Calculations: for demonstration only the synthetic fixed conversion is accepted
        # in CLI; injected broker callbacks are needed for non-synthetic profit conversion.
        cost_one_lot = commission + slippage + fees + swap
        method = calc.get('method')
        if method == 'SYNTHETIC_LINEAR':
            rate = dec(calc.get('money_per_price_unit_per_lot_ccy'), 'money_per_price_unit_per_lot_ccy', positive=True)
            margin_rate = dec(calc.get('margin_per_lot_ccy'), 'margin_per_lot_ccy', positive=True)
            def profit_fn(s, qty, e, x):
                return (x - e) * rate * qty * (1 if s == 'LONG' else -1)
            def margin_fn(s, qty, e):
                return margin_rate * qty
            out['limitations'].append('SYNTHETIC_BROKER_CALCULATIONS')
        elif method == 'BROKER_INJECTED':
            require(callable(profit_calc) and callable(margin_calc), 'BROKER_CALCULATORS_MISSING')
            def profit_fn(s, qty, e, x):
                try:
                    return dec(profit_calc(s, qty, e, x), 'broker_profit_calc')
                except Exception:
                    raise RiskInputError('BROKER_PROFIT_CALCULATOR_FAILED') from None
            def margin_fn(s, qty, e):
                try:
                    return dec(margin_calc(s, qty, e), 'broker_margin_calc', min_value=Decimal(0))
                except Exception:
                    raise RiskInputError('BROKER_MARGIN_CALCULATOR_FAILED') from None
            out['limitations'].append('CALLBACK_AUTHENTICITY_UNVERIFIED')
        else:
            raise RiskInputError('UNKNOWN_BROKER_CALCULATION_METHOD')
        gross_stop_one = profit_fn(side, Decimal(1), entry, stop)
        require(gross_stop_one < 0, 'BROKER_STOP_PROFIT_NOT_NEGATIVE')
        gross_target_one = sum((weight * profit_fn(side, Decimal(1), entry, price) for price, weight in legs), Decimal(0))
        require(gross_target_one > 0, 'BROKER_TARGET_PROFIT_NOT_POSITIVE')
        stress_loss_one = -gross_stop_one + cost_one_lot
        available = min(equity * fraction, max_daily_loss - daily_used,
                        max_total_open - reserved - pending, max_cluster - cluster)
        out['risk_budget_ccy'] = fmt(max(Decimal(0), available))
        require(available > 0, 'RISK_BUDGET_EXHAUSTED')
        lots = floorsize(available / stress_loss_one, volume_step, volume_max)
        require(lots >= volume_min, 'BELOW_VOLUME_MIN')
        gross_stop = profit_fn(side, lots, entry, stop)
        gross_reward = sum((weight * profit_fn(side, lots, entry, price) for price, weight in legs), Decimal(0))
        require(gross_stop < 0 and gross_reward > 0, 'BROKER_PROFIT_CALCULATOR_INCONSISTENT')
        modeled_loss = -gross_stop + cost_one_lot * lots
        modeled_reward = gross_reward - cost_one_lot * lots
        # Non-linear broker products may need one-step decrement after calc at rounded lots
        while lots >= volume_min and modeled_loss > available:
            lots = floorsize(lots-volume_step, volume_step, volume_max)
            if lots < volume_min:
                break
            gross_stop = profit_fn(side, lots, entry, stop)
            gross_reward = sum((weight * profit_fn(side, lots, entry, price) for price, weight in legs), Decimal(0))
            modeled_loss = -gross_stop + cost_one_lot * lots
            modeled_reward = gross_reward - cost_one_lot * lots
        require(lots >= volume_min, 'BELOW_VOLUME_MIN_AFTER_RECHECK')
        require(modeled_loss > 0 and modeled_loss <= available, 'LOSS_EXCEEDS_BUDGET')
        require(modeled_reward > 0, 'REWARD_NOT_NET_POSITIVE')
        margin = margin_fn(side, lots, entry)
        buffer = dec(policy.get('margin_buffer_multiplier'), 'margin_buffer_multiplier', min_value=Decimal(1))
        require(margin * buffer <= free_margin, 'INSUFFICIENT_FREE_MARGIN')
        rr = modeled_reward / modeled_loss
        min_rr = dec(policy.get('min_net_rr'), 'min_net_rr', positive=True)
        preferred_rr = dec(policy.get('preferred_net_rr'), 'preferred_net_rr', positive=True)
        require(preferred_rr >= min_rr, 'INVALID_RR_POLICY')
        out.update(position_size_lots=fmt(lots), modeled_loss_ccy=fmt(modeled_loss),
                   modeled_reward_ccy=fmt(modeled_reward), rr_net=fmt(rr),
                   margin_estimate_ccy=fmt(margin), portfolio_risk_after_ccy=fmt(reserved+pending+modeled_loss))
        out['cost_breakdown_ccy'] = {
            'spread_in_bid_ask_prices': True, 'spread_added_again_ccy': 0,
            'commission_ccy': fmt(commission*lots), 'slippage_stress_ccy': fmt(slippage*lots),
            'swap_ccy': fmt(swap*lots), 'other_fees_ccy': fmt(fees*lots),
        }
        if rr < min_rr:
            raise RiskInputError('NET_RR_BELOW_MINIMUM')
        out['status'] = 'PASS_WITH_LIMITATIONS'
        out['risk_gate'] = 'PASS' if rr >= preferred_rr else 'CONDITIONAL'
        out['risk_gate_reason'] = ('RR_PREFERRED_REACHED' if rr >= preferred_rr else 'RR_CONDITIONAL_NOT_EXECUTABLE')
        out['preliminary_risk_eligible'] = rr >= preferred_rr
        out['reason_codes'] = [] if rr >= preferred_rr else ['NET_RR_CONDITIONAL']
    except (RiskInputError, KeyError, TypeError, OverflowError) as exc:
        code = str(exc) if isinstance(exc, RiskInputError) else ('MISSING_' + str(exc).strip("' ").upper())
        out['status'] = 'FAIL'
        out['risk_gate'] = 'BLOCKED'
        out['risk_gate_reason'] = code
        out['reason_codes'] = [code]
        out['preliminary_risk_eligible'] = False
    return out


def main():
    p=argparse.ArgumentParser(description='Offline read-only M11 risk gate')
    p.add_argument('--input',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    result=evaluate(json.loads(Path(args.input).read_text(encoding='utf-8')))
    Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('M11:',result['risk_gate'],result['risk_gate_reason'],'| orders_sent=0')

if __name__ == '__main__':
    main()
