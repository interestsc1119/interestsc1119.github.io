# InterestSC AI Daily Radar

Personal GitHub Pages homepage for InterestSC, with an automated daily digest of trending AI/ML projects and top tech news.

## Features

- Personal-homepage layout for `interestsc1119.github.io`
- AI project radar from GitHub Trending
- Tech news digest from Hacker News and RSS sources
- 14-day trend charts and recent history
- Daily automation via GitHub Actions

## Live Site

https://interestsc1119.github.io

## Automation

The workflow runs every day at **08:57 Beijing time**.

GitHub Actions schedules use UTC, so the cron expression is:

```yaml
57 0 * * *
```

## Architecture

```text
GitHub Actions
  |
  |-- scripts/fetch_trending.py
  |     |-- GitHub Trending
  |     |-- Hacker News API
  |     |-- TechCrunch / Ars Technica / The Verge RSS
  |
  |-- scripts/update_html.py
  |     |-- injects JSON data into index.template.html
  |
  |-- git-auto-commit-action
  |
  v
GitHub Pages serves index.html
```

## Project Structure

```text
.
|-- .github/workflows/daily-update.yml
|-- data/
|   |-- all.json
|   |-- daily.json
|   |-- history.json
|   `-- news.json
|-- scripts/
|   |-- fetch_trending.py
|   `-- update_html.py
|-- index.template.html
|-- index.html
`-- README.md
```

## Manual Trigger

Open the repository's Actions tab, choose **Daily AI & News Update**, and run the workflow manually.
