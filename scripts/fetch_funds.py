"""Fetch, score, and cross-check mainland China public mutual funds.

The output is a non-personalized educational watchlist. It intentionally avoids
buy/sell instructions and ranks funds only against peers in the same risk bucket.
"""

from __future__ import annotations

import bisect
import json
import math
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TIMEZONE = ZoneInfo("Asia/Hong_Kong")

RANKING_URL = "https://fund.eastmoney.com/data/rankhandler.aspx"
HISTORY_URL = "https://api.fund.eastmoney.com/f10/lsjz"
SINA_URL = "https://hq.sinajs.cn/list="

BUCKETS = {
    "stable": {
        "label": "稳健观察",
        "description": "债券型基金为主，强调回撤与波动控制；稳健不等于保本。",
        "categories": [("zq", "债券型")],
        "preselect": 14,
        "chase_threshold": 2.5,
        "spike_threshold": 1.5,
        "drawdown_warning": -8.0,
        "weights": {
            "momentum": 0.15,
            "long_term": 0.20,
            "drawdown": 0.30,
            "volatility": 0.25,
            "consistency": 0.10,
        },
    },
    "balanced": {
        "label": "均衡观察",
        "description": "混合型基金为主，在中期收益和下行风险之间寻找平衡。",
        "categories": [("hh", "混合型")],
        "preselect": 14,
        "chase_threshold": 12.0,
        "spike_threshold": 4.0,
        "drawdown_warning": -20.0,
        "weights": {
            "momentum": 0.25,
            "long_term": 0.20,
            "drawdown": 0.25,
            "volatility": 0.20,
            "consistency": 0.10,
        },
    },
    "growth": {
        "label": "进取观察",
        "description": "股票型与指数型基金为主，潜在波动和本金损失风险更高。",
        "categories": [("gp", "股票型"), ("zs", "指数型")],
        "preselect": 20,
        "chase_threshold": 18.0,
        "spike_threshold": 6.0,
        "drawdown_warning": -30.0,
        "weights": {
            "momentum": 0.35,
            "long_term": 0.20,
            "drawdown": 0.15,
            "volatility": 0.15,
            "consistency": 0.15,
        },
    },
}

EXCLUDED_NAME_PARTS = ("定开", "持有期", "封闭", "养老", "QDII")


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; InterestSC-Fund-Watch/2.0)",
            "Accept": "application/json,text/plain,*/*",
        }
    )
    return session


def to_float(value: object) -> float | None:
    text = str(value or "").strip().replace("%", "")
    if not text or text in {"--", "---"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value: object) -> date | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def annualize_cumulative_return(value: float | None, years: float) -> float | None:
    if value is None or value <= -100 or years <= 0:
        return None
    return (math.pow(1 + value / 100, 1 / years) - 1) * 100


def parse_rank_payload(payload: str, category_code: str, category_label: str) -> list[dict]:
    match = re.search(r"datas:(\[.*?\]),allRecords:", payload, re.DOTALL)
    if not match:
        raise ValueError("Unexpected Eastmoney ranking response")

    raw_rows = json.loads(match.group(1))
    today = datetime.now(TIMEZONE).date()
    funds: list[dict] = []

    for raw_row in raw_rows:
        fields = raw_row.split(",")
        if len(fields) < 17:
            continue

        inception = parse_date(fields[16])
        age_years = (today - inception).days / 365.25 if inception else None
        return_3y = to_float(fields[13])
        funds.append(
            {
                "code": fields[0],
                "name": fields[1],
                "category_code": category_code,
                "category": category_label,
                "nav_date": fields[3],
                "unit_nav": to_float(fields[4]),
                "accumulated_nav": to_float(fields[5]),
                "daily_return": to_float(fields[6]),
                "return_1w": to_float(fields[7]),
                "return_1m": to_float(fields[8]),
                "return_3m": to_float(fields[9]),
                "return_6m": to_float(fields[10]),
                "return_1y": to_float(fields[11]),
                "return_2y": to_float(fields[12]),
                "return_3y": return_3y,
                "return_3y_annualized": annualize_cumulative_return(return_3y, 3),
                "return_ytd": to_float(fields[14]),
                "return_since_inception": to_float(fields[15]),
                "inception_date": fields[16],
                "age_years": round(age_years, 1) if age_years is not None else None,
                "fee": fields[20] if len(fields) > 20 and fields[20] else (fields[19] if len(fields) > 19 else ""),
                "url": f"https://fund.eastmoney.com/{fields[0]}.html",
            }
        )

    return funds


def fetch_ranking(
    session: requests.Session,
    category_code: str,
    category_label: str,
    sort_key: str,
    limit: int = 140,
) -> list[dict]:
    today = datetime.now(TIMEZONE).date()
    params = {
        "op": "ph",
        "dt": "kf",
        "ft": category_code,
        "rs": "",
        "gs": "0",
        "sc": sort_key,
        "st": "desc",
        "sd": (today - timedelta(days=366)).isoformat(),
        "ed": today.isoformat(),
        "qdii": "",
        "tabSubtype": ",,,,,",
        "pi": "1",
        "pn": str(limit),
        "dx": "1",
        "v": str(time.time()),
    }
    response = session.get(
        RANKING_URL,
        params=params,
        headers={"Referer": "https://fund.eastmoney.com/data/fundranking.html"},
        timeout=35,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    return parse_rank_payload(response.text, category_code, category_label)


def normalized_fund_name(name: str) -> str:
    return re.sub(r"(?<=[\u4e00-\u9fff0-9])(?:A|C|E|I)$", "", name.strip(), flags=re.IGNORECASE)


def share_class_preference(fund: dict) -> tuple[int, float]:
    name = fund.get("name", "").upper()
    preference = 3 if name.endswith("A") else (1 if name.endswith(("C", "E", "I")) else 2)
    return preference, float(fund.get("age_years") or 0)


def is_eligible(fund: dict, bucket_id: str) -> bool:
    name = str(fund.get("name") or "")
    if any(part.lower() in name.lower() for part in EXCLUDED_NAME_PARTS):
        return False
    if bucket_id == "stable" and ("可转债" in name or "转债" in name):
        return False
    return bool(
        (fund.get("age_years") or 0) >= 3
        and fund.get("return_1y") is not None
        and fund.get("return_3y") is not None
        and fund.get("return_6m") is not None
    )


def percentile_map(items: list[dict], key: str, higher_is_better: bool = True) -> dict[str, float]:
    values = sorted(float(item[key]) for item in items if item.get(key) is not None)
    if not values:
        return {item["code"]: 50.0 for item in items}

    result: dict[str, float] = {}
    denominator = max(len(values) - 1, 1)
    for item in items:
        value = item.get(key)
        if value is None:
            score = 0.0
        else:
            position = bisect.bisect_right(values, float(value)) - 1
            score = position / denominator * 100
            if not higher_is_better:
                score = 100 - score
        result[item["code"]] = score
    return result


def deduplicate_and_preselect(funds: list[dict], bucket_id: str, limit: int) -> list[dict]:
    by_code = {fund["code"]: fund for fund in funds if is_eligible(fund, bucket_id)}
    by_name: dict[str, dict] = {}
    for fund in by_code.values():
        key = normalized_fund_name(fund["name"])
        current = by_name.get(key)
        if current is None or share_class_preference(fund) > share_class_preference(current):
            by_name[key] = fund

    eligible = list(by_name.values())
    if not eligible:
        return []

    p_6m = percentile_map(eligible, "return_6m")
    p_1y = percentile_map(eligible, "return_1y")
    p_3y = percentile_map(eligible, "return_3y_annualized")

    for fund in eligible:
        periods = [fund.get("return_1m"), fund.get("return_3m"), fund.get("return_6m"), fund.get("return_1y")]
        consistency = sum(value is not None and value > 0 for value in periods) / len(periods) * 100
        fund["pre_score"] = round(
            p_6m[fund["code"]] * 0.25
            + p_1y[fund["code"]] * 0.30
            + p_3y[fund["code"]] * 0.35
            + consistency * 0.10,
            2,
        )

    eligible.sort(key=lambda item: item["pre_score"], reverse=True)
    return eligible[:limit]


def fetch_nav_metrics(session: requests.Session, fund: dict) -> dict | None:
    # The paginated JSON endpoint caps responses at 20 records. The public fund
    # detail payload exposes the same complete NAV trend in one request.
    today = datetime.now(TIMEZONE).date()
    request = urllib.request.Request(
        f"https://fund.eastmoney.com/pingzhongdata/{fund['code']}.js?v={today:%Y%m%d}",
        headers={
            "Referer": f"https://fund.eastmoney.com/{fund['code']}.html",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        payload = response.read().decode("utf-8-sig")

    match = re.search(r"var Data_netWorthTrend = (\[.*?\]);", payload, re.DOTALL)
    if not match:
        return None

    all_records = json.loads(match.group(1))
    cutoff = int(
        datetime.combine(today - timedelta(days=400), datetime.min.time(), tzinfo=TIMEZONE).timestamp()
        * 1000
    )
    records = sorted(
        [record for record in all_records if int(record.get("x") or 0) >= cutoff],
        key=lambda item: int(item.get("x") or 0),
    )
    if not records:
        return None

    daily_returns = [to_float(item.get("equityReturn")) for item in records]
    daily_returns = [value / 100 for value in daily_returns if value is not None and value > -100]
    if len(daily_returns) < 100:
        return None

    curve = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for daily_return in daily_returns:
        curve *= 1 + daily_return
        peak = max(peak, curve)
        max_drawdown = min(max_drawdown, curve / peak - 1)

    annualized_return = (math.pow(curve, 250 / len(daily_returns)) - 1) * 100
    annualized_volatility = statistics.stdev(daily_returns) * math.sqrt(250) * 100
    positive_day_ratio = sum(value > 0 for value in daily_returns) / len(daily_returns) * 100

    latest = records[-1]
    latest_nav = to_float(latest.get("y"))
    latest_date = datetime.fromtimestamp(int(latest["x"]) / 1000, TIMEZONE).date().isoformat()
    internal_difference = None
    if fund.get("unit_nav") is not None and latest_nav not in (None, 0):
        internal_difference = abs(float(fund["unit_nav"]) - latest_nav) / abs(latest_nav) * 100
        if fund.get("nav_date") == latest_date and internal_difference > 1:
            return None

    return {
        "nav_date": latest_date,
        "unit_nav": latest_nav if latest_nav is not None else fund.get("unit_nav"),
        "daily_return": to_float(latest.get("equityReturn")),
        "purchase_status": "申购状态以最新公告为准",
        "redemption_status": "赎回状态以最新公告为准",
        "annualized_return_1y": round(annualized_return, 2),
        "annualized_volatility": round(annualized_volatility, 2),
        "max_drawdown_1y": round(max_drawdown * 100, 2),
        "positive_day_ratio": round(positive_day_ratio, 1),
        "history_observations": len(daily_returns),
        "internal_nav_difference_pct": round(internal_difference, 4) if internal_difference is not None else None,
    }


def score_bucket(funds: list[dict], bucket_id: str) -> list[dict]:
    if not funds:
        return []

    config = BUCKETS[bucket_id]
    p_6m = percentile_map(funds, "return_6m")
    p_1y_calc = percentile_map(funds, "annualized_return_1y")
    p_3y = percentile_map(funds, "return_3y_annualized")
    p_drawdown = percentile_map(funds, "max_drawdown_1y")
    p_volatility = percentile_map(funds, "annualized_volatility", higher_is_better=False)
    p_consistency = percentile_map(funds, "positive_day_ratio")

    for fund in funds:
        code = fund["code"]
        components = {
            "momentum": (p_6m[code] + p_1y_calc[code]) / 2,
            "long_term": p_3y[code],
            "drawdown": p_drawdown[code],
            "volatility": p_volatility[code],
            "consistency": p_consistency[code],
        }
        score = sum(components[key] * weight for key, weight in config["weights"].items())

        monthly_return = float(fund.get("return_1m") or 0)
        if monthly_return > config["chase_threshold"]:
            score -= min(12, (monthly_return - config["chase_threshold"]) * 0.5)

        fund["score"] = round(max(0, min(100, score)), 1)
        fund["score_components"] = {key: round(value, 1) for key, value in components.items()}

    funds.sort(key=lambda item: item["score"], reverse=True)
    return funds


def parse_sina_payload(payload: bytes) -> dict[str, dict]:
    text = payload.decode("gb18030", errors="replace")
    quotes: dict[str, dict] = {}
    for code, body in re.findall(r'hq_str_f_(\d+)="([^"]*)"', text):
        fields = body.split(",")
        if len(fields) < 5 or not fields[0]:
            continue
        quotes[code] = {
            "name": fields[0],
            "unit_nav": to_float(fields[1]),
            "accumulated_nav": to_float(fields[2]),
            "previous_nav": to_float(fields[3]),
            "nav_date": fields[4],
        }
    return quotes


def fetch_sina_quotes(session: requests.Session, codes: list[str]) -> dict[str, dict]:
    if not codes:
        return {}
    symbols = ",".join(f"f_{code}" for code in codes)
    response = session.get(
        f"{SINA_URL}{symbols}",
        headers={"Referer": "https://finance.sina.com.cn", "Accept": "text/plain,*/*"},
        timeout=35,
    )
    response.raise_for_status()
    return parse_sina_payload(response.content)


def decimal_difference_pct(first: object, second: object) -> float | None:
    try:
        left = Decimal(str(first))
        right = Decimal(str(second))
        if right == 0:
            return None
        return float(abs(left - right) / abs(right) * Decimal("100"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def attach_cross_validation(fund: dict, quote: dict | None) -> None:
    if not quote or quote.get("unit_nav") is None:
        fund["verification"] = {
            "status": "unavailable",
            "label": "第二数据源暂不可用",
            "source": "新浪财经",
        }
        return

    if quote.get("nav_date") != fund.get("nav_date"):
        fund["verification"] = {
            "status": "pending",
            "label": "第二数据源待同步",
            "source": "新浪财经",
            "source_date": quote.get("nav_date"),
        }
        return

    difference = decimal_difference_pct(fund.get("unit_nav"), quote.get("unit_nav"))
    status = "verified" if difference is not None and difference <= 1 else "mismatch"
    fund["verification"] = {
        "status": status,
        "label": "双源净值已核验" if status == "verified" else "净值差异待核查",
        "source": "新浪财经",
        "source_date": quote.get("nav_date"),
        "difference_pct": round(difference, 4) if difference is not None else None,
    }


def risk_label(volatility: float | None, max_drawdown: float | None) -> str:
    volatility = float(volatility or 0)
    max_drawdown = abs(float(max_drawdown or 0))
    if volatility < 5 and max_drawdown < 6:
        return "较低历史波动"
    if volatility < 12 and max_drawdown < 15:
        return "中低历史波动"
    if volatility < 24 and max_drawdown < 30:
        return "中等历史波动"
    return "较高历史波动"


def attach_observation(fund: dict, bucket_id: str) -> None:
    config = BUCKETS[bucket_id]
    monthly_return = float(fund.get("return_1m") or 0)
    daily_return = float(fund.get("daily_return") or 0)
    max_drawdown = float(fund.get("max_drawdown_1y") or 0)
    return_3m = float(fund.get("return_3m") or 0)
    return_6m = float(fund.get("return_6m") or 0)

    if monthly_return > config["chase_threshold"] or daily_return > config["spike_threshold"]:
        signal = "避免追高"
        advice = "近期涨幅偏快，历史得分不代表未来表现；更适合等待波动回落后继续观察。"
    elif max_drawdown < config["drawdown_warning"]:
        signal = "高波动观察"
        advice = "历史最大回撤较深，只适合能承受相应本金波动、且投资期限较长的观察者。"
    elif return_3m < 0 and return_6m < 0:
        signal = "等待企稳"
        advice = "中期趋势尚未改善，不宜仅因长期排名靠前而作出仓促决定。"
    else:
        signal = "分批观察"
        advice = "风险调整后表现位于候选前列，可纳入备选并继续核对持仓、基金经理与费用。"

    fund["signal"] = signal
    fund["observation"] = advice
    fund["risk_label"] = risk_label(fund.get("annualized_volatility"), fund.get("max_drawdown_1y"))


def collect_candidates(session: requests.Session, bucket_id: str) -> tuple[list[dict], int]:
    config = BUCKETS[bucket_id]
    ranked_funds: list[dict] = []
    for category_code, category_label in config["categories"]:
        for sort_key in ("1nzf", "3nzf"):
            rows = fetch_ranking(session, category_code, category_label, sort_key)
            ranked_funds.extend(rows)
            time.sleep(0.15)

    unique_count = len({fund["code"] for fund in ranked_funds})
    candidates = deduplicate_and_preselect(ranked_funds, bucket_id, config["preselect"])

    enriched: list[dict] = []
    for fund in candidates:
        try:
            metrics = fetch_nav_metrics(session, fund)
            if metrics:
                fund.update(metrics)
                enriched.append(fund)
        except (requests.RequestException, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            print(f"  {fund['code']} history failed: {error}")
        time.sleep(0.12)

    return score_bucket(enriched, bucket_id), unique_count


def load_history() -> list[dict]:
    path = DATA_DIR / "history.json"
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
        return [item for item in history if isinstance(item, dict) and "scores" in item]
    except (OSError, json.JSONDecodeError):
        return []


def save_output(groups: list[dict], analyzed_count: int) -> None:
    now = datetime.now(TIMEZONE)
    selected = [fund for group in groups for fund in group["funds"]]
    verified_count = sum(fund.get("verification", {}).get("status") == "verified" for fund in selected)
    pending_count = sum(fund.get("verification", {}).get("status") == "pending" for fund in selected)
    chase_count = sum(fund.get("signal") == "避免追高" for fund in selected)
    data_dates = [fund.get("nav_date") for fund in selected if fund.get("nav_date")]
    data_as_of = max(data_dates) if data_dates else now.date().isoformat()

    daily_notes = [
        f"本次从 {analyzed_count} 只基金的排行候选中完成历史数据筛选，最终列出 {len(selected)} 只观察标的。",
        f"{verified_count} 只基金的最新净值已通过东方财富与新浪双源同日校验；{pending_count} 只因第二数据源日期稍晚同步而标记待确认。",
        f"有 {chase_count} 只基金触发短期涨幅偏快提示；高排名不等于适合立即申购，避免频繁申赎和追涨杀跌。",
    ]

    output = {
        "date": now.date().isoformat(),
        "data_as_of": data_as_of,
        "updated_at": now.isoformat(timespec="seconds"),
        "scope": "中国大陆公募开放式基金（非个性化观察清单）",
        "summary": {
            "analyzed_count": analyzed_count,
            "shortlisted_count": len(selected),
            "verified_count": verified_count,
            "pending_count": pending_count,
        },
        "daily_notes": daily_notes,
        "groups": groups,
        "methodology": {
            "minimum_history_years": 3,
            "history_window_days": 400,
            "ranking_window_days": 366,
            "score_note": "收益、三年年化表现、最大回撤、波动率与上涨日占比的同类相对分位；满分100分。",
            "share_class_note": "同一基金不同份额默认优先保留A类或成立更久的份额，实际应按持有期与费率选择。",
            "source_note": "排行和历史净值来自天天基金/东方财富，最新单位净值由新浪财经独立交叉校验。",
        },
        "disclaimer": "本页面仅用于投资者教育和基金初筛，不构成个性化投资建议、收益承诺或交易指令。基金有风险，可能损失本金；请阅读基金合同、招募说明书、产品资料概要和最新公告，并根据自身风险承受能力、投资期限和资产配置独立决策。",
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "funds.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    history = load_history()
    score_summary = {
        group["id"]: round(statistics.mean(fund["score"] for fund in group["funds"]), 1)
        if group["funds"]
        else 0
        for group in groups
    }
    average_1y = round(statistics.mean(fund["return_1y"] for fund in selected), 2) if selected else 0
    record = {
        "date": now.date().isoformat(),
        "data_as_of": data_as_of,
        "shortlisted_count": len(selected),
        "verified_count": verified_count,
        "scores": score_summary,
        "average_return_1y": average_1y,
    }
    history = [item for item in history if item.get("date") != record["date"]]
    history.append(record)
    history = history[-30:]
    (DATA_DIR / "history.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    session = build_session()
    bucket_results: dict[str, list[dict]] = {}
    analyzed_count = 0

    print("Fetching public-fund rankings and historical NAV data...")
    for bucket_id, config in BUCKETS.items():
        print(f"- {config['label']}")
        try:
            scored, unique_count = collect_candidates(session, bucket_id)
        except (requests.RequestException, ValueError) as error:
            print(f"  bucket failed: {error}")
            scored, unique_count = [], 0
        analyzed_count += unique_count
        bucket_results[bucket_id] = scored[:7]
        print(f"  analyzed universe: {unique_count}; scored: {len(scored)}")

    validation_pool = [fund for funds in bucket_results.values() for fund in funds]
    try:
        quotes = fetch_sina_quotes(session, [fund["code"] for fund in validation_pool])
    except requests.RequestException as error:
        print(f"Sina cross-check unavailable: {error}")
        quotes = {}

    groups: list[dict] = []
    for bucket_id, config in BUCKETS.items():
        selected: list[dict] = []
        for fund in bucket_results[bucket_id]:
            attach_cross_validation(fund, quotes.get(fund["code"]))
            if fund["verification"]["status"] == "mismatch":
                print(f"  excluded {fund['code']}: cross-source NAV mismatch")
                continue
            attach_observation(fund, bucket_id)
            selected.append(fund)
            if len(selected) == 5:
                break

        groups.append(
            {
                "id": bucket_id,
                "label": config["label"],
                "description": config["description"],
                "funds": selected,
            }
        )

    save_output(groups, analyzed_count)
    print("Fund data saved.")
    for group in groups:
        print(f"- {group['label']}: {len(group['funds'])} funds")


if __name__ == "__main__":
    main()
