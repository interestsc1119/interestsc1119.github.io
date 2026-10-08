# InterestSC Daily Investment Watch

Personal GitHub Pages dashboard for a daily, rules-based review of mainland China public mutual funds, major market indices, and Berkshire Hathaway's public US equity portfolio.

## Pages

- `index.html`: three risk-bucket fund watchlists with return, volatility, drawdown, and consistency scoring
- `market.html`: daily A-share, Hong Kong, and US index performance plus Berkshire's latest public Form 13F holdings
- `market.html#dividend100`: CSI Dividend Low Volatility 100 (930955), MA250, distance to the annual line, a price/MA250 chart, and daily conditional purchase observations
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
4. Fetches 930955 history from Eastmoney and CSI, cross-checks the close and MA250, then generates a daily JSON/Markdown report and a GitHub Actions run summary.
5. Renders `index.html` and `market.html`, then commits updated data and HTML files. The render/publish steps can use cached fund/market data when another collector fails, so the dedicated index report can still update.

Form 13F is quarterly, can be filed up to 45 days after quarter-end, and covers only specified US-listed securities. The site labels the report and filing dates separately and does not present it as Buffett's personal or real-time trading activity. If SEC access is temporarily unavailable, the collector can use DATAROMA's organized 13F data and labels that fallback on the page.

## Project structure

```text
.
|-- .github/workflows/daily-update.yml
|-- data/
|   |-- dividend100.json
|   |-- dividend100.md
|   |-- funds.json
|   |-- history.json
|   |-- market.json
|   `-- market_history.json
|-- scripts/
|   |-- fetch_dividend100.py
|   |-- render_dividend100.py
|   |-- fetch_funds.py
|   |-- fetch_markets.py
|   |-- render_funds.py
|   `-- render_markets.py
|-- dividend100.template.html
|-- tests/test_dividend100.py
|-- fund.template.html
|-- market.template.html
|-- index.html
|-- market.html
`-- README.md
```

## Manual trigger

Open the repository's Actions tab, choose **Daily Fund & Market Watch Update**, and run the workflow manually.

## Dividend Low Volatility 100 rules

The annual line is the arithmetic mean of the latest 250 completed trading-session closes. The module also displays its 20-session change. Advice is suspended when data is stale, the annual history is incomplete, dates disagree, or cross-source differences exceed 1%. Recent history must match on at least 245 of the latest 250 trading dates.

Trend observations use explicit heuristic thresholds: within -3% to +5% of MA250 with a non-falling annual line can prompt small staged purchases for long-term investors; a gap above +8% prompts waiting; prices below -3% with a falling annual line prompt caution. These are trend rules, not fair-value estimates or backtested return guarantees. The price index excludes dividend reinvestment, and index points are not ETF prices.

The module updates with the existing 06:30 Beijing/Hong Kong workflow. `data/dividend100.md` is also shown in each GitHub Actions run summary. Website updates and run summaries do not send external email/WeChat notifications; those require an explicitly configured channel.

## Methodology and limitations

This dashboard is an educational screening and research tool, not an investment adviser. Historical return, volatility, drawdown, public holdings, and portfolio changes do not predict future performance. Before making a decision, read official product documents and company filings, verify fees and risks, and match any investment to your own risk tolerance and time horizon.
