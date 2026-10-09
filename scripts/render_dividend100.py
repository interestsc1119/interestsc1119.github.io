"""Render the dedicated dividend-index section for market.html."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def safe(value: object) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def number(value: object, suffix: str = "", signed: bool = False) -> str:
    if value is None:
        return "待更新"
    return f"{float(value):+,.2f}{suffix}" if signed else f"{float(value):,.2f}{suffix}"


def direction(value: object) -> str:
    if value is None:
        return "flat"
    return "up" if float(value) > 0 else "down" if float(value) < 0 else "flat"


def chart_svg(rows: list[dict]) -> tuple[str, str]:
    if len(rows) < 2:
        return '<p class="empty">正在等待足够的年线历史数据。</p>', "#68736e"
    width, height, left, right, top, bottom = 900, 290, 64, 18, 15, 38
    numbers = [float(row[key]) for row in rows for key in ("close", "ma250")]
    low, high = min(numbers), max(numbers)
    padding = max((high - low) * .08, 1)
    low, high = low - padding, high + padding
    def x(i: int) -> float:
        return left + i * (width - left - right) / (len(rows) - 1)
    def y(value: float) -> float:
        return top + (high - value) / (high - low) * (height - top - bottom)
    color = "#a6403c" if rows[-1]["close"] > rows[0]["close"] else "#1e6f54" if rows[-1]["close"] < rows[0]["close"] else "#68736e"
    parts = [f'<svg class="dividend-chart" viewBox="0 0 {width} {height}" role="img" aria-labelledby="dividend-chart-title"><title id="dividend-chart-title">红利低波100收盘点位与250日年线</title>']
    for fraction in (0, .25, .5, .75, 1):
        value = low + (high - low) * fraction
        coordinate = y(value)
        parts.append(f'<line class="grid" x1="{left}" x2="{width-right}" y1="{coordinate:.1f}" y2="{coordinate:.1f}"/><text class="chart-label" x="{left-8}" y="{coordinate+4:.1f}" text-anchor="end">{value:,.0f}</text>')
    for key, tone, dashed in (("close", color, ""), ("ma250", "#a86517", ' stroke-dasharray="6 4"')):
        points = " ".join(f"{x(i):.1f},{y(float(row[key])):.1f}" for i, row in enumerate(rows))
        parts.append(f'<polyline data-series="{key}" points="{points}" fill="none" stroke="{tone}" stroke-width="2.5" stroke-linejoin="round"{dashed}/>')
    for i, anchor in ((0, "start"), (len(rows)//2, "middle"), (len(rows)-1, "end")):
        parts.append(f'<text class="chart-label" x="{x(i):.1f}" y="{height-10}" text-anchor="{anchor}">{safe(rows[i]["date"])}</text>')
    parts.append("</svg>")
    return "".join(parts), color


def render_module(data: dict | None = None) -> str:
    if data is None:
        try:
            data = json.loads((ROOT / "data" / "dividend100.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    metrics, advice, verification = data.get("metrics") or {}, data.get("advice") or {}, data.get("verification") or {}
    valuation, policy = data.get("valuation") or {}, data.get("strategy") or {}
    valuation_quality = valuation.get("verification") or {}
    sources = data.get("sources") or {}
    rows = data.get("chart") or []
    chart, color = chart_svg(rows)
    gap = metrics.get("distance_ma250_pct")
    position = "年线上方" if gap is not None and gap > 0 else "年线下方" if gap is not None and gap < 0 else "年线附近" if gap is not None else "位置待更新"
    replacements = {
        "{{DIV_NAME}}": safe(data.get("name") or "中证红利低波动100指数"), "{{DIV_CODE}}": safe(data.get("code") or "930955"),
        "{{DIV_DATE}}": safe(data.get("data_as_of") or "待更新"), "{{DIV_CLOSE}}": number(metrics.get("close")),
        "{{DIV_MA250}}": number(metrics.get("ma250")), "{{DIV_POSITION}}": position,
        "{{DIV_BAND_LOW}}": number(metrics.get("reference_band_low")), "{{DIV_BAND_HIGH}}": number(metrics.get("reference_band_high")),
        "{{DIV_CHART}}": chart, "{{DIV_CHART_COLOR}}": color,
        "{{DIV_CHART_RANGE}}": safe(f"{rows[0]['date']} 至 {rows[-1]['date']}" if rows else "历史待更新"),
        "{{DIV_ADVICE_TITLE}}": safe(advice.get("title") or "等待完整数据"), "{{DIV_ADVICE_REASON}}": safe(advice.get("reason")),
        "{{DIV_ADVICE_ACTION}}": safe(advice.get("action") or "先核对最新收盘数据与基金信息。"),
        "{{DIV_ADVICE_RISK}}": safe(advice.get("risk")), "{{DIV_MANUAL_CHECKS}}": safe(advice.get("manual_checks")),
        "{{DIV_ELIGIBLE}}": "true" if advice.get("eligible") is True else "false",
        "{{DIV_PE}}": number(valuation.get("pe_ttm")), "{{DIV_PE_PERCENTILE}}": number(valuation.get("pe_percentile_5y"), "%"),
        "{{DIV_YIELD}}": number(valuation.get("dividend_yield"), "%"),
        "{{DIV_PE_DATE}}": safe(valuation.get("pe_as_of") or "待更新"), "{{DIV_YIELD_DATE}}": safe(valuation.get("dividend_as_of") or "待更新"),
        "{{DIV_VAL_QUALITY}}": safe(valuation_quality.get("label") or "估值待核验"),
        "{{DIV_VAL_HISTORY}}": safe(valuation.get("history_days") or 0), "{{DIV_VAL_METHOD}}": safe(valuation.get("methodology")),
        "{{DIV_VAL_RISK}}": safe(valuation.get("risk_note")),
        "{{DIV_VAL_URL}}": safe(valuation.get("sources", {}).get("indicator") or "https://www.csindex.com.cn/"),
        "{{DIV_PE_LOW}}": safe(policy.get("pe_low_percentile", 30)), "{{DIV_YIELD_MIN}}": safe(policy.get("min_dividend_yield_pct", 4)),
        "{{DIV_TRANCHE}}": safe(policy.get("max_tranche_budget_pct", 20)), "{{DIV_INTERVAL}}": safe(policy.get("min_days_between_buys", 30)),
        "{{DIV_QUALITY_CLASS}}": safe(verification.get("status") or "pending"), "{{DIV_QUALITY}}": safe(verification.get("label") or "数据待核验"),
        "{{DIV_UPDATED}}": safe(data.get("updated_at")), "{{DIV_HISTORY_SOURCE}}": safe(data.get("history_source") or "待更新"),
        "{{DIV_CLOSE_ERROR}}": number(verification.get("latest_close_difference_pct"), "%"), "{{DIV_MA_ERROR}}": number(verification.get("ma250_difference_pct"), "%"),
        "{{DIV_MATCHED_DAYS}}": safe(verification.get("history_matched_days") or 0), "{{DIV_METHOD}}": safe(data.get("methodology")),
        "{{DIV_RISK_NOTE}}": safe(data.get("risk_note") or "数据不足时暂停建议；指数仍有下跌风险。"),
        "{{DIV_OFFICIAL_URL}}": safe(sources.get("official") or "https://www.csindex.com.cn/"),
        "{{DIV_METHOD_URL}}": safe(sources.get("methodology") or "https://www.csindex.com.cn/"),
        "{{DIV_SECONDARY_URL}}": safe(sources.get("eastmoney") or "https://quote.eastmoney.com/zz/2.930955.html"),
    }
    for tag, key in (("DAILY", "daily_return"), ("DISTANCE", "distance_ma250_pct"), ("SLOPE", "ma250_change_20d_pct"), ("MONTH", "return_1m"), ("YTD", "return_ytd"), ("DRAWDOWN", "max_drawdown_1y")):
        replacements[f"{{{{DIV_{tag}}}}}"] = number(metrics.get(key), "%", signed=True)
        replacements[f"{{{{DIV_{tag}_CLASS}}}}"] = direction(metrics.get(key))
    template = (ROOT / "dividend100.template.html").read_text(encoding="utf-8")
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    if "{{DIV_" in template:
        raise ValueError("红利低波模块存在未替换字段")
    return template
