"""Fetch major-index performance and Berkshire Hathaway's latest public 13F.

Index prices update daily. Form 13F holdings update quarterly and can be filed
up to 45 days after quarter-end, so this module keeps those timelines separate.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import statistics
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TIMEZONE = ZoneInfo("Asia/Hong_Kong")
SEC_CIK = "0001067983"
SEC_UA = "InterestSC market dashboard interestsc1119@users.noreply.github.com"
SEC_BROWSE_URL = "https://www.sec.gov/edgar/browse/?CIK=1067983&owner=exclude&action=getcompany"

INDEXES = [
    {"id": "shanghai", "name": "上证指数", "market": "A股", "provider": "sina", "symbol": "sh000001", "quote": "s_sh000001"},
    {"id": "csi300", "name": "沪深300", "market": "A股", "provider": "sina", "symbol": "sh000300", "quote": "s_sh000300"},
    {"id": "shenzhen", "name": "深证成指", "market": "A股", "provider": "sina", "symbol": "sz399001", "quote": "s_sz399001"},
    {"id": "chinext", "name": "创业板指", "market": "A股", "provider": "sina", "symbol": "sz399006", "quote": "s_sz399006"},
    {"id": "hsi", "name": "恒生指数", "market": "港股", "provider": "yahoo", "symbol": "^HSI", "quote": "hkHSI"},
    {"id": "sp500", "name": "标普500", "market": "美股", "provider": "yahoo", "symbol": "^GSPC", "quote": "usINX"},
    {"id": "nasdaq", "name": "纳斯达克综合", "market": "美股", "provider": "yahoo", "symbol": "^IXIC", "quote": "usIXIC"},
    {"id": "dow", "name": "道琼斯工业", "market": "美股", "provider": "yahoo", "symbol": "^DJI", "quote": "usDJI"},
]

CUSIP_TICKERS = {
    "02005N100": "ALLY", "02079K107": "GOOG", "02079K305": "GOOGL",
    "023135106": "AMZN", "025816109": "AXP", "037833100": "AAPL",
    "060505104": "BAC", "14040H105": "COF", "16119P108": "CHTR",
    "166764100": "CVX", "191216100": "KO", "21036P108": "STZ",
    "23918K108": "DVA", "247361702": "DAL", "500754106": "KHC",
    "501044101": "KR", "526057104": "LEN", "526057302": "LEN.B",
    "546347105": "LPX", "55616P104": "M", "615369105": "MCO",
    "62944T105": "NVR", "650111107": "NYT", "670346105": "NUE",
    "674599105": "OXY", "829933100": "SIRI", "92343E102": "VRSN",
    "H1467J104": "CB",
}

KNOWN_FILINGS = {
    "2026-03-31": {
        "filing_date": "2026-05-15",
        "accession": "0001193125-26-226661",
        "url": "https://www.sec.gov/Archives/edgar/data/1067983/000119312526226661/0001193125-26-226661-index.htm",
    },
    "2025-12-31": {
        "filing_date": "2026-02-17",
        "accession": "0001193125-26-054580",
        "url": "https://www.sec.gov/Archives/edgar/data/1067983/000119312526054580/0001193125-26-054580-index.htm",
    },
}


def fetch_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 40) -> bytes:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_json(url: str, headers: dict[str, str] | None = None) -> dict:
    return json.loads(fetch_bytes(url, headers).decode("utf-8-sig"))


def to_float(value: object) -> float | None:
    text = str(value or "").strip().replace(",", "").replace("%", "").replace("$", "")
    if not text or text in {"--", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def decimal_difference_pct(first: object, second: object) -> float | None:
    try:
        left = Decimal(str(first))
        right = Decimal(str(second))
        if right == 0:
            return None
        return float(abs(left - right) / abs(right) * Decimal("100"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def fetch_sina_history(symbol: str) -> list[dict]:
    params = urllib.parse.urlencode({"symbol": symbol, "scale": "240", "ma": "no", "datalen": "280"})
    url = f"https://quotes.sina.cn/cn/api/openapi.php/CN_MarketDataService.getKLineData?{params}"
    payload = fetch_json(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
    rows = ((payload.get("result") or {}).get("data") or [])
    return [
        {"date": row.get("day", ""), "close": to_float(row.get("close"))}
        for row in rows
        if to_float(row.get("close")) is not None
    ]


def fetch_yahoo_history(symbol: str) -> list[dict]:
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1y&interval=1d&events=history"
    payload = fetch_json(url, {"User-Agent": "Mozilla/5.0"})
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    timestamps = result.get("timestamp") or []
    closes = (((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
    rows = []
    for timestamp, close in zip(timestamps, closes):
        if close is None:
            continue
        day = datetime.fromtimestamp(timestamp, ZoneInfo("UTC")).date().isoformat()
        rows.append({"date": day, "close": float(close)})
    return rows


def fetch_tencent_quotes(symbols: list[str]) -> dict[str, dict]:
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
    text = fetch_bytes(
        url,
        {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
    ).decode("gb18030", errors="replace")
    quotes: dict[str, dict] = {}
    for symbol, body in re.findall(r'v_([^=]+)="([^"]*)"', text):
        fields = body.split("~")
        if len(fields) < 6:
            continue
        quotes[symbol] = {
            "name": fields[1],
            "price": to_float(fields[3]),
            "quote_time": fields[30] if len(fields) > 30 else "",
        }
    return quotes


def trailing_return(rows: list[dict], periods: int) -> float | None:
    if len(rows) <= periods or not rows[-1].get("close") or not rows[-periods - 1].get("close"):
        return None
    return (rows[-1]["close"] / rows[-periods - 1]["close"] - 1) * 100


def build_index_metrics(config: dict, rows: list[dict], quote: dict | None) -> dict:
    rows = sorted(rows, key=lambda item: item["date"])
    if len(rows) < 20:
        raise ValueError(f"Insufficient index history for {config['name']}")
    latest = rows[-1]
    daily_returns = [rows[i]["close"] / rows[i - 1]["close"] - 1 for i in range(1, len(rows))]
    curve = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in daily_returns:
        curve *= 1 + value
        peak = max(peak, curve)
        max_drawdown = min(max_drawdown, curve / peak - 1)

    current_year = latest["date"][:4]
    year_rows = [row for row in rows if row["date"].startswith(current_year)]
    ytd = (latest["close"] / year_rows[0]["close"] - 1) * 100 if year_rows else None
    one_month = trailing_return(rows, 21)
    three_month = trailing_return(rows, 63)
    one_year = trailing_return(rows, min(251, len(rows) - 1))
    annualized_volatility = statistics.stdev(daily_returns) * math.sqrt(250) * 100 if len(daily_returns) > 2 else None

    second_price = (quote or {}).get("price")
    difference = decimal_difference_pct(latest["close"], second_price) if second_price is not None else None
    verification_status = "verified" if difference is not None and difference <= 1 else "pending"
    normalized = [round(row["close"] / rows[-30]["close"] * 100, 2) for row in rows[-30:]]

    if (one_month or 0) > 0 and (three_month or 0) > 0:
        trend = "中期偏强"
    elif (one_month or 0) < 0 and (three_month or 0) < 0:
        trend = "中期偏弱"
    else:
        trend = "区间震荡"

    return {
        "id": config["id"],
        "name": config["name"],
        "market": config["market"],
        "date": latest["date"],
        "close": round(latest["close"], 4),
        "daily_return": round(daily_returns[-1] * 100, 2),
        "return_1m": round(one_month, 2) if one_month is not None else None,
        "return_3m": round(three_month, 2) if three_month is not None else None,
        "return_ytd": round(ytd, 2) if ytd is not None else None,
        "return_1y": round(one_year, 2) if one_year is not None else None,
        "annualized_volatility": round(annualized_volatility, 2) if annualized_volatility is not None else None,
        "max_drawdown_1y": round(max_drawdown * 100, 2),
        "trend": trend,
        "sparkline": normalized,
        "history_source": "新浪财经" if config["provider"] == "sina" else "Yahoo Finance",
        "verification": {
            "status": verification_status,
            "label": "腾讯点位已核验" if verification_status == "verified" else "第二源待核验",
            "source": "腾讯行情",
            "difference_pct": round(difference, 4) if difference is not None else None,
            "quote_time": (quote or {}).get("quote_time", ""),
        },
    }


def child_text(element: ET.Element, name: str) -> str:
    child = element.find(f".//{{*}}{name}")
    return (child.text or "").strip() if child is not None else ""


def parse_13f_xml(content: bytes) -> list[dict]:
    root = ET.fromstring(content)
    aggregated: dict[str, dict] = {}
    for row in root.findall(".//{*}infoTable"):
        if child_text(row, "putCall"):
            continue
        cusip = child_text(row, "cusip").upper()
        if not cusip:
            continue
        try:
            value = Decimal(child_text(row, "value") or "0")
            shares = Decimal(child_text(row, "sshPrnamt") or "0")
        except InvalidOperation:
            continue
        item = aggregated.setdefault(
            cusip,
            {
                "cusip": cusip,
                "ticker": CUSIP_TICKERS.get(cusip, ""),
                "name": child_text(row, "nameOfIssuer"),
                "class": child_text(row, "titleOfClass"),
                "value_decimal": Decimal("0"),
                "shares_decimal": Decimal("0"),
            },
        )
        item["value_decimal"] += value
        item["shares_decimal"] += shares

    total = sum((item["value_decimal"] for item in aggregated.values()), Decimal("0"))
    holdings = []
    for item in aggregated.values():
        weight = item["value_decimal"] / total * Decimal("100") if total else Decimal("0")
        holdings.append(
            {
                "cusip": item["cusip"],
                "ticker": item["ticker"],
                "name": item["name"],
                "class": item["class"],
                "value": int(item["value_decimal"]),
                "shares": int(item["shares_decimal"]),
                "weight": round(float(weight), 2),
            }
        )
    return sorted(holdings, key=lambda item: item["value"], reverse=True)


def recent_13f_filings() -> list[dict]:
    headers = {"User-Agent": SEC_UA, "Accept": "application/json", "Accept-Encoding": "identity"}
    payload = fetch_json(f"https://data.sec.gov/submissions/CIK{SEC_CIK}.json", headers)
    recent = ((payload.get("filings") or {}).get("recent") or {})
    rows = []
    for form, accession, filing_date, report_date in zip(
        recent.get("form", []),
        recent.get("accessionNumber", []),
        recent.get("filingDate", []),
        recent.get("reportDate", []),
    ):
        if form == "13F-HR":
            rows.append(
                {
                    "accession": accession,
                    "filing_date": filing_date,
                    "report_date": report_date,
                    "url": f"https://www.sec.gov/Archives/edgar/data/1067983/{accession.replace('-', '')}/{accession}-index.htm",
                }
            )
    return rows[:2]


def fetch_sec_holding_table(filing: dict) -> list[dict]:
    headers = {"User-Agent": SEC_UA, "Accept": "application/json", "Accept-Encoding": "identity"}
    accession_plain = filing["accession"].replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/1067983/{accession_plain}"
    directory = fetch_json(f"{base}/index.json", headers).get("directory") or {}
    candidates = [
        item for item in directory.get("item", [])
        if str(item.get("name", "")).lower().endswith(".xml")
        and str(item.get("name", "")).lower() != "primary_doc.xml"
    ]
    if not candidates:
        raise ValueError("SEC filing information table XML not found")
    document = max(candidates, key=lambda item: int(item.get("size") or 0))["name"]
    xml = fetch_bytes(f"{base}/{document}", {"User-Agent": SEC_UA, "Accept-Encoding": "identity"})
    return parse_13f_xml(xml)


def build_sec_changes(current: list[dict], previous: list[dict]) -> list[dict]:
    current_map = {item["cusip"]: item for item in current}
    previous_map = {item["cusip"]: item for item in previous}
    changes = []
    for cusip, item in current_map.items():
        old = previous_map.get(cusip)
        if old is None:
            status, change = "new", None
        elif old["shares"]:
            change = (item["shares"] / old["shares"] - 1) * 100
            if abs(change) < 0.5:
                continue
            status = "increased" if change > 0 else "reduced"
        else:
            continue
        changes.append(
            {
                "ticker": item.get("ticker") or item["cusip"],
                "name": item["name"],
                "status": status,
                "change_pct": round(change, 2) if change is not None else None,
                "shares": item["shares"],
                "reference_value": item["value"],
            }
        )
    for cusip, old in previous_map.items():
        if cusip not in current_map:
            changes.append(
                {
                    "ticker": old.get("ticker") or old["cusip"],
                    "name": old["name"],
                    "status": "exited",
                    "change_pct": -100.0,
                    "shares": 0,
                    "reference_value": old["value"],
                }
            )
    return sorted(changes, key=lambda item: item["reference_value"], reverse=True)


class DataromaGridParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_grid = False
        self.in_row = False
        self.in_cell = False
        self.cell_text: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table" and attributes.get("id") == "grid":
            self.in_grid = True
        elif self.in_grid and tag == "tr":
            self.in_row = True
            self.row = []
        elif self.in_row and tag == "td":
            self.in_cell = True
            self.cell_text = []

    def handle_data(self, data: str) -> None:
        if self.in_cell and data.strip():
            self.cell_text.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.in_cell:
            self.row.append(" ".join(self.cell_text))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.row:
                self.rows.append(self.row)
            self.in_row = False
        elif tag == "table" and self.in_grid:
            self.in_grid = False


def fetch_with_curl(url: str) -> str:
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        raise RuntimeError("curl is required for the DATAROMA fallback")
    result = subprocess.run(
        [
            curl, "-fsSL", "--max-time", "45",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
            "-H", "Accept: text/html,application/xhtml+xml",
            url,
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def activity_status(text: str) -> str:
    lowered = text.lower()
    if "buy" in lowered or "new" in lowered:
        return "new"
    if "add" in lowered:
        return "increased"
    if "reduce" in lowered or "trim" in lowered:
        return "reduced"
    if "sell" in lowered:
        return "exited"
    return "unchanged"


def fetch_dataroma_portfolio() -> dict:
    url = "https://www.dataroma.com/m/holdings.php?m=brk"
    html = fetch_with_curl(url)
    period_match = re.search(r"Period:\s*<span>([^<]+)</span>", html)
    date_match = re.search(r"Portfolio date:\s*<span>([^<]+)</span>", html)
    count_match = re.search(r"No\. of stocks:\s*<span>([\d,]+)</span>", html)
    value_match = re.search(r"Portfolio value:\s*<span>\$([\d,]+)</span>", html)
    if not all((period_match, date_match, value_match)):
        raise ValueError("Unexpected DATAROMA portfolio page")

    report_date = datetime.strptime(date_match.group(1), "%d %b %Y").date().isoformat()
    portfolio_value = int(value_match.group(1).replace(",", ""))
    parser = DataromaGridParser()
    parser.feed(html)
    holdings = []
    changes = []
    for cells in parser.rows:
        if len(cells) < 6 or cells[0].lower() == "history":
            continue
        stock_match = re.match(r"([A-Z.]+)\s*-\s*(.+)", cells[1])
        if not stock_match:
            continue
        ticker, name = stock_match.groups()
        weight = to_float(cells[2])
        shares = to_float(cells[4])
        if weight is None or shares is None:
            continue
        activity = cells[3]
        status = activity_status(activity)
        holding = {
            "cusip": "",
            "ticker": ticker,
            "name": name,
            "class": "",
            "value": int(Decimal(str(portfolio_value)) * Decimal(str(weight)) / Decimal("100")),
            "shares": int(shares),
            "weight": round(weight, 2),
            "activity": activity,
        }
        holdings.append(holding)
        if status != "unchanged":
            change_match = re.search(r"([+-]?[\d.]+)%", activity)
            change_pct = to_float(change_match.group(1)) if change_match else None
            if change_pct is not None and status in {"reduced", "exited"}:
                change_pct = -abs(change_pct)
            changes.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "status": status,
                    "change_pct": change_pct,
                    "shares": int(shares),
                    "reference_value": holding["value"],
                }
            )

    known = KNOWN_FILINGS.get(report_date, {})
    return {
        "period": period_match.group(1),
        "report_date": report_date,
        "filing_date": known.get("filing_date", "请查看SEC最新披露"),
        "accession": known.get("accession", ""),
        "filing_url": known.get("url", SEC_BROWSE_URL),
        "portfolio_value": portfolio_value,
        "positions_count": int((count_match.group(1) if count_match else len(holdings)).replace(",", "")),
        "holdings": sorted(holdings, key=lambda item: item["value"], reverse=True),
        "changes": sorted(changes, key=lambda item: item["reference_value"], reverse=True),
        "data_status": "fallback",
        "data_status_label": "SEC直连受限，采用DATAROMA的13F整理数据",
        "source_url": url,
    }


def fetch_berkshire_portfolio() -> dict:
    dataroma = None
    try:
        dataroma = fetch_dataroma_portfolio()
    except (RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"DATAROMA fallback unavailable: {error}")

    try:
        filings = recent_13f_filings()
        if len(filings) < 2:
            raise ValueError("Two SEC 13F filings are required")
        current = fetch_sec_holding_table(filings[0])
        previous = fetch_sec_holding_table(filings[1])
        total = sum(item["value"] for item in current)
        for item in current:
            item["weight"] = round(item["value"] / total * 100, 2) if total else 0

        verified = 0
        checked = 0
        if dataroma:
            secondary = {item["ticker"]: item for item in dataroma["holdings"]}
            for item in current[:15]:
                if item.get("ticker") in secondary:
                    checked += 1
                    difference = decimal_difference_pct(item["shares"], secondary[item["ticker"]]["shares"])
                    if difference is not None and difference <= 1:
                        verified += 1

        return {
            "period": filings[0]["report_date"],
            "report_date": filings[0]["report_date"],
            "filing_date": filings[0]["filing_date"],
            "accession": filings[0]["accession"],
            "filing_url": filings[0]["url"],
            "portfolio_value": total,
            "positions_count": len(current),
            "holdings": current,
            "changes": build_sec_changes(current, previous),
            "previous_report_date": filings[1]["report_date"],
            "data_status": "verified" if checked and checked == verified else "primary",
            "data_status_label": f"SEC官方13F；DATAROMA份额核验 {verified}/{checked}" if checked else "SEC官方13F",
            "source_url": filings[0]["url"],
        }
    except (urllib.error.URLError, ValueError, ET.ParseError, json.JSONDecodeError) as error:
        print(f"SEC fetch unavailable: {error}")
        if dataroma:
            return dataroma
        raise


def enrich_berkshire_strategy(portfolio: dict) -> None:
    holdings = portfolio.get("holdings") or []
    top5 = round(sum(item.get("weight", 0) for item in holdings[:5]), 1)
    top10 = round(sum(item.get("weight", 0) for item in holdings[:10]), 1)
    changes = portfolio.get("changes") or []
    counts = {status: sum(item.get("status") == status for item in changes) for status in ("new", "increased", "reduced", "exited")}
    portfolio["concentration"] = {"top5": top5, "top10": top10}
    portfolio["change_counts"] = counts
    portfolio["strategy_notes"] = [
        f"前五大公开美股持仓占 {top5:.1f}%，前十大占 {top10:.1f}%；这是集中度事实，不是建议照抄。",
        f"本期公开变化信号：新进 {counts['new']}、增持 {counts['increased']}、减持 {counts['reduced']}、退出 {counts['exited']}。",
        "把持仓变化当作研究线索：先理解生意、管理层与长期资本回报，再讨论价格和安全边际。",
        "13F不披露现金、私有企业和多数非美国上市证券，也不能证明每笔交易由巴菲特本人决定。",
    ]


def load_previous_market() -> dict:
    try:
        return json.loads((DATA_DIR / "market.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_market_data(indices: list[dict], berkshire: dict) -> None:
    now = datetime.now(TIMEZONE)
    output = {
        "date": now.date().isoformat(),
        "updated_at": now.isoformat(timespec="seconds"),
        "index_data_as_of": max((item["date"] for item in indices), default=now.date().isoformat()),
        "indices": indices,
        "berkshire": berkshire,
        "methodology": {
            "index_note": "日线计算日涨跌、近1月、近3月、年初至今和近1年表现；最新点位由腾讯行情交叉校验。",
            "holdings_note": "每日检查最新13F，但持仓只在季度披露更新；份额变化以相邻两个报告期比较。",
        },
        "disclaimer": "指数历史表现不代表未来收益。伯克希尔13F是滞后的季度公开快照，不是实时交易、完整资产负债表或个性化投资建议。",
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "market.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    history_path = DATA_DIR / "market_history.json"
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        history = []
    record = {
        "date": now.date().isoformat(),
        "indices": {item["id"]: item["close"] for item in indices},
        "filing_report_date": berkshire.get("report_date", ""),
    }
    history = [item for item in history if item.get("date") != record["date"]]
    history.append(record)
    history_path.write_text(json.dumps(history[-90:], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    quotes = fetch_tencent_quotes([item["quote"] for item in INDEXES])
    previous = load_previous_market()
    previous_indices = {item.get("id"): item for item in previous.get("indices", [])}
    indices = []
    for config in INDEXES:
        try:
            rows = fetch_sina_history(config["symbol"]) if config["provider"] == "sina" else fetch_yahoo_history(config["symbol"])
            indices.append(build_index_metrics(config, rows, quotes.get(config["quote"])))
            print(f"Index updated: {config['name']}")
        except (urllib.error.URLError, ValueError, json.JSONDecodeError) as error:
            stale = previous_indices.get(config["id"])
            if stale:
                stale = dict(stale)
                stale["verification"] = {"status": "stale", "label": "沿用上次数据", "source": "缓存"}
                indices.append(stale)
                print(f"Index fallback: {config['name']} ({error})")
            else:
                print(f"Index unavailable: {config['name']} ({error})")

    berkshire = fetch_berkshire_portfolio()
    enrich_berkshire_strategy(berkshire)
    save_market_data(indices, berkshire)
    print(f"Market data saved: {len(indices)} indices; 13F period {berkshire.get('report_date')}")


if __name__ == "__main__":
    main()
