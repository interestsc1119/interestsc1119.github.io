"""
Render index.html from the static template and the latest JSON data.
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def read_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def inline_json(value) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def is_numeric_text(value: object) -> bool:
    return bool(re.fullmatch(r"[\d,]+", str(value or "").strip()))


def render_ai_projects(projects: list[dict]) -> str:
    if not projects:
        return '<div class="empty-state">今天还没有抓取到 AI 项目。</div>'

    html_parts: list[str] = []
    for index, project in enumerate(projects[:20], 1):
        full_name = escape(project.get("full_name") or project.get("name") or "Unknown project")
        description = escape(project.get("description") or "暂无描述")
        url = escape(project.get("url") or "#", quote=True)
        stars = escape(str(project.get("stars") or "0"))
        trend_value = str(project.get("stars_today") or "").strip()
        has_today_boost = is_numeric_text(trend_value)

        trend_pill = ""
        if has_today_boost:
            trend_pill = f'<span class="pill today">今日 +{escape(trend_value)}</span>'
        elif trend_value:
            trend_pill = f'<span class="pill">{escape(trend_value)}</span>'

        html_parts.append(
            f"""
            <article class="project-card" data-boost="{str(has_today_boost).lower()}">
                <div class="project-header">
                    <span class="rank">{index}</span>
                    <h3 class="project-name">
                        <a href="{url}" target="_blank" rel="noreferrer">{full_name}</a>
                    </h3>
                </div>
                <p class="project-desc">{description}</p>
                <div class="project-stats">
                    <span class="pill">Stars {stars}</span>
                    {trend_pill}
                    <a href="{url}" class="view-btn" target="_blank" rel="noreferrer">查看</a>
                </div>
            </article>
            """
        )

    return "\n".join(html_parts)


def render_news(news_items: list[dict]) -> str:
    if not news_items:
        return '<div class="empty-state">今天还没有抓取到科技新闻。</div>'

    html_parts: list[str] = []
    for index, item in enumerate(news_items[:20], 1):
        title = escape(item.get("title") or "Untitled")
        url = escape(item.get("url") or "#", quote=True)
        source = escape(item.get("source") or "Unknown source")
        hot_value = escape(str(item.get("hot_value") or ""))
        is_hot = bool(item.get("is_hot"))
        hot_pill = '<span class="pill today">Hot</span>' if is_hot else ""
        score_pill = f'<span class="pill">{hot_value} pts</span>' if hot_value else ""

        html_parts.append(
            f"""
            <article class="news-item" data-hot="{str(is_hot).lower()}">
                <span class="news-rank">{index}</span>
                <div class="news-content">
                    <h3 class="news-title">
                        <a href="{url}" target="_blank" rel="noreferrer">{title}</a>
                    </h3>
                    <div class="news-meta">
                        <span>{source}</span>
                        {hot_pill}
                        {score_pill}
                    </div>
                </div>
            </article>
            """
        )

    return "\n".join(html_parts)


def update_html() -> None:
    daily_data = read_json(DATA_DIR / "daily.json", {"date": "", "count": 0, "projects": []})
    news_data = read_json(DATA_DIR / "news.json", {"count": 0, "news": []})
    history = read_json(DATA_DIR / "history.json", [])

    ai_history_data = {
        "labels": [item.get("date", "") for item in history[-14:]],
        "values": [item.get("ai_count", 0) for item in history[-14:]],
    }
    news_history_data = {
        "labels": [item.get("date", "") for item in history[-14:]],
        "values": [item.get("news_count", 0) for item in history[-14:]],
    }
    recent_history = history[-7:] if len(history) >= 7 else history

    html_content = (ROOT / "index.template.html").read_text(encoding="utf-8")
    replacements = {
        "{{AI_PROJECTS_HTML}}": render_ai_projects(daily_data.get("projects", [])),
        "{{NEWS_HTML}}": render_news(news_data.get("news", [])),
        "{{UPDATE_DATE}}": escape(str(daily_data.get("date") or "待更新")),
        "{{AI_COUNT}}": escape(str(daily_data.get("count") or 0)),
        "{{NEWS_COUNT}}": escape(str(news_data.get("count") or 0)),
        "{{AI_HISTORY_DATA}}": inline_json(ai_history_data),
        "{{NEWS_HISTORY_DATA}}": inline_json(news_history_data),
        "{{RECENT_HISTORY}}": inline_json(recent_history),
    }

    for placeholder, value in replacements.items():
        html_content = html_content.replace(placeholder, value)

    html_content = "\n".join(line.rstrip() for line in html_content.splitlines()) + "\n"
    (ROOT / "index.html").write_text(html_content, encoding="utf-8")

    print("index.html updated")
    print(f"   - AI projects: {daily_data.get('count', 0)}")
    print(f"   - Tech news: {news_data.get('count', 0)}")


if __name__ == "__main__":
    update_html()
