"""Daily CSI Dividend Low Volatility 100 (930955) allocation report.

Keep index points separate from ETF prices. Price-index returns exclude
reinvested dividends; the moving average is a trend measure, not fair value.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

if __package__:
    from .dividend_strategy import build_allocation_advice, build_valuation, load_policy
else:
    from dividend_strategy import build_allocation_advice, build_valuation, load_policy

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "dividend100.json"
REPORT_PATH = ROOT / "data" / "dividend100.md"
TIMEZONE = ZoneInfo("Asia/Hong_Kong")
CODE = "930955"
NAME = "中证红利低波动100指数"
OFFICIAL_URL = "https://www.csindex.com.cn/#/indices/family/detail?indexCode=930955"
METHODOLOGY_URL = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/20231208180204-930955_Index_Methodology_cn.pdf"
EASTMONEY_URL = "https://quote.eastmoney.com/zz/2.930955.html"
D = Decimal


def decode_json(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode('utf-8-sig'))
    except UnicodeDecodeError:
        return json.loads(raw.decode('gb18030'))


def fetch_json(url: str) -> dict:
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.csindex.com.cn/"}
    last_error: Exception | None = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=18) as response:
                return decode_json(response.read())
        except (OSError, ValueError) as error:
            last_error = error
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if curl:
        result = subprocess.run(
            [curl, "-fsSL", "--max-time", "20", "-H", "User-Agent: Mozilla/5.0", "-H", "Referer: https://quote.eastmoney.com/", url],
            capture_output=True, check=True,
        )
        return decode_json(result.stdout)
    raise RuntimeError(f"行情源暂不可用：{last_error}")


def clean_rows(rows: list[dict], now: datetime) -> list[dict]:
    """Discard incomplete current sessions; reject contradictory duplicate days."""
    dates: dict[str, dict] = {}
    for row in rows:
        try:
            day = date.fromisoformat(str(row["date"]))
            close = D(str(row["close"]))
        except (KeyError, ValueError, InvalidOperation):
            continue
        if not close.is_finite() or close <= 0 or day > now.date() or day.weekday() >= 5:
            continue
        if day == now.date() and (now.hour, now.minute) < (15, 10):
            continue
        normalized = {"date": day.isoformat(), "close": str(close)}
        try:
            pe = D(str(row.get("pe_ttm")))
            if pe.is_finite() and pe > 0:
                normalized["pe_ttm"] = str(pe)
        except InvalidOperation:
            pass
        if normalized["date"] in dates and dates[normalized["date"]]["close"] != str(close):
            raise ValueError(f"同一交易日出现不同收盘价：{day}")
        previous = dates.get(normalized["date"], {})
        if previous.get("pe_ttm") and normalized.get("pe_ttm") and previous["pe_ttm"] != normalized["pe_ttm"]:
            raise ValueError(f"同一交易日出现不同滚动PE：{day}")
        dates[normalized["date"]] = normalized
    return [dates[key] for key in sorted(dates)]


def fetch_official(start: str, end: str, now: datetime) -> list[dict]:
    query = urllib.parse.urlencode({"indexCode": CODE, "startDate": start, "endDate": end})
    payload = fetch_json("https://www.csindex.com.cn/csindex-home/perf/index-perf?" + query)
    rows = []
    for row in payload.get("data") or []:
        if str(row.get("indexCode")) != CODE:
            raise ValueError("中证官方返回的指数代码不匹配")
        day = str(row.get("tradeDate") or "")
        if len(day) == 8:
            rows.append({"date": f"{day[:4]}-{day[4:6]}-{day[6:]}", "close": row.get("close"), "pe_ttm": row.get("peg")})
    return clean_rows(rows, now)


def fetch_indicators(start: str, end: str, now: datetime) -> list[dict]:
    import xlrd
    url = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/930955indicator.xls"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        sheet = xlrd.open_workbook(file_contents=response.read()).sheet_by_index(0)
    if sheet.ncols != 10 or "P/E1" not in str(sheet.cell_value(0, 6)) or "D/P1" not in str(sheet.cell_value(0, 8)):
        raise ValueError("中证估值表字段发生变化")
    rows = []
    for i in range(1, sheet.nrows):
        row = sheet.row_values(i)
        if str(row[1]) != CODE:
            raise ValueError("估值表指数代码不匹配")
        day = str(row[0])
        if len(day) != 8:
            continue
        parsed = date.fromisoformat(f"{day[:4]}-{day[4:6]}-{day[6:]}")
        if parsed > now.date() or parsed.weekday() >= 5 or (parsed == now.date() and (now.hour, now.minute) < (15, 10)):
            continue
        rows.append({"date": parsed.isoformat(), "pe_total": row[6], "dividend_yield": row[8]})
    return rows


def valuation_reference(policy: dict) -> dict | None:
    """Only accept an explicitly configured, documented same-basis source."""
    if policy.get("valuation_reference_url"):
        result = fetch_json(policy["valuation_reference_url"])
    else:
        path = ROOT / "data" / "dividend100_valuation_reference.json"
        result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if result is not None and not isinstance(result, dict):
        raise ValueError("估值参照必须为JSON对象")
    return result


def fetch_eastmoney(start: str, end: str, now: datetime) -> list[dict]:
    query = urllib.parse.urlencode({
        "secid": "2.930955", "klt": "101", "fqt": "0", "beg": start, "end": end, "lmt": "1000",
        "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    })
    payload = fetch_json("https://push2his.eastmoney.com/api/qt/stock/kline/get?" + query)
    data = payload.get("data") or {}
    if data.get("code") != CODE or data.get("market") != 2:
        raise ValueError("东方财富返回的指数代码/市场不匹配")
    rows = [{"date": cells[0], "close": cells[2]} for cells in (item.split(",") for item in data.get("klines") or []) if len(cells) >= 3]
    return clean_rows(rows, now)


def as_number(value: Decimal, places: int = 2) -> float:
    return float(value.quantize(D(1).scaleb(-places)))


def difference_pct(first: Decimal, second: Decimal) -> Decimal:
    return abs(first - second) / first * D(100)


def moving_average(rows: list[dict], window: int = 250) -> Decimal:
    if len(rows) < window:
        raise ValueError(f"年线需要至少{window}个交易日，当前仅{len(rows)}个")
    return sum((D(row["close"]) for row in rows[-window:]), D(0)) / D(window)


def verify_sources(primary: list[dict], secondary: list[dict]) -> dict:
    result = {"status": "pending", "label": "第二数据源待核验", "sources": ["东方财富", "中证指数公司"]}
    if not primary or not secondary:
        return result
    if primary[-1]["date"] != secondary[-1]["date"]:
        result["label"] = "两源最新交易日不一致，建议暂停"
        result["primary_date"], result["secondary_date"] = primary[-1]["date"], secondary[-1]["date"]
        return result
    close_error = difference_pct(D(primary[-1]["close"]), D(secondary[-1]["close"]))
    secondary_map = {row["date"]: D(row["close"]) for row in secondary}
    errors = [difference_pct(D(row["close"]), secondary_map[row["date"]]) for row in primary[-250:] if row["date"] in secondary_map]
    result.update({"latest_close_difference_pct": as_number(close_error, 4), "history_matched_days": len(errors)})
    if len(primary) < 250 or len(secondary) < 250:
        result["label"] = "年线历史不足，建议暂停"
        return result
    ma_error = difference_pct(moving_average(primary), moving_average(secondary))
    maximum = max(errors, default=D(100))
    result.update({"ma250_difference_pct": as_number(ma_error, 4), "max_history_difference_pct": as_number(maximum, 4)})
    if close_error > 1 or ma_error > 1 or maximum > 1:
        result.update({"status": "mismatch", "label": "两源差异超过1%，建议暂停"})
    elif len(errors) >= 245:
        result.update({"status": "verified", "label": "收盘价与250日年线已双源核验"})
    else:
        result["label"] = "两源同日历史覆盖不足，建议暂停"
    return result


def build_advice(metrics: dict, verified: bool, fresh: bool, valuation: dict | None = None,
                 policy: dict | None = None) -> dict:
    return build_allocation_advice(metrics, verified, fresh, valuation, policy)


def build_report(rows: list[dict], verification: dict, now: datetime, source: str,
                 valuation: dict | None = None, policy: dict | None = None) -> dict:
    if len(rows) < 270:
        raise ValueError("需要至少270个交易日计算年线及20日斜率")
    closes = [D(row["close"]) for row in rows]
    latest = closes[-1]
    ma250 = moving_average(rows)
    previous_ma = moving_average(rows[:-20])
    peak = closes[-250]
    drawdown = D(0)
    for close in closes[-250:]:
        peak = max(peak, close)
        drawdown = min(drawdown, (close / peak - 1) * 100)
    pre_year = [row for row in rows if row["date"] < f"{rows[-1]['date'][:4]}-01-01"]
    ytd = (latest / D(pre_year[-1]["close"]) - 1) * 100 if pre_year else None
    metrics = {
        "close": as_number(latest), "ma250": as_number(ma250),
        "daily_return": as_number((latest / closes[-2] - 1) * 100),
        "return_1m": as_number((latest / closes[-22] - 1) * 100),
        "return_ytd": as_number(ytd) if ytd is not None else None,
        "distance_ma250_pct": as_number((latest / ma250 - 1) * 100),
        "ma250_change_20d_pct": as_number((ma250 / previous_ma - 1) * 100),
        "max_drawdown_1y": as_number(drawdown),
        "reference_band_low": as_number(ma250 * D("0.97")),
        "reference_band_high": as_number(ma250 * D("1.03")),
    }
    age = (now.date() - date.fromisoformat(rows[-1]["date"])).days
    fresh = 0 <= age <= 7
    chart = []
    rolling = sum(closes[:250], D(0))
    for position in range(249, len(rows)):
        if position > 249:
            rolling += closes[position] - closes[position - 250]
        chart.append({"date": rows[position]["date"], "close": as_number(closes[position]), "ma250": as_number(rolling / D(250))})
    return {
        "code": CODE, "name": NAME, "updated_at": now.isoformat(timespec="seconds"), "data_as_of": rows[-1]["date"],
        "status": "current" if fresh else "stale", "history_days": len(rows), "history_source": source,
        "metrics": metrics, "verification": verification,
        "valuation": valuation or {}, "strategy": policy or load_policy(),
        "advice": build_advice(metrics, verification.get("status") == "verified", fresh, valuation, policy),
        "chart": chart[-250:], "sources": {"official": OFFICIAL_URL, "eastmoney": EASTMONEY_URL, "methodology": METHODOLOGY_URL},
        "methodology": "配置逻辑：行情与估值均核验、PE近5年分位≤预设低位阈值、股息率达到预设下限、点位在250日年线附近或下方，才提示逢低买入一笔。年线下行仅提示风险，不否决买入；每日处于配置区不表示每天加仓。阈值与预算规程是未回测的示例参数，不是官方买卖标准。",
        "risk_note": "本模块使用930955价格指数，涨幅未计入分红再投资；年线不是便宜/昂贵的估值结论，低波动也可能亏损。购买建议只供长期配置参考，需结合自身期限与风险承受能力。",
    }


def markdown_summary(report: dict) -> str:
    metrics, advice = report.get("metrics") or {}, report.get("advice") or {}
    valuation, policy = report.get("valuation") or {}, report.get("strategy") or {}
    def valuation_value(key: str, suffix: str = "") -> str:
        number = valuation.get(key)
        return f"{number:.2f}{suffix}" if number is not None else "待更新"
    def value(key: str, suffix: str = "") -> str:
        number = metrics.get(key)
        return f"{number:,.2f}{suffix}" if number is not None else "待更新"
    return (
        f"## 红利低波100每日观察（{CODE}）\n\n"
        f"数据截至：{report.get('data_as_of') or '待更新'}；生成时间：{report['updated_at']}\n\n"
        f"| 指标 | 数值 |\n|---|---:|\n| 收盘点位 | {value('close')} |\n"
        f"| 日涨跌 | {value('daily_return', '%')} |\n| 年线 MA250 | {value('ma250')} |\n"
        f"| 相对年线 | {value('distance_ma250_pct', '%')} |\n| 年线20日变化 | {value('ma250_change_20d_pct', '%')} |\n\n"
        f"估值截至：PE {valuation.get('pe_as_of') or '待更新'} / 股息率 {valuation.get('dividend_as_of') or '待更新'}。\n\n"
        f"滚动PE：{valuation_value('pe_ttm')}；PE近5年分位：{valuation_value('pe_percentile_5y', '%')}；股息率：{valuation_value('dividend_yield', '%')}。\n\n"
        f"**{advice.get('title', '数据待更新')}**\n\n{advice.get('reason', '')}\n\n{advice.get('action', '')}\n\n"
        f"{advice.get('risk', '')}\n\n行情核验：{(report.get('verification') or {}).get('label', '待核验')}；估值核验：{valuation.get('verification', {}).get('label', '待核验')}。\n\n"
        f"示例参数：PE分位≤{policy.get('pe_low_percentile', 30)}%、股息率≥{policy.get('min_dividend_yield_pct', 4)}%；每笔最多专属预算{policy.get('max_tranche_budget_pct', 20)}%，间隔至少{policy.get('min_days_between_buys', 30)}个自然日。未回测，不是收益保证。\n\n"
        f"[查看每日模块](https://interestsc1119.github.io/market.html#dividend100)\n\n{report.get('risk_note', '')}\n"
    )


def main() -> None:
    now = datetime.now(TIMEZONE)
    policy = load_policy()
    start, end = (now.date() - timedelta(days=2000)).strftime("%Y%m%d"), now.strftime("%Y%m%d")
    collected: dict[str, list[dict]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        tasks = {name: pool.submit(fetcher, start, end, now) for name, fetcher in (("official", fetch_official), ("eastmoney", fetch_eastmoney), ("indicators", fetch_indicators))}
        for name, future in tasks.items():
            try:
                collected[name] = future.result()
                print(f"Dividend100 {name}: {len(collected[name])} daily closes", flush=True)
            except Exception as error:
                print(f"Dividend100 {name} unavailable: {type(error).__name__}", flush=True)
    try:
        reference = valuation_reference(policy)
    except Exception as error:
        reference = None
        print(f"Dividend100 independent valuation reference unavailable: {type(error).__name__}", flush=True)
    try:
        use_eastmoney = len(collected.get("eastmoney") or []) >= 270
        primary = collected.get("eastmoney") if use_eastmoney else collected.get("official") or []
        secondary = collected.get("official") if use_eastmoney else []
        source = "东方财富" if use_eastmoney else "中证指数公司"
        valuation = build_valuation(collected.get("official") or [], collected.get("indicators") or [], reference, now, primary[-1]["date"] if primary else None)
        report = build_report(primary, verify_sources(primary, secondary or []), now, source, valuation, policy)
    except ValueError as error:
        try:
            report = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report = {"code": CODE, "name": NAME, "metrics": {}, "chart": [], "sources": {"official": OFFICIAL_URL, "eastmoney": EASTMONEY_URL, "methodology": METHODOLOGY_URL}}
        report.update({"status": "stale", "updated_at": now.isoformat(timespec="seconds"), "verification": {"status": "stale", "label": "未取得完整新数据，沿用缓存并暂停建议"}})
        report["strategy"] = policy
        report["advice"] = build_advice(report.get("metrics") or {}, False, False, report.get("valuation"), policy)
        print(f"Dividend100 degraded: {error}", flush=True)
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = markdown_summary(report)
    REPORT_PATH.write_text(summary, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(summary)
    print(f"Dividend100 saved: {report.get('data_as_of')} / {report['advice']['title']}", flush=True)


if __name__ == "__main__":
    main()
