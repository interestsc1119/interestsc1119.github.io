"""Observed CSI DP1 dividend yields, never reconstructed from prices or P/E.

The public indicator XLS has a short rolling history. Persist every observed
session so daily updates can extend, rather than silently reset, that window.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


CODE = "930955"
BASIS = "CSI_DP1_TOTAL_SHARES_PERCENT"
SOURCE = "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/930955indicator.xls"
D = Decimal


def clean_observations(rows: list[dict], now: datetime) -> list[dict]:
    days: dict[str, Decimal] = {}
    for row in rows:
        try:
            day = date.fromisoformat(str(row["date"]))
            value = D(str(row["dividend_yield"]))
        except (KeyError, ValueError, InvalidOperation, TypeError):
            continue
        if not value.is_finite() or not 0 < value <= 100:
            continue
        if day > now.date() or day.weekday() >= 5:
            continue
        if day == now.date() and (now.hour, now.minute) < (15, 10):
            continue
        key = day.isoformat()
        if key in days and days[key] != value:
            raise ValueError(f"官方股息率同日数据冲突：{key}")
        days[key] = value
    return [{"date": day, "dividend_yield": str(days[day])} for day in sorted(days)]


def update_archive(path: Path, incoming: list[dict], now: datetime) -> list[dict]:
    """Validate identity; new official observations may revise older observations.

    A corrupt or wrong-basis archive is never silently overwritten. A duplicate
    conflict within one delivery is rejected; a revision across deliveries is
    retained in the audit log and replaces that date, not a second sample.
    """
    archive: dict = {}
    if path.exists():
        archive = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(archive, dict) or archive.get("schema_version") != 1 or archive.get("code") != CODE or archive.get("basis") != BASIS or archive.get("source") != SOURCE or archive.get("unit") != "percent":
            raise ValueError("股息率历史档案的指数、来源或口径不匹配")
        if not isinstance(archive.get("observations"), list):
            raise ValueError("股息率历史档案记录格式错误")
    saved = clean_observations(archive.get("observations") or [], now)
    if len(saved) != len(archive.get("observations") or []):
        raise ValueError("股息率历史档案含无效或重复记录，请人工检查")
    new = clean_observations(incoming, now)
    merged = {row["date"]: row for row in saved}
    revisions = list(archive.get("revisions") or [])
    for row in new:
        old = merged.get(row["date"])
        if old and D(old["dividend_yield"]) != D(row["dividend_yield"]):
            revisions.append({"date": row["date"], "old": old["dividend_yield"], "new": row["dividend_yield"], "observed_at": now.isoformat(timespec="seconds")})
        merged[row["date"]] = row
    observations = [merged[day] for day in sorted(merged)]
    if not new:
        return observations
    result = {"schema_version": 1, "code": CODE, "basis": BASIS, "source": SOURCE,
              "unit": "percent", "updated_at": now.isoformat(timespec="seconds"),
              "observations": observations, "revisions": revisions}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return observations


def build_yield_percentile(rows: list[dict], current: object, current_date: str | None,
                           close_date: str | None, now: datetime) -> dict:
    result = {
        "status": "insufficient", "percentile": None, "percentile_5y": None,
        "sample_days": 0, "start": None, "end": None, "as_of": current_date,
        "label": "股息率历史不足", "basis": BASIS, "source": SOURCE,
        "minimum_sample_days": 20,
        "methodology": "使用同一官方DP1口径，以（低于当前股息率的样本数＋相等样本数的一半）÷样本数×100计算经验分位，含当前交易日。统计窗口限近5年、最多1250个已采集交易日。",
        "note": "分位越高，当前股息率相对样本越高，与PE低分位方向相反；短样本不代表长期估值，不是收益承诺，也不参与现有买入条件。",
    }
    if not current_date or not close_date:
        return result
    end = date.fromisoformat(current_date)
    try:
        start = end.replace(year=end.year - 5)
    except ValueError:
        start = end.replace(year=end.year - 5, day=28)
    samples = [row for row in clean_observations(rows, now) if start.isoformat() <= row["date"] <= current_date][-1250:]
    if samples:
        result.update({"sample_days": len(samples), "start": samples[0]["date"], "end": samples[-1]["date"]})
    try:
        value = D(str(current))
        valid = value.is_finite() and 0 < value <= 100
    except (ValueError, InvalidOperation):
        valid = False
    if current_date != close_date or not valid or not samples or samples[-1]["date"] != current_date:
        result.update({"status": "missing_current", "label": "股息率当前值或统计日期不完整"})
        return result
    if not 0 <= (now.date() - end).days <= 7:
        result.update({"status": "stale", "label": "股息率数据已过期"})
        return result
    if D(samples[-1]["dividend_yield"]) != value:
        result.update({"status": "mismatch", "label": "历史档案与当前DP1不一致"})
        return result
    if len(samples) < 20:
        result["label"] = f"仅{len(samples)}个交易日，至少需20日"
        return result
    values = [D(row["dividend_yield"]) for row in samples]
    less, equal = sum(item < value for item in values), sum(item == value for item in values)
    rank = float(((D(less) + D(equal) / 2) / D(len(values)) * 100).quantize(D("0.01")))
    long_window = len(samples) >= 1000 and (end - date.fromisoformat(samples[0]["date"])).days >= 1460
    result.update({"status": "five_year_window" if long_window else "recent_sample",
                   "percentile": rank, "percentile_5y": rank if long_window else None,
                   "label": f"近5年窗口 · {len(samples)}个已采集交易日" if long_window else f"已采集样本 · {len(samples)}个交易日（非5年分位）"})
    return result
