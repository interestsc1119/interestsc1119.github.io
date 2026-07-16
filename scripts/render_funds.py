"""Render the static fund-watch dashboard from JSON data."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def inline_json(value) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def number(value: object, digits: int = 1, fallback: str = "--") -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return fallback


def percent(value: object, digits: int = 1, signed: bool = False) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "--"
    prefix = "+" if signed and numeric > 0 else ""
    return f"{prefix}{numeric:.{digits}f}%"


def metric(label: str, value: str, tone: str = "") -> str:
    tone_class = f" {tone}" if tone else ""
    return (
        f'<div class="metric{tone_class}">'
        f'<span>{escape(label)}</span><strong>{escape(value)}</strong>'
        "</div>"
    )


def render_fund_card(fund: dict, rank: int) -> str:
    name = escape(str(fund.get("name") or "未知基金"))
    code = escape(str(fund.get("code") or ""))
    category = escape(str(fund.get("category") or "基金"))
    url = escape(str(fund.get("url") or "#"), quote=True)
    signal = escape(str(fund.get("signal") or "继续观察"))
    observation = escape(str(fund.get("observation") or "暂无观察说明"))
    risk = escape(str(fund.get("risk_label") or "风险待评估"))
    status = escape(str(fund.get("purchase_status") or "状态未知"))
    fee = escape(str(fund.get("fee") or "以销售渠道为准"))
    verification = fund.get("verification") or {}
    verification_status = str(verification.get("status") or "unavailable")
    if verification_status not in {"verified", "pending", "unavailable"}:
        verification_status = "unavailable"
    verification_label = escape(str(verification.get("label") or "数据待核验"))
    score = number(fund.get("score"), 1)

    metrics = "".join(
        [
            metric("近1年", percent(fund.get("return_1y"), 1, True), "positive"),
            metric("三年年化", percent(fund.get("return_3y_annualized"), 1, True), "positive"),
            metric("年化波动", percent(fund.get("annualized_volatility"), 1)),
            metric("近1年最大回撤", percent(fund.get("max_drawdown_1y"), 1), "negative"),
            metric("上涨日占比", percent(fund.get("positive_day_ratio"), 1)),
            metric("最新日涨跌", percent(fund.get("daily_return"), 2, True)),
        ]
    )

    return f"""
    <article class="fund-card">
        <div class="fund-card-top">
            <div class="fund-rank">{rank:02d}</div>
            <div class="fund-identity">
                <div class="fund-kicker">{category} · {code}</div>
                <h3><a href="{url}" target="_blank" rel="noreferrer">{name}</a></h3>
            </div>
            <div class="score" aria-label="同类综合得分 {score}">
                <strong>{score}</strong><span>同类得分</span>
            </div>
        </div>
        <div class="tag-row">
            <span class="tag signal">{signal}</span>
            <span class="tag">{risk}</span>
            <span class="tag verification {verification_status}">{verification_label}</span>
        </div>
        <div class="metrics">{metrics}</div>
        <p class="observation"><strong>观察说明</strong>{observation}</p>
        <div class="fund-footer">
            <span>净值 {number(fund.get('unit_nav'), 4)} · {escape(str(fund.get('nav_date') or '--'))}</span>
            <span>{status} · 参考费率 {fee}</span>
            <a href="{url}" target="_blank" rel="noreferrer">查看基金资料 →</a>
        </div>
    </article>
    """


def render_groups(groups: list[dict]) -> tuple[str, str]:
    tab_parts: list[str] = []
    section_parts: list[str] = []

    for index, group in enumerate(groups):
        group_id = str(group.get("id") or f"group-{index}")
        if group_id not in {"stable", "balanced", "growth"}:
            continue
        active = " active" if not tab_parts else ""
        label = escape(str(group.get("label") or group_id))
        description = escape(str(group.get("description") or ""))
        funds = group.get("funds") or []
        tab_parts.append(
            f'<button class="tab-btn{active}" type="button" data-group="{group_id}">{label}</button>'
        )
        cards = "\n".join(render_fund_card(fund, rank) for rank, fund in enumerate(funds, 1))
        if not cards:
            cards = '<div class="empty-state">今日数据暂不足，未生成此档观察清单。</div>'
        section_parts.append(
            f"""
            <section class="group-section{active}" id="group-{group_id}">
                <div class="group-heading">
                    <div><span class="eyebrow">Risk bucket</span><h2>{label}</h2></div>
                    <p>{description}</p>
                </div>
                <div class="fund-list">{cards}</div>
            </section>
            """
        )

    return "\n".join(tab_parts), "\n".join(section_parts)


def render_notes(notes: list[str]) -> str:
    if not notes:
        return '<li>今日数据尚未生成。</li>'
    return "\n".join(f"<li>{escape(str(note))}</li>" for note in notes)


def render_dashboard() -> None:
    data = read_json(DATA_DIR / "funds.json", {})
    history = read_json(DATA_DIR / "history.json", [])
    summary = data.get("summary") or {}
    methodology = data.get("methodology") or {}
    tabs_html, groups_html = render_groups(data.get("groups") or [])

    recent_history = [item for item in history[-30:] if isinstance(item, dict) and "scores" in item]
    template = (ROOT / "fund.template.html").read_text(encoding="utf-8")
    replacements = {
        "{{TAB_BUTTONS_HTML}}": tabs_html,
        "{{FUND_GROUPS_HTML}}": groups_html,
        "{{DAILY_NOTES_HTML}}": render_notes(data.get("daily_notes") or []),
        "{{UPDATE_DATE}}": escape(str(data.get("date") or "待更新")),
        "{{DATA_AS_OF}}": escape(str(data.get("data_as_of") or "待更新")),
        "{{ANALYZED_COUNT}}": escape(str(summary.get("analyzed_count") or 0)),
        "{{SHORTLISTED_COUNT}}": escape(str(summary.get("shortlisted_count") or 0)),
        "{{VERIFIED_COUNT}}": escape(str(summary.get("verified_count") or 0)),
        "{{SCOPE}}": escape(str(data.get("scope") or "公募基金观察清单")),
        "{{SCORE_NOTE}}": escape(str(methodology.get("score_note") or "")),
        "{{SHARE_CLASS_NOTE}}": escape(str(methodology.get("share_class_note") or "")),
        "{{SOURCE_NOTE}}": escape(str(methodology.get("source_note") or "")),
        "{{DISCLAIMER}}": escape(str(data.get("disclaimer") or "基金有风险，投资需谨慎。")),
        "{{HISTORY_DATA}}": inline_json(recent_history),
    }

    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)

    unresolved = [token for token in ("{{", "}}") if token in template]
    if unresolved:
        raise ValueError("Unresolved template placeholder")

    output = "\n".join(line.rstrip() for line in template.splitlines()) + "\n"
    (ROOT / "index.html").write_text(output, encoding="utf-8")
    print("index.html updated")
    print(f"- analyzed: {summary.get('analyzed_count', 0)}")
    print(f"- shortlisted: {summary.get('shortlisted_count', 0)}")
    print(f"- verified: {summary.get('verified_count', 0)}")


if __name__ == "__main__":
    render_dashboard()
