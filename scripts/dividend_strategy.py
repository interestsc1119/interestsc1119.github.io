"""Valuation-first, contrarian allocation rules, not a fair-value model.

CSI's price-history field named ``peg`` is documented as rolling P/E by
AKShare; it is NOT the price/earnings-to-growth (PEG) ratio. Its historical
series is kept separate from PE1/PE2 and equal-weight third-party series.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
D = Decimal
BASIS = "CSI_PERF_PE_TTM_AND_DP1"
DEFAULT_POLICY = {
    "pe_low_percentile": 30, "pe_high_percentile": 70,
    "min_dividend_yield_pct": 4, "max_tranche_budget_pct": 20,
    "min_days_between_buys": 30, "valuation_reference_url": None,
}


def positive(value: object) -> Decimal | None:
    try:
        number = D(str(value))
        return number if number.is_finite() and number > 0 else None
    except (InvalidOperation, ValueError):
        return None


def rounded(value: Decimal) -> float:
    return float(value.quantize(D("0.01")))


def load_policy() -> dict:
    path = ROOT / "config" / "dividend100_strategy.json"
    policy = {**DEFAULT_POLICY, **json.loads(path.read_text(encoding="utf-8"))} if path.exists() else dict(DEFAULT_POLICY)
    low, high = policy["pe_low_percentile"], policy["pe_high_percentile"]
    if not 0 <= low < high <= 100:
        raise ValueError("PE分位阈值必须满足0≤低位<高位≤100")
    if not 0 < policy["max_tranche_budget_pct"] <= 100 or not 1 <= policy["min_days_between_buys"] <= 365:
        raise ValueError("每笔预算比例或买入间隔无效")
    if not 0 < policy["min_dividend_yield_pct"] < 30:
        raise ValueError("股息率阈值无效")
    url = policy.get("valuation_reference_url")
    if url and urlparse(url).scheme != "https":
        raise ValueError("估值参照接口必须使用HTTPS")
    return policy


def historical_percentile(current: Decimal, history: list[Decimal]) -> Decimal:
    """Midrank empirical percentile: lower P/E gives a lower rank.

    A short dividend history is never presented as a five-year percentile.
    """
    if len(history) < 1000:
        raise ValueError("PE分位至少需要1000个历史交易日")
    less = sum(value < current for value in history)
    equal = sum(value == current for value in history)
    return (D(less) + D(equal) / 2) / D(len(history)) * 100


def build_valuation(history: list[dict], indicators: list[dict], reference: dict | None,
                    now: datetime, as_of: str | None) -> dict:
    quality = {"status": "pending", "label": "官方估值单源，独立同口径核验待补充"}
    result = {
        "status": "pending", "verification": quality, "basis": BASIS,
        "pe_ttm": None, "pe_percentile_5y": None, "dividend_yield": None,
        "pb": None, "history_days": 0, "pe_as_of": None, "dividend_as_of": None,
        "methodology": "PE分位使用中证官方行情滚动PE同一序列，近5年最多1250个有效交易日（至少1000日），以小于当前值的数量加相等数量的一半计算经验分位。股息率单独使用官方DP1总股本口径；不拼接PE2、等权PE或短期股息率分位。PB尚未接入。",
        "risk_note": "历史低分位不等于内在价值低估；股息率不是承诺收益，分红可减少。自动数据不能证明未来分红可持续性，购买前需人工核对基金及成分股公告。",
        "sources": {"history": "https://www.csindex.com.cn/#/indices/family/detail?indexCode=930955",
                    "indicator": "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/930955indicator.xls"},
    }
    if not as_of:
        return result
    end = date.fromisoformat(as_of)
    try:
        start = end.replace(year=end.year - 5)
    except ValueError:
        start = end.replace(year=end.year - 5, day=28)
    values = {row["date"]: positive(row.get("pe_ttm")) for row in history
              if start.isoformat() <= row["date"] <= as_of and positive(row.get("pe_ttm"))}
    dates = sorted(values)[-1250:]
    if dates:
        current = values[dates[-1]]
        result.update({"pe_ttm": rounded(current), "pe_as_of": dates[-1], "history_days": len(dates),
                       "history_start": dates[0], "history_end": dates[-1]})
        if len(dates) >= 1000:
            result["pe_percentile_5y"] = rounded(historical_percentile(current, [values[day] for day in dates]))
    rows = sorted((row for row in indicators if row["date"] <= as_of), key=lambda row: row["date"])
    indicator = rows[-1] if rows else {}
    dividend = positive(indicator.get("dividend_yield"))
    result.update({"dividend_yield": rounded(dividend) if dividend else None, "dividend_as_of": indicator.get("date"),
                   "official_pe1": indicator.get("pe_total")})
    if result["pe_as_of"] != as_of or result["dividend_as_of"] != as_of:
        quality["label"] = "估值与收盘日期不一致，暂停配置提示"
        return result
    if result["pe_percentile_5y"] is None or not dividend:
        quality["label"] = "估值历史或股息率不足，暂停配置提示"
        return result
    if not 0 <= (now.date() - end).days <= 7:
        quality["label"] = "估值数据已过期，暂停配置提示"
        return result
    # A second CSI delivery channel is an internal consistency check only.
    # It must never be mislabeled as independent cross-source verification.
    pe1 = positive(indicator.get("pe_total"))
    if pe1:
        result["official_channel_pe_difference_pct"] = rounded(abs(current - pe1) / current * 100)
    if not reference:
        return result
    source = reference.get("source") or {}
    host = (urlparse(str(source.get("url") or "")).hostname or "").lower()
    valid_source = source.get("name") and host and urlparse(str(source.get("url") or "")).scheme == "https" and host != "example.com" and not (host == "csindex.com.cn" or host.endswith(".csindex.com.cn"))
    if reference.get("code") != "930955" or reference.get("basis") != BASIS or not valid_source:
        quality["label"] = "估值参照身份、独立来源或计算口径不匹配"
        return result
    result["sources"]["reference"] = source["url"]
    result["reference_source"] = source["name"]
    if reference.get("date") != as_of:
        quality["label"] = "估值参照日期不一致，暂停配置提示"
        return result
    reference_pe, reference_dividend = positive(reference.get("pe_ttm")), positive(reference.get("dividend_yield"))
    if not reference_pe or not reference_dividend:
        quality["label"] = "第二源PE或股息率缺失，暂停配置提示"
        return result
    pe_error = abs(current - reference_pe) / current * 100
    dividend_error = abs(dividend - reference_dividend) / dividend * 100
    quality.update({"pe_difference_pct": rounded(pe_error), "dividend_difference_pct": rounded(dividend_error)})
    if pe_error > 1 or dividend_error > 1:
        quality.update({"status": "mismatch", "label": "同口径估值两源差异超过1%，暂停配置提示"})
        return result
    quality.update({"status": "verified", "label": "PE与股息率已同日同口径独立核验"})
    result["status"] = "verified"
    return result


def build_allocation_advice(metrics: dict, price_verified: bool, fresh: bool,
                            valuation: dict | None = None, policy: dict | None = None) -> dict:
    valuation, policy = valuation or {}, policy or DEFAULT_POLICY
    gap = metrics.get("distance_ma250_pct")
    rank, dividend = valuation.get("pe_percentile_5y"), valuation.get("dividend_yield")
    risk = "年线方向仅作风险提示，不作为买入否决条件。"
    if (metrics.get("ma250_change_20d_pct") or 0) < 0:
        risk += "目前年线下行，买入后仍可能继续下跌，不因跌幅扩大而自动加倍。"
    common = {"eligible": False, "max_tranche_budget_pct": policy["max_tranche_budget_pct"],
              "min_days_between_buys": policy["min_days_between_buys"], "risk": risk,
              "manual_checks": "执行前确认长期闲置资金、能承受权益回撤、分红风险和基金费用/溢价；页面不知道你的真实仓位。"}
    def advice(state: str, title: str, reason: str, action: str, eligible: bool = False) -> dict:
        return {**common, "state": state, "title": title, "reason": reason, "action": action, "eligible": eligible}
    if not price_verified or not fresh or gap is None:
        return advice("paused", "行情待核验，暂缓新增配置", "收盘价与年线未通过核验或已过期。", "暂停依据本模块新增投入；不把缺数据解释为指数不值得持有。")
    if valuation.get("verification", {}).get("status") != "verified" or rank is None or dividend is None:
        return advice("paused", "估值待核验，暂缓新增配置", valuation.get("verification", {}).get("label") or "尚未取得完整且独立核验的估值。", "可观察年线下方的位置，但不将其直接等同于便宜；等待同口径估值核验。")
    if rank > policy["pe_low_percentile"]:
        state = "wait" if rank >= policy["pe_high_percentile"] else "observe"
        return advice(state, "估值尚未进入低位配置区", f"PE近5年分位{rank:.2f}%，未达到≤{policy['pe_low_percentile']}%的观察阈值；低于年线也不会单独触发买入。", "保留本次计划资金，等待估值改善；不根据单日涨跌改变长期持仓。")
    if dividend < policy["min_dividend_yield_pct"]:
        return advice("observe", "股息率尚未满足配置条件", f"股息率{dividend:.2f}%，低于预设{policy['min_dividend_yield_pct']}%观察阈值。", "先核对分红变化，不仅因为PE分位低就买入。")
    if gap > 0:
        return advice("wait", "估值低位，等待年线附近或下方", f"估值满足观察条件，但点位仍高于年线{gap:.2f}%。", "本策略选择不追高，保留资金等待年线附近或下方；这不是所有投资者的通用买卖要求。")
    return advice("consider", "可考虑逢低买入一笔", f"PE近5年分位{rank:.2f}%、股息率{dividend:.2f}%，点位相对年线{gap:+.2f}%；年线下降不直接否决配置。", f"人工核对风险与剩余预算后，每笔最多使用红利低波100专属预算的{policy['max_tranche_budget_pct']}%，不得超过剩余预算；两笔至少间隔{policy['min_days_between_buys']}个自然日。每日处于配置区不表示每天都应买入。", True)
