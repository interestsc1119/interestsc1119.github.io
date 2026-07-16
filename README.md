# InterestSC Daily Investment Watch

Personal GitHub Pages dashboard for a daily, rules-based review of mainland China public mutual funds, major market indices, and Berkshire Hathaway's public US equity portfolio.

## Pages

- `index.html`: three risk-bucket fund watchlists with return, volatility, drawdown, and consistency scoring
- `market.html`: daily A-share, Hong Kong, and US index performance plus Berkshire's latest public Form 13F holdings
- The former news and trending interface has been removed

## Daily automation

The workflow runs every day at **06:30 Beijing/Hong Kong time**, after the previous US close and after most mainland public-fund NAVs have been published.

GitHub Actions uses UTC:

```yaml
30 22 * * *
```

Each run:

1. Fetches and scores public funds, then cross-checks the latest NAV with Sina Finance.
2. Calculates eight major-index return and risk metrics from Sina/Yahoo history, with Tencent quote cross-checks.
3. Checks for Berkshire Hathaway's latest SEC Form 13F and compares it with the prior quarter.
4. Renders `index.html` and `market.html`, then commits updated JSON and HTML files.

Form 13F is quarterly, can be filed up to 45 days after quarter-end, and covers only specified US-listed securities. The site labels the report and filing dates separately and does not present it as Buffett's personal or real-time trading activity. If SEC access is temporarily unavailable, the collector can use DATAROMA's organized 13F data and labels that fallback on the page.

## Project structure

```text
.
|-- .github/workflows/daily-update.yml
|-- data/
|   |-- funds.json
|   |-- history.json
|   |-- market.json
|   `-- market_history.json
|-- scripts/
|   |-- fetch_funds.py
|   |-- fetch_markets.py
|   |-- render_funds.py
|   `-- render_markets.py
|-- fund.template.html
|-- market.template.html
|-- index.html
|-- market.html
`-- README.md
```

## Manual trigger

Open the repository's Actions tab, choose **Daily Fund & Market Watch Update**, and run the workflow manually.

## Methodology and limitations

This dashboard is an educational screening and research tool, not an investment adviser. Historical return, volatility, drawdown, public holdings, and portfolio changes do not predict future performance. Before making a decision, read official product documents and company filings, verify fees and risks, and match any investment to your own risk tolerance and time horizon.
