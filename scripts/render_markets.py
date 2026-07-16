"""Render the daily market and Berkshire 13F dashboard."""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "market.json"
TEMPLATE_PATH = ROOT / "market.template.html"
OUTPUT_PATH = ROOT / "market.html"


def safe(value: object) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def bilingual_name(item: dict) -> str:
    english = safe(item.get("name"))
    chinese = safe(item.get("name_zh"))
    return f"{english} · {chinese}" if chinese else english


def number(value: object, decimals: int = 2) -> str:
    if value is None:
        return "—"
    amount = float(value)
    if abs(amount) >= 10_000:
        return f"{amount:,.0f}"
    return f"{amount:,.{decimals}f}"


def percent(value: object, signed: bool = True) -> str:
    if value is None:
        return "—"
    amount = float(value)
    prefix = "+" if signed and amount > 0 else ""
    return f"{prefix}{amount:.2f}%"


def direction_class(value: object) -> str:
    if value is None:
        return "flat"
    amount = float(value)
    return "up" if amount > 0 else "down" if amount < 0 else "flat"


def money(value: object) -> str:
    if value is None:
        return "—"
    amount = float(value)
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:,.1f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:,.1f}M"
    return f"${amount:,.0f}"


def shares(value: object) -> str:
    if value is None:
        return "—"
    amount = float(value)
    if amount >= 1_000_000_000:
        return f"{amount / 1_000_000_000:,.2f}B"
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:,.2f}M"
    if amount >= 1_000:
        return f"{amount / 1_000:,.1f}K"
    return f"{amount:,.0f}"


def date_label(value: object) -> str:
    text = str(value or "")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y.%m.%d")
    except ValueError:
        return text or "—"


def sparkline_svg(points: list[float], index_name: str) -> str:
    if len(points) < 2:
        return '<span class="spark-empty">暂无趋势</span>'
    width, height, padding = 280, 76, 4
    low, high = min(points), max(points)
    spread = high - low or 1
    coords = []
    for position, value in enumerate(points):
        x = padding + position * (width - padding * 2) / (len(points) - 1)
        y = height - padding - (value - low) * (height - padding * 2) / spread
        coords.append(f"{x:.1f},{y:.1f}")
    tone = "#1e6f54" if points[-1] >= points[0] else "#a6403c"
    polygon = " ".join([f"{padding},{height - padding}", *coords, f"{width - padding},{height - padding}"])
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{safe(index_name)} 近30个交易日走势">'
        f'<defs><linearGradient id="fill-{safe(index_name)}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{tone}" stop-opacity=".20"/>'
        f'<stop offset="1" stop-color="{tone}" stop-opacity="0"/></linearGradient></defs>'
        f'<polygon points="{polygon}" fill="url(#fill-{safe(index_name)})"/>'
        f'<polyline points="{" ".join(coords)}" fill="none" stroke="{tone}" '
        'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    )


def render_index_cards(indices: list[dict]) -> str:
    cards = []
    for item in indices:
        verification = item.get("verification") or {}
        status = str(verification.get("status") or "pending")
        status_class = "verified" if status == "verified" else "stale" if status == "stale" else "pending"
        metrics = [
            ("近1月", item.get("return_1m")),
            ("近3月", item.get("return_3m")),
            ("今年以来", item.get("return_ytd")),
            ("近1年", item.get("return_1y")),
        ]
        metric_html = "".join(
            f'<div><span>{label}</span><strong class="{direction_class(value)}">{percent(value)}</strong></div>'
            for label, value in metrics
        )
        cards.append(
            '<article class="index-card">'
            '<header>'
            f'<div><span class="market-label">{safe(item.get("market"))}</span>'
            f'<h3>{safe(item.get("name"))}</h3></div>'
            f'<span class="trend-pill">{safe(item.get("trend"))}</span>'
            '</header>'
            '<div class="index-quote">'
            f'<strong>{number(item.get("close"))}</strong>'
            f'<span class="{direction_class(item.get("daily_return"))}">{percent(item.get("daily_return"))}</span>'
            '</div>'
            f'{sparkline_svg(item.get("sparkline") or [], str(item.get("id") or "index"))}'
            f'<div class="metric-grid">{metric_html}</div>'
            '<div class="risk-line">'
            f'<span>年化波动 <b>{percent(item.get("annualized_volatility"), signed=False)}</b></span>'
            f'<span>近1年最大回撤 <b>{percent(item.get("max_drawdown_1y"), signed=False)}</b></span>'
            '</div>'
            '<footer>'
            f'<span>{date_label(item.get("date"))} · {safe(item.get("history_source"))}</span>'
            f'<span class="source-status {status_class}">{safe(verification.get("label"))}</span>'
            '</footer>'
            '</article>'
        )
    return "".join(cards) or '<p class="empty">今日指数数据暂不可用。</p>'


def render_holdings(holdings: list[dict]) -> str:
    rows = []
    for rank, item in enumerate(holdings[:15], start=1):
        weight = float(item.get("weight") or 0)
        ticker = item.get("ticker") or item.get("cusip") or "—"
        rows.append(
            '<tr>'
            f'<td class="rank">{rank:02d}</td>'
            '<td><div class="company-cell">'
            f'<strong>{safe(ticker)}</strong><span>{bilingual_name(item)}</span>'
            '</div></td>'
            '<td><div class="weight-cell">'
            f'<strong>{weight:.2f}%</strong><span><i style="width:{min(weight * 2.7, 100):.1f}%"></i></span>'
            '</div></td>'
            f'<td>{shares(item.get("shares"))}</td>'
            f'<td>{money(item.get("value"))}</td>'
            '</tr>'
        )
    return "".join(rows) or '<tr><td colspan="5" class="empty">持仓数据暂不可用。</td></tr>'


CHANGE_LABELS = {
    "new": ("新进", "new"),
    "increased": ("增持", "up"),
    "reduced": ("减持", "down"),
    "exited": ("退出", "exited"),
}


def render_changes(changes: list[dict]) -> str:
    cards = []
    for item in changes[:12]:
        label, css_class = CHANGE_LABELS.get(str(item.get("status")), ("调整", "flat"))
        change = item.get("change_pct")
        detail = percent(change) if change is not None else "首次披露"
        cards.append(
            '<article class="change-card">'
            f'<span class="change-badge {css_class}">{label}</span>'
            f'<strong>{safe(item.get("ticker"))}</strong>'
            f'<p>{bilingual_name(item)}</p>'
            f'<b>{detail}</b>'
            '</article>'
        )
    return "".join(cards) or '<p class="empty">本期没有需要展示的显著持股数量变化。</p>'


def render_notes(notes: list[str]) -> str:
    return "".join(
        f'<li><span>{index:02d}</span><p>{safe(note)}</p></li>'
        for index, note in enumerate(notes, start=1)
    )


def render_change_summary(counts: dict) -> str:
    labels = (("new", "新进"), ("increased", "增持"), ("reduced", "减持"), ("exited", "退出"))
    return "".join(
        f'<span><b>{int(counts.get(key) or 0)}</b>{label}</span>'
        for key, label in labels
    )


def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    indices = data.get("indices") or []
    berkshire = data.get("berkshire") or {}
    holdings = berkshire.get("holdings") or []
    verification_count = sum(
        (item.get("verification") or {}).get("status") == "verified" for item in indices
    )
    data_status = str(berkshire.get("data_status") or "fallback")
    status_class = "verified" if data_status == "verified" else "primary" if data_status == "primary" else "fallback"
    concentration = berkshire.get("concentration") or {}
    methodology = data.get("methodology") or {}

    replacements = {
        "{{UPDATED_AT}}": date_label(data.get("updated_at")),
        "{{DATA_DATE}}": date_label(data.get("index_data_as_of")),
        "{{INDEX_COUNT}}": str(len(indices)),
        "{{INDEX_VERIFIED}}": str(verification_count),
        "{{INDEX_CARDS}}": render_index_cards(indices),
        "{{REPORT_DATE}}": date_label(berkshire.get("report_date")),
        "{{FILING_DATE}}": date_label(berkshire.get("filing_date")),
        "{{POSITIONS_COUNT}}": str(int(berkshire.get("positions_count") or len(holdings))),
        "{{PORTFOLIO_VALUE}}": money(berkshire.get("portfolio_value")),
        "{{DATA_STATUS}}": safe(berkshire.get("data_status_label")),
        "{{DATA_STATUS_CLASS}}": status_class,
        "{{FILING_URL}}": safe(berkshire.get("filing_url") or "https://www.sec.gov/edgar/browse/?CIK=1067983"),
        "{{SOURCE_URL}}": safe(berkshire.get("source_url") or berkshire.get("filing_url") or "https://www.sec.gov/edgar/browse/?CIK=1067983"),
        "{{TOP_HOLDINGS}}": render_holdings(holdings),
        "{{CHANGES}}": render_changes(berkshire.get("changes") or []),
        "{{CHANGE_SUMMARY}}": render_change_summary(berkshire.get("change_counts") or {}),
        "{{STRATEGY_NOTES}}": render_notes(berkshire.get("strategy_notes") or []),
        "{{TOP5}}": percent(concentration.get("top5"), signed=False),
        "{{TOP10}}": percent(concentration.get("top10"), signed=False),
        "{{INDEX_NOTE}}": safe(methodology.get("index_note")),
        "{{HOLDINGS_NOTE}}": safe(methodology.get("holdings_note")),
        "{{DISCLAIMER}}": safe(data.get("disclaimer")),
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)

    unresolved = [part.split("}}", 1)[0] for part in template.split("{{")[1:]]
    if unresolved:
        raise ValueError(f"Unresolved template placeholders: {unresolved}")
    OUTPUT_PATH.write_text(template, encoding="utf-8")
    print(f"Rendered {OUTPUT_PATH.name}: {len(indices)} indices, {len(holdings)} holdings")


if __name__ == "__main__":
    main()
