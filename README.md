# AI Daily Trending

Automated daily digest of trending AI/ML projects on GitHub and top tech news from authoritative sources.

## Features

- **AI Projects** — Scans GitHub Trending for AI/ML/DL related repositories every day
- **Tech News** — Aggregates headlines from Hacker News, TechCrunch, Ars Technica, and The Verge
- **Trend Charts** — 14-day visualization of project and news volume trends
- **History** — Tracks daily data for the past 30 days
- **Zero-cost Automation** — Runs daily via GitHub Actions, hosted on GitHub Pages

## Live Site

**https://interestsc1119.github.io**

## Architecture

```
GitHub Actions (cron)
  |
  |-- fetch_trending.py
  |     |-- GitHub Trending (HTML scraping)
  |     |-- Hacker News (official Firebase API)
  |     |-- TechCrunch / Ars Technica / The Verge (RSS feeds)
  |
  |-- update_html.py  (inject data into HTML template)
  |
  |-- git-auto-commit-action (commit & push)
  |
  v
GitHub Pages serves index.html
```

| Component | Technology |
|-----------|-----------|
| Data sources | GitHub Trending, Hacker News API, RSS feeds |
| Automation | GitHub Actions (cron: daily 06:01 UTC / 14:01 CST) |
| Hosting | GitHub Pages |
| Language | Python, HTML/CSS/JS |

## Project Structure

```
.
├── .github/workflows/
│   └── daily-update.yml      # GitHub Actions workflow
├── scripts/
│   ├── fetch_trending.py     # Scrape GitHub Trending & fetch news
│   └── update_html.py        # Inject data into HTML template
├── data/
│   ├── daily.json            # Today's AI projects
│   ├── all.json              # All trending projects
│   ├── news.json             # Today's tech news
│   └── history.json          # 30-day history
├── index.template.html       # HTML template with placeholders
├── index.html                # Generated page (auto-updated)
└── README.md
```

## Manual Trigger

1. Go to the **Actions** tab of this repository
2. Select **Daily AI & News Update**
3. Click **Run workflow**

## License

MIT
