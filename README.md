# InterestSC Daily Investment Watch

Personal GitHub Pages dashboard for a daily, rules-based review of mainland China public mutual funds, major market indices, and Berkshire Hathaway's public US equity portfolio.

## Pages

- `index.html`: three risk-bucket fund watchlists with return, volatility, drawdown, and consistency scoring
- `market.html`: daily A-share, Hong Kong, and US index performance plus Berkshire's latest public Form 13F holdings
- `market.html#dividend100`: CSI Dividend Low Volatility 100 (930955), MA250, official historical P/E percentile and dividend yield, valuation-first allocation observations, and a manual tranche-budget/cooldown check
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
4. Fetches 930955 price history from Eastmoney and CSI, cross-checks the close and MA250, and collects CSI rolling P/E history and its PE1/DP1 indicator XLS. It generates a valuation-first daily JSON/Markdown report and a GitHub Actions run summary.
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
|   |-- dividend_strategy.py
|   |-- fetch_dividend100.py
|   |-- render_dividend100.py
|   |-- fetch_funds.py
|   |-- fetch_markets.py
|   |-- render_funds.py
|   `-- render_markets.py
|-- dividend100.template.html
|-- tests/test_dividend100.py
|-- tests/test_dividend_allocation.cjs
|-- assets/dividend-allocation.js
|-- config/dividend100_strategy.json
|-- fund.template.html
|-- market.template.html
|-- index.html
|-- market.html
`-- README.md
```

## Manual trigger

Open the repository's Actions tab, choose **Daily Fund & Market Watch Update**, and run the workflow manually.

## Dividend Low Volatility 100 rules

The annual line is the arithmetic mean of the latest 250 completed trading-session closes. Its 20-session change is a risk indicator, **not a purchase veto**. Price verification still requires matching latest dates, at least 245 overlapping recent trading dates, and close/history/MA250 differences no greater than 1%. Data older than seven calendar days is suspended.

Allocation is valuation-first: after price and valuation verification, P/E at or below the **30th historical percentile**, official DP1 dividend yield at least **4%**, and a close at or below MA250 can prompt considering **one tranche**, even with a falling annual line. Falling below MA250 alone does not establish cheapness. Higher P/E ranks, an insufficient yield, or a price above MA250 do not trigger a purchase. The defaults are transparent, unbacktested example parameters in `config/dividend100_strategy.json`, not CSI recommendations or an estimate of fair value.

P/E ranks use the same CSI rolling-P/E history series within the preceding five calendar years, at most 1,250 valid sessions and at least 1,000. The empirical rank counts observations below the current value plus half the equal observations. The page shows actual dates and coverage. CSI's history API calls this field `peg`, but it is documented as rolling P/E, not the PEG growth ratio. DP1 (total-share-capital basis) is kept separate from DP2, and short dividend history is not called a five-year percentile. P/B and forward dividend sustainability are not automatically verified by this module.

CSI price history and its indicator XLS are two channels from **the same organization**, not two independent valuation sources. They are labeled accordingly. Different equal-weight/market-cap-weighted P/E or dividend definitions cannot be mixed. Until a same-date, same-method independent valuation reference is available, official figures are displayed but the allocation suggestion remains **paused**. This is a data gap, not a sell signal.

An authorized independent provider can supply a public HTTPS JSON endpoint in `valuation_reference_url`, or a reviewed local `data/dividend100_valuation_reference.json`. The schema is illustrated by `data/dividend100_valuation_reference.example.json`: code, date, documented basis `CSI_PERF_PE_TTM_AND_DP1`, positive `pe_ttm` and `dividend_yield` (percentage, e.g. 4 means 4%), and the actual independent provider name/source URL. Its methods must genuinely match; setting the basis label alone does not make incompatible data valid. Values are compared with CSI using exact Decimal arithmetic; either difference above 1% suspends the suggestion. Never put API secrets in committed configuration or use the placeholder example as real data.

The manual budget check caps each tranche at **20% of the user's dedicated 930955 budget** and at the remaining budget, with at least **30 calendar days** between purchases. This percentage is not of the user's entire portfolio. Users must enter their actual cumulative spending and last purchase date and confirm long-term funds, risk tolerance, and fund/dividend checks. The page does not know real holdings, place orders, or save/upload those entries. A daily allocation-zone signal is not a daily buy instruction. Budget rules can also be adjusted in the strategy configuration after considering personal circumstances.

The price index excludes dividend reinvestment, and index points are not ETF prices. A historically low P/E does not guarantee future returns; dividends can be reduced.

The module updates with the existing 06:30 Beijing/Hong Kong workflow. `data/dividend100.md` is also shown in each GitHub Actions run summary. Website updates and run summaries do not send external email/WeChat notifications; those require an explicitly configured channel.

Run the rule and budget checks with `python -m unittest discover -s tests -v` and `node tests/test_dividend_allocation.cjs`. The data collector requires `xlrd==2.0.2` to parse CSI's official XLS.

## Methodology and limitations

This dashboard is an educational screening and research tool, not an investment adviser. Historical return, volatility, drawdown, public holdings, and portfolio changes do not predict future performance. Before making a decision, read official product documents and company filings, verify fees and risks, and match any investment to your own risk tolerance and time horizon.
