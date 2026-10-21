"""Bilingual (English + Simplified Chinese) Telegram messages of the Frog Wizard 🐸🪄 — Pepe Magic vs. Wall Street.

Rules:
* Both language versions are generated from ONE verified event / report object. Every value (price, volume, P&L, time, ticket,
  currency) is formatted ONCE into a string and the same string is inserted into both versions - the two languages can never
  show different numbers.
* Symbols, numbers, ticket identifiers and currency codes are never translated.
* Output is Telegram HTML: every dynamic value is HTML-escaped; message length is validated (Telegram limit 4096 chars).
* English first, Chinese below (configurable: order = "en_zh" | "zh_en"). Simplified Chinese only.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timezone

TELEGRAM_LIMIT = 4096
SEP = "━━━━━━━━━━━━━━━━━━"
RISK_EN = "⚠️ Trading involves risk. This message is for informational purposes only."
RISK_ZH = "⚠️ 交易存在风险。本消息仅供信息参考。"
PAST_EN = "⚠️ Historical performance does not guarantee future results."
PAST_ZH = "⚠️ 历史表现不代表未来收益。"

TERMS = {  # consistent terminology (spec section 2)
    "BUY": "买入", "SELL": "卖出", "ENTRY PRICE": "入场价格", "EXIT PRICE": "出场价格", "STOP LOSS": "止损", "TAKE PROFIT": "止盈",
    "VOLUME": "交易手数", "OPEN POSITION": "开仓", "CLOSED POSITION": "平仓", "PARTIAL CLOSE": "部分平仓", "REALIZED P&L": "已实现盈亏",
    "PROFIT": "盈利", "LOSS": "亏损", "BREAK EVEN": "保本", "TRADE STATUS": "交易状态",
}
PERIOD = {"all": ("All available history", "全部可用历史记录"), "today": ("Today", "今日"), "week": ("This week", "本周"),
          "month": ("This month", "本月")}


class MessageTooLong(ValueError):
    pass


def esc(x) -> str:
    return html.escape("" if x is None else str(x), quote=False)


def fmt_price(v, digits: int) -> str | None:
    return None if v is None else f"{float(v):.{int(digits)}f}"


def fmt_vol(v) -> str:
    return f"{float(v):.2f}"


def fmt_money(v, ccy: str, signed: bool = True) -> str:
    v = float(v)
    s = "+" if signed and v > 0 else ("-" if v < 0 else "")
    return f"{s}{abs(v):,.2f} {ccy}".strip()


def fmt_pct(v, signed: bool = False) -> str:
    if v is None:
        return "N/A"
    return f"{'+' if signed and v > 0 else ''}{float(v):.2f}%"


def fmt_time(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def assemble(en: list[str], zh: list[str], footer: list[str], order: str = "en_zh") -> str:
    first, second = (en, zh) if order != "zh_en" else (zh, en)
    text = "\n".join(first + [SEP] + second + ([""] + footer if footer else []))
    validate(text)
    return text


def validate(text: str) -> str:
    if len(text) > TELEGRAM_LIMIT:
        raise MessageTooLong(f"{len(text)} > {TELEGRAM_LIMIT}")
    return text


# ------------------------------------------------------------------------------------------------ trade events
@dataclass
class TradeEvent:
    """One VERIFIED trade event read from MT5 (all values from the terminal; nothing estimated)."""
    kind: str                         # OPENED / CLOSED / PARTIAL / PROTECTION / CONNECTION
    symbol: str = ""
    side: str = ""                    # BUY / SELL
    position_id: int | None = None
    digits: int = 2                   # price digits of the symbol
    currency: str = ""
    entry_price: float | None = None
    exit_price: float | None = None
    sl: float | None = None
    tp: float | None = None
    prev_sl: float | None = None
    prev_tp: float | None = None
    volume: float | None = None       # opened volume
    closed_volume: float | None = None
    remaining_volume: float | None = None
    gross: float | None = None
    commission: float | None = None
    swap: float | None = None
    fee: float | None = None
    net: float | None = None
    classification: str | None = None  # WIN / LOSS / BREAK_EVEN (closed)
    time: float | None = None
    breakeven: bool = False           # protection: new SL == entry price (reliably detected)
    delayed: bool = False             # published after a reconnection
    connection_state: str | None = None   # CONNECTION events: LOST / RESTORED / HISTORY_INCOMPLETE
    account_label: str | None = None
    extra: dict = field(default_factory=dict)


def _side(e: TradeEvent) -> tuple[str, str]:
    return ("BUY 🟢", "买入 🟢") if e.side == "BUY" else ("SELL 🔴", "卖出 🔴")


def _values(e: TradeEvent) -> dict:
    """All dynamic values formatted once (shared by both languages)."""
    p = lambda x: fmt_price(x, e.digits)  # noqa: E731
    return {"symbol": esc(e.symbol), "entry": esc(p(e.entry_price)), "exit": esc(p(e.exit_price)), "sl": esc(p(e.sl)), "tp": esc(p(e.tp)),
            "prev_sl": esc(p(e.prev_sl)), "prev_tp": esc(p(e.prev_tp)),
            "vol": esc(fmt_vol(e.volume)) if e.volume is not None else None,
            "cvol": esc(fmt_vol(e.closed_volume)) if e.closed_volume is not None else None,
            "rvol": esc(fmt_vol(e.remaining_volume)) if e.remaining_volume is not None else None,
            "net": esc(fmt_money(e.net, e.currency)) if e.net is not None else None,
            "gross": esc(fmt_money(e.gross, e.currency)) if e.gross is not None else None,
            "costs": esc(fmt_money((e.commission or 0) + (e.swap or 0) + (e.fee or 0), e.currency)) if e.net is not None else None,
            "pos": esc(e.position_id) if e.position_id is not None else None, "time": esc(fmt_time(e.time)), "acc": esc(e.account_label)}


def _delayed(e: TradeEvent, en: list, zh: list) -> None:
    if e.delayed:
        en.append("⏱️ Reported after reconnection (event time shown above).")
        zh.append("⏱️ 重新连接后补发（事件时间见上）。")


def render_event(e: TradeEvent, order: str = "en_zh") -> str:
    v = _values(e)
    sen, szh = _side(e)
    unset_en, unset_zh = "not set", "未设置"
    if e.kind == "OPENED":
        en = ["🐸🪄 <b>FROG WIZARD — NEW TRADE OPENED</b>", f"⚔️ Instrument: {v['symbol']}", f"📊 Direction: {sen}", f"🎯 Entry Price: {v['entry']}",
              f"🛡️ Stop Loss: {v['sl'] or unset_en}", f"💰 Take Profit: {v['tp'] or unset_en}", f"📦 Volume: {v['vol']} lots",
              f"🔖 Position: #{v['pos']} · {v['time']}",
              "🧙 The Frog Wizard: Another magical operation begins. Let's see how the market unfolds."]
        zh = ["🐸🪄 <b>蛙巫师 — 新交易已开仓</b>", f"⚔️ 交易品种： {v['symbol']}", f"📊 交易方向： {szh}", f"🎯 入场价格： {v['entry']}",
              f"🛡️ 止损： {v['sl'] or unset_zh}", f"💰 止盈： {v['tp'] or unset_zh}", f"📦 交易手数： {v['vol']} 手",
              f"🔖 持仓编号： #{v['pos']} · {v['time']}",
              "🧙 蛙巫师： 新一轮魔法交易已经开始，让我们静待市场揭晓结果。"]
        _delayed(e, en, zh)
        return assemble(en, zh, [RISK_EN, RISK_ZH], order)
    if e.kind in ("CLOSED", "PARTIAL"):
        st_en = {"WIN": "CLOSED IN PROFIT", "LOSS": "CLOSED AT A LOSS", "BREAK_EVEN": "CLOSED AT BREAK EVEN"}.get(e.classification or "", "CLOSED")
        st_zh = {"WIN": "盈利平仓", "LOSS": "亏损平仓", "BREAK_EVEN": "保本平仓"}.get(e.classification or "", "已平仓")
        partial = e.kind == "PARTIAL"
        en = ["🐸💰 <b>FROG WIZARD — " + ("PARTIAL CLOSE" if partial else "TRADE CLOSED") + "</b>", f"⚔️ Instrument: {v['symbol']}",
              f"📊 Direction: {sen}", f"📍 Entry Price: {v['entry']}", f"🏁 Exit Price: {v['exit']}", f"📦 Closed Volume: {v['cvol']} lots"]
        zh = ["🐸💰 <b>蛙巫师 — " + ("部分平仓" if partial else "交易已平仓") + "</b>", f"⚔️ 交易品种： {v['symbol']}",
              f"📊 交易方向： {szh}", f"📍 入场价格： {v['entry']}", f"🏁 出场价格： {v['exit']}", f"📦 平仓手数： {v['cvol']} 手"]
        if partial and v["rvol"] is not None:
            en.append(f"📦 Remaining Volume: {v['rvol']} lots")
            zh.append(f"📦 剩余手数： {v['rvol']} 手")
        en += [f"💵 Realized P&L (net): {v['net']}", f"🧾 Gross P&L: {v['gross']} · Commission/swap/fees: {v['costs']}"]
        zh += [f"💵 已实现盈亏（净值）： {v['net']}", f"🧾 毛盈亏： {v['gross']} · 佣金/隔夜利息/费用： {v['costs']}"]
        if not partial:
            en.append(f"📈 Status: {st_en}")
            zh.append(f"📈 交易状态： {st_zh}")
            en.append("🪄 The Frog Wizard: Another operation is complete. The result has been recorded in the wizard's ledger.")
            zh.append("🪄 蛙巫师： 又一笔交易圆满结束，结果已记录在蛙巫师的交易账簿中。")
        else:
            en.append("🪄 The Frog Wizard: Part of the position is secured; the rest stays in play.")
            zh.append("🪄 蛙巫师： 部分仓位已锁定，其余仓位继续持有。")
        en.append(f"🔖 Position: #{v['pos']} · {v['time']}")
        zh.append(f"🔖 持仓编号： #{v['pos']} · {v['time']}")
        _delayed(e, en, zh)
        return assemble(en, zh, [RISK_EN, RISK_ZH], order)
    if e.kind == "PROTECTION":
        removed_en, removed_zh = "removed", "已移除"

        def line(label_en, label_zh, prev, new, changed):
            if not changed:
                return f"• {label_en}: {new or unset_en}", f"• {label_zh}：{new or unset_zh}"
            return (f"• Previous {label_en}: {prev or unset_en}\n• New {label_en}: {new or removed_en}",
                    f"• 原{label_zh}：{prev or unset_zh}\n• 新{label_zh}：{new or removed_zh}")
        sl_changed, tp_changed = e.prev_sl != e.sl, e.prev_tp != e.tp
        a_en, a_zh = line("SL", "止损", v["prev_sl"], v["sl"], sl_changed)
        b_en, b_zh = line("TP", "止盈", v["prev_tp"], v["tp"], tp_changed)
        en = ["🐸🛡️ <b>FROG WIZARD — TRADE PROTECTION UPDATED</b>", f"Instrument: {v['symbol']} | Direction: {e.side}", a_en, b_en]
        zh = ["🐸🛡️ <b>蛙巫师 — 交易保护位已更新</b>", f"交易品种： {v['symbol']} | 交易方向： {TERMS.get(e.side, e.side)}", a_zh, b_zh]
        if e.breakeven:
            en.append("✅ Stop Loss moved to BREAK EVEN (entry price).")
            zh.append("✅ 止损已移至保本位（入场价格）。")
        en.append(f"🔖 Position: #{v['pos']} · {v['time']}")
        zh.append(f"🔖 持仓编号： #{v['pos']} · {v['time']}")
        _delayed(e, en, zh)
        return assemble(en, zh, [], order)
    if e.kind == "CONNECTION":
        msg = {"LOST": ("🐸⚠️ <b>FROG WIZARD — MT5 CONNECTION LOST</b>", "Trade notifications and statistics are paused until the terminal reconnects.",
                        "🐸⚠️ <b>蛙巫师 — MT5 连接中断</b>", "交易通知与统计已暂停，待终端重新连接后恢复。"),
               "RESTORED": ("🐸✅ <b>FROG WIZARD — MT5 CONNECTION RESTORED</b>", "History is being reconciled; missed events will be reported.",
                            "🐸✅ <b>蛙巫师 — MT5 连接已恢复</b>", "正在核对历史记录，错过的事件将被补发。"),
               "HISTORY_INCOMPLETE": ("🐸⚠️ <b>FROG WIZARD — HISTORY INCOMPLETE</b>", "Some statistics cannot be verified and are shown as N/A.",
                                      "🐸⚠️ <b>蛙巫师 — 历史记录不完整</b>", "部分统计数据无法核实，将显示为 N/A。")}[e.connection_state or "LOST"]
        en = [msg[0], msg[1]] + ([f"Account: {v['acc']}"] if v["acc"] else []) + [f"🕒 {v['time']}"]
        zh = [msg[2], msg[3]] + ([f"账户： {v['acc']}"] if v["acc"] else []) + [f"🕒 {v['time']}"]
        return assemble(en, zh, [], order)
    raise ValueError(f"UNKNOWN_EVENT:{e.kind}")


# ------------------------------------------------------------------------------------------------ statistics reports
def _ccy_block(agg: dict, show_money: bool) -> tuple[list[str], list[str]]:
    """Money lines: one line per currency (never summed across currencies)."""
    en, zh = [], []
    for ccy, c in sorted((agg.get("by_currency") or {}).items()):
        if show_money:
            nm = esc(fmt_money(c["net_trading_profit"], ccy))
            en.append(f"• Net realized P&L ({esc(ccy)}): {nm}")
            zh.append(f"• 已实现净盈亏（{esc(ccy)}）：{nm}")
        r = esc(fmt_pct(c.get("roi"), signed=True))
        en.append(f"• ROI ({esc(ccy)}): {r}")
        zh.append(f"• 投资回报率（ROI，{esc(ccy)}）：{r}")
    return en, zh


def _warn_lines(warnings: list[str]) -> tuple[list[str], list[str]]:
    en, zh = [], []
    if any(w.startswith("INCOMPLETE_HISTORY") or w == "HISTORY_NOT_COVERING_PERIOD" for w in warnings):
        en.append("⚠️ History is incomplete for this period – affected figures are N/A or partial.")
        zh.append("⚠️ 本周期历史记录不完整——相关数据显示为 N/A 或不完整。")
    if "DISCONNECTED" in warnings:
        en.append("⚠️ MT5 is disconnected – figures are from the last verified synchronisation.")
        zh.append("⚠️ MT5 未连接——数据来自最近一次核实的同步。")
    return en, zh


def render_stats(agg: dict, period: str, *, show_money: bool = True, order: str = "en_zh", synced_at: float | None = None) -> str:
    pe, pz = PERIOD.get(period, (period, period))
    wr = esc(fmt_pct(agg.get("win_rate")))
    n = {k: esc(agg.get(k) if agg.get(k) is not None else "N/A") for k in ("accounts", "completed_trades", "wins", "losses", "break_even", "open_positions", "deals")}
    me, mz = _ccy_block(agg, show_money)
    we, wz = _warn_lines(agg.get("warnings") or [])
    ts = esc(fmt_time(synced_at)) if synced_at else "—"
    en = ["🐸🪄 <b>FROG WIZARD — TRADING STATISTICS</b>", SEP, "📊 <b>ACCOUNT OVERVIEW</b>", f"• Monitored accounts: {n['accounts']}",
          f"• Deals: {n['deals']}", f"• Completed trades: {n['completed_trades']}", f"• Winning trades: {n['wins']}", f"• Losing trades: {n['losses']}",
          f"• Break-even trades: {n['break_even']}", f"• Win rate: {wr}", "", "💰 <b>PERFORMANCE</b>", *me, f"• Open positions: {n['open_positions']}",
          f"• Reporting period: {pe}", f"• Last MT5 sync: {ts}", *we,
          "ℹ️ Win rate = wins / (wins + losses); break-even trades excluded and shown separately. P&L after commission, swap and fees."]
    zh = ["🐸🪄 <b>蛙巫师 — 交易统计报告</b>", "📊 <b>账户概览</b>", f"• 已监控账户数：{n['accounts']}", f"• 成交笔数：{n['deals']}",
          f"• 已完成交易：{n['completed_trades']}", f"• 盈利交易：{n['wins']}", f"• 亏损交易：{n['losses']}", f"• 持平交易：{n['break_even']}",
          f"• 胜率：{wr}", "", "💰 <b>交易表现</b>", *mz, f"• 当前持仓数：{n['open_positions']}", f"• 统计周期：{pz}", f"• 最近 MT5 同步：{ts}", *wz,
          "ℹ️ 胜率 = 盈利交易 /（盈利交易 + 亏损交易）；持平交易不计入，单独列示。盈亏已扣除佣金、隔夜利息及费用。"]
    footer = ["🧙 The Frog Wizard: Every trade leaves a mark in the ledger. Track the numbers, respect the risk, and let the data speak.",
              "🧙 蛙巫师： 每一笔交易都会留下记录。关注数据，尊重风险，让事实说明一切。", PAST_EN, PAST_ZH]
    return assemble(en, zh, footer, order)


def render_winratio(agg: dict, period: str, order: str = "en_zh") -> str:
    pe, pz = PERIOD.get(period, (period, period))
    n = {k: esc(agg.get(k)) for k in ("completed_trades", "wins", "losses", "break_even")}
    wr = esc(fmt_pct(agg.get("win_rate")))
    we, wz = _warn_lines(agg.get("warnings") or [])
    en = ["🐸🎯 <b>FROG WIZARD — WIN RATIO</b>", f"• Winning trades: {n['wins']}", f"• Losing trades: {n['losses']}", f"• Break-even trades: {n['break_even']}",
          f"• Completed trades: {n['completed_trades']}", f"• Win rate: {wr}", f"• Reporting period: {pe}", *we,
          "ℹ️ Win rate = wins / (wins + losses). Open positions are not included."]
    zh = ["🐸🎯 <b>蛙巫师 — 胜率</b>", f"• 盈利交易：{n['wins']}", f"• 亏损交易：{n['losses']}", f"• 持平交易：{n['break_even']}",
          f"• 已完成交易：{n['completed_trades']}", f"• 胜率：{wr}", f"• 统计周期：{pz}", *wz, "ℹ️ 胜率 = 盈利交易 /（盈利交易 + 亏损交易）。未平仓持仓不计入。"]
    return assemble(en, zh, [PAST_EN, PAST_ZH], order)


METHOD = {"SIMPLE": ("Net trading profit / starting capital", "交易净利润 / 期初资本"),
          "MODIFIED_DIETZ": ("Modified Dietz (deposits/withdrawals removed, time-weighted capital) – approximation",
                             "修正 Dietz 法（剔除出入金，按时间加权资本）——近似值"),
          "TWR": ("Time-weighted return from equity snapshots", "基于净值快照的时间加权收益率")}
LIMIT = {"HISTORY_INCOMPLETE_FOR_PERIOD": ("history incomplete for this period", "本周期历史记录不完整"),
         "STARTING_CAPITAL_ZERO_OR_NEGATIVE": ("starting capital is zero or unavailable", "期初资本为零或无法获取"),
         "NO_ACCOUNT_BALANCE": ("account balance unavailable (MT5 not connected)", "无法获取账户余额（MT5 未连接）"),
         "NO_TRADES": ("no trades yet", "暂无交易"), "DIETZ_DENOMINATOR_NOT_POSITIVE": ("capital base not positive", "资本基数非正"),
         "TWR_NEEDS_EQUITY_SNAPSHOTS_AT_EACH_FLOW": ("TWR needs equity snapshots at each cash flow", "时间加权收益需在每笔出入金时有净值快照")}


def render_roi(per_account: list[dict], period: str, *, show_money: bool = True, order: str = "en_zh") -> str:
    pe, pz = PERIOD.get(period, (period, period))
    en = ["🐸📈 <b>FROG WIZARD — ROI</b>", f"• Reporting period: {pe}"]
    zh = ["🐸📈 <b>蛙巫师 — 投资回报率（ROI）</b>", f"• 统计周期：{pz}"]
    for a in per_account:
        r = a.get("roi") or {}
        ccy = a["currency"]
        val = esc(fmt_pct(r.get("value"), signed=True))
        me, mz = METHOD.get(r.get("method") or "", ("N/A", "N/A"))
        lab = esc(a.get("label") or a["account"])
        en += ["", f"🏦 {lab} ({esc(ccy)})", f"• ROI: {val}", f"• Method: {esc(me)}"]
        zh += ["", f"🏦 {lab}（{esc(ccy)}）", f"• 投资回报率：{val}", f"• 计算方法：{esc(mz)}"]
        if show_money:
            cap = esc(fmt_money(r["capital_base"], ccy, signed=False)) if r.get("capital_base") is not None else "N/A"
            net = esc(fmt_money(r.get("net_profit") or 0, ccy))
            dep, wd = esc(fmt_money(a.get("deposits") or 0, ccy, signed=False)), esc(fmt_money(a.get("withdrawals") or 0, ccy, signed=False))
            en += [f"• Capital base: {cap}", f"• Net trading profit: {net}", f"• Deposits / withdrawals: {dep} / {wd}"]
            zh += [f"• 资本基数：{cap}", f"• 交易净利润：{net}", f"• 入金 / 出金：{dep} / {wd}"]
        lims = [x for x in r.get("limitations") or [] if not x.startswith("APPROXIMATION")]
        if lims:
            en.append("• N/A because: " + esc("; ".join(LIMIT.get(x, (x, x))[0] for x in lims)))
            zh.append("• 显示 N/A 的原因：" + esc("；".join(LIMIT.get(x, (x, x))[1] for x in lims)))
    en.append("ℹ️ Deposits and withdrawals are not counted as profit or loss.")
    zh.append("ℹ️ 入金和出金不计入盈亏。")
    return assemble(en, zh, [PAST_EN, PAST_ZH], order)


def render_account(accts: list[dict], order: str = "en_zh") -> str:
    """Owner/admin only: balance, equity, currency, connection status - never login, server or credentials."""
    en, zh = ["🐸🏦 <b>FROG WIZARD — ACCOUNT</b>"], ["🐸🏦 <b>蛙巫师 — 账户</b>"]
    for a in accts:
        ccy = a.get("currency") or ""
        conn_en = "connected" if a.get("connected") else "disconnected"
        conn_zh = "已连接" if a.get("connected") else "未连接"
        bal = esc(fmt_money(a["balance"], ccy, signed=False)) if a.get("balance") is not None else "N/A"
        eq = esc(fmt_money(a["equity"], ccy, signed=False)) if a.get("equity") is not None else "N/A"
        fl = esc(fmt_money(a["floating"], ccy)) if a.get("floating") is not None else "N/A"
        lab = esc(a.get("label"))
        en += ["", f"• Account: {lab}", f"• Currency: {esc(ccy)}", f"• Balance: {bal}", f"• Equity: {eq}", f"• Floating P&L: {fl}",
               f"• Open positions: {esc(a.get('open_positions'))}", f"• MT5 status: {conn_en}", f"• Last sync: {esc(fmt_time(a.get('synced_at')))}"]
        zh += ["", f"• 账户：{lab}", f"• 账户货币：{esc(ccy)}", f"• 余额：{bal}", f"• 净值：{eq}", f"• 浮动盈亏：{fl}",
               f"• 当前持仓数：{esc(a.get('open_positions'))}", f"• MT5 状态：{conn_zh}", f"• 最近同步：{esc(fmt_time(a.get('synced_at')))}"]
    return assemble(en, zh, [], order)


def render_accounts(n: int, order: str = "en_zh") -> str:
    en = ["🐸🏦 <b>FROG WIZARD — MONITORED ACCOUNTS</b>", f"• Accounts configured and monitored by this bot: {n}",
          "ℹ️ Only accounts explicitly configured for monitoring are counted (not all accounts saved in the MT5 terminal)."]
    zh = ["🐸🏦 <b>蛙巫师 — 监控账户</b>", f"• 本机器人已配置并监控的账户数：{n}", "ℹ️ 仅统计明确配置为监控的账户（不包括 MT5 终端中保存的全部账户）。"]
    return assemble(en, zh, [], order)


def render_text(key: str, order: str = "en_zh", **kw) -> str:
    T = {"denied": ("⛔ This command is available only to the bot owner in a private chat.", "⛔ 此命令仅限机器人所有者在私聊中使用。"),
         "unknown": ("Unknown command. Available: /stats [today|week|month|all], /winratio [period], /roi [period], /accounts, /account",
                     "未知命令。可用命令：/stats [today|week|month|all]、/winratio [周期]、/roi [周期]、/accounts、/account"),
         "bad_period": ("Unknown period. Use: today, week, month or all.", "未知周期。请使用：today、week、month 或 all。"),
         "rate": ("Please wait a moment before the next command.", "请稍候再发送下一条命令。"),
         "test": ("🐸🪄 FROG WIZARD — configuration test. No trade is reported in this message.", "🐸🪄 蛙巫师 — 配置测试。本消息不包含任何交易。"),
         "unavailable": ("⚠️ Statistics are unavailable: no verified MT5 data has been synchronised yet.", "⚠️ 统计不可用：尚未同步任何已核实的 MT5 数据。")}
    en, zh = T[key]
    return assemble([en.format(**kw)], [zh.format(**kw)], [], order)
