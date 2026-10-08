"""Daily CSI Dividend Low Volatility 100 (930955) report and MA250.

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
        if not close.is_finite() or close <= 0 or day > now.date():
            continue
        if day == now.date() and (now.hour, now.minute) < (15, 10):
            continue
        normalized = {"date": day.isoformat(), "close": str(close)}
        if normalized["date"] in dates and dates[normalized["date"]]["close"] != str(close):
            raise ValueError(f"同一交易日出现不同收盘价：{day}")
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
            rows.append({"date": f"{day[:4]}-{day[4:6]}-{day[6:]}", "close": row.get("close")})
    return clean_rows(rows, now)


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


def build_advice(metrics: dict, verified: bool, fresh: bool) -> dict:
    gap, slope = metrics.get("distance_ma250_pct"), metrics.get("ma250_change_20d_pct")
    if not verified or not fresh or gap is None or slope is None:
        return {"state": "paused", "title": "数据待核验，暂缓新增买入", "reason": "数据源、日期或历史长度未满足要求，先等待完整收盘数据。", "action": "暂停依据本模块加仓；已持有者按原计划检查基金公告与仓位。"}
    if gap > 8:
        return {"state": "wait", "title": "等待回落，避免追涨", "reason": f"收盘价高于年线 {gap:+.2f}%，超过8%的趋势偏离观察阈值。", "action": "新增资金可先保留，等待更靠近年线再评估；已有定投无需因单日上涨临时加倍。"}
    if gap < -3 and slope < 0:
        return {"state": "weak", "title": "趋势偏弱，观望为主", "reason": f"收盘价低于年线 {abs(gap):.2f}%，且年线近20个交易日向下。", "action": "先观察能否重新站稳年线；长期定投者可按既定小额计划执行，避免一次性大额抄底。"}
    if gap < -3:
        return {"state": "observe", "title": "年线下方，等待企稳", "reason": f"收盘价低于年线 {abs(gap):.2f}%，趋势仍需确认。", "action": "先观察回到年线附近后的表现；准备长期配置的资金可拆分为多期，避免单次押注。"}
    if slope < 0:
        return {"state": "observe", "title": "年线仍下行，谨慎分批", "reason": f"当前年线近20个交易日变化 {slope:+.2f}%，长期趋势尚未转强。", "action": "新增配置以观察为主；若已有长期定投计划，控制单期金额并保留后续资金。"}
    if gap > 5:
        return {"state": "wait", "title": "温和偏离，放慢新增节奏", "reason": f"收盘价高于年线 {gap:+.2f}%，已超出靠近年线的观察区间。", "action": "优先等待回落或按固定小额定投执行，避免追涨后集中加仓。"}
    return {"state": "consider", "title": "可考虑小额分批配置", "reason": f"价格相对年线 {gap:+.2f}%，年线近20个交易日变化 {slope:+.2f}%。", "action": "若计划持有至少3年、能承受股票基金回撤，可将计划投入拆成3—6期；先核实跟踪指数、费率、跟踪误差与ETF溢价。"}


def build_report(rows: list[dict], verification: dict, now: datetime, source: str) -> dict:
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
        "advice": build_advice(metrics, verification.get("status") == "verified", fresh),
        "chart": chart[-250:], "sources": {"official": OFFICIAL_URL, "eastmoney": EASTMONEY_URL, "methodology": METHODOLOGY_URL},
        "methodology": "年线=最近250个交易日（含当日）收盘价的算术平均；年线20日变化用于观察方向。±3%、+5%、+8%为预设趋势观察阈值，并非经回测的收益保证或估值标准。",
        "risk_note": "本模块使用930955价格指数，涨幅未计入分红再投资；年线不是便宜/昂贵的估值结论，低波动也可能亏损。购买建议只供长期配置参考，需结合自身期限与风险承受能力。",
    }


def markdown_summary(report: dict) -> str:
    metrics, advice = report.get("metrics") or {}, report.get("advice") or {}
    def value(key: str, suffix: str = "") -> str:
        number = metrics.get(key)
        return f"{number:,.2f}{suffix}" if number is not None else "待更新"
    return (
        f"## 红利低波100每日观察（{CODE}）\n\n"
        f"数据截至：{report.get('data_as_of') or '待更新'}；生成时间：{report['updated_at']}\n\n"
        f"| 指标 | 数值 |\n|---|---:|\n| 收盘点位 | {value('close')} |\n"
        f"| 日涨跌 | {value('daily_return', '%')} |\n| 年线 MA250 | {value('ma250')} |\n"
        f"| 相对年线 | {value('distance_ma250_pct', '%')} |\n| 年线20日变化 | {value('ma250_change_20d_pct', '%')} |\n\n"
        f"**{advice.get('title', '数据待更新')}**\n\n{advice.get('reason', '')}\n\n{advice.get('action', '')}\n\n"
        f"核验：{(report.get('verification') or {}).get('label', '待核验')}。\n\n"
        f"[查看每日模块](https://interestsc1119.github.io/market.html#dividend100)\n\n{report.get('risk_note', '')}\n"
    )


def main() -> None:
    now = datetime.now(TIMEZONE)
    start, end = (now.date() - timedelta(days=1200)).strftime("%Y%m%d"), now.strftime("%Y%m%d")
    collected: dict[str, list[dict]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        tasks = {name: pool.submit(fetcher, start, end, now) for name, fetcher in (("official", fetch_official), ("eastmoney", fetch_eastmoney))}
        for name, future in tasks.items():
            try:
                collected[name] = future.result()
                print(f"Dividend100 {name}: {len(collected[name])} daily closes", flush=True)
            except Exception as error:
                print(f"Dividend100 {name} unavailable: {type(error).__name__}", flush=True)
    try:
        use_eastmoney = len(collected.get("eastmoney") or []) >= 270
        primary = collected.get("eastmoney") if use_eastmoney else collected.get("official") or []
        secondary = collected.get("official") if use_eastmoney else []
        source = "东方财富" if use_eastmoney else "中证指数公司"
        report = build_report(primary, verify_sources(primary, secondary or []), now, source)
    except ValueError as error:
        try:
            report = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report = {"code": CODE, "name": NAME, "metrics": {}, "chart": [], "sources": {"official": OFFICIAL_URL, "eastmoney": EASTMONEY_URL, "methodology": METHODOLOGY_URL}}
        report.update({"status": "stale", "updated_at": now.isoformat(timespec="seconds"), "verification": {"status": "stale", "label": "未取得完整新数据，沿用缓存并暂停建议"}})
        report["advice"] = build_advice(report.get("metrics") or {}, False, False)
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
