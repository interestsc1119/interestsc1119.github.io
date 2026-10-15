import unittest
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.fetch_dividend100 import build_advice, build_report, clean_rows, main, moving_average, official_price_status
from scripts.render_dividend100 import render_module
from scripts.dividend_strategy import build_valuation, historical_percentile


NOW = datetime(2026, 10, 8, 18, tzinfo=ZoneInfo("Asia/Hong_Kong"))


def history(count=550):
    days, cursor = [], NOW.date()
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return [{"date": day.isoformat(), "close": str(1000 + i)} for i, day in enumerate(reversed(days))]


def low_valuation():
    return {"pe_ttm": 8, "pe_percentile_5y": 20, "dividend_yield": 5,
            "verification": {"status": "official_single", "label": "测试官方单源"}}


def valuation_inputs():
    rows = [{**row, "pe_ttm": "8"} for row in history(1400)]
    day = rows[-1]["date"]
    indicators = [{"date": day, "pe_total": 8, "dividend_yield": 5}]
    return rows, indicators


class Dividend100Tests(unittest.TestCase):
    def test_annual_line_uses_last_250_closes(self):
        rows = history()
        expected = sum((Decimal(row["close"]) for row in rows[-250:]), Decimal(0)) / Decimal(250)
        self.assertEqual(moving_average(rows), expected)
        self.assertEqual(moving_average(rows), Decimal("1424.5"))

    def test_short_history_rejects_annual_line(self):
        with self.assertRaises(ValueError):
            moving_average(history(249))

    def test_exclude_open_session_and_duplicate_dates(self):
        open_now = NOW.replace(hour=10)
        rows = history(2)
        self.assertEqual(len(clean_rows(rows + rows, open_now)), 1)
        self.assertEqual(len(clean_rows(rows + rows, NOW)), 2)

    def test_conflicting_duplicate_is_rejected(self):
        row = history(1)[0]
        with self.assertRaises(ValueError):
            clean_rows([row, {**row, "close": "9999"}], NOW)

    def test_conflicting_pe_and_weekend_rows_are_rejected(self):
        row = history(1)[0]
        with self.assertRaises(ValueError):
            clean_rows([{**row, "pe_ttm": "8"}, {**row, "pe_ttm": "9"}], NOW)
        weekend = {"date": "2026-10-04", "close": "1000"}
        self.assertEqual(clean_rows([weekend], NOW), [])

    def test_official_source_checks_history_length(self):
        rows = history()
        quality = official_price_status(rows, NOW)
        self.assertEqual(quality["status"], "official_single")
        self.assertEqual(quality["sources"], ["中证指数公司"])
        self.assertEqual(official_price_status(history(269), NOW)["status"], "pending")

    def test_old_or_future_price_dates_pause(self):
        rows = history()
        self.assertEqual(official_price_status(rows, NOW + timedelta(days=8))["status"], "pending")
        self.assertEqual(official_price_status(rows, NOW - timedelta(days=1))["status"], "pending")

    def test_advice_never_buy_when_stale_or_unverified(self):
        metrics = {"distance_ma250_pct": 1, "ma250_change_20d_pct": 1}
        self.assertEqual(build_advice(metrics, False, True)["state"], "paused")
        self.assertEqual(build_advice(metrics, True, False)["state"], "paused")

    def test_advice_branches(self):
        self.assertEqual(build_advice({"distance_ma250_pct": -1}, True, True, low_valuation())["state"], "consider")
        self.assertEqual(build_advice({"distance_ma250_pct": 9}, True, True, low_valuation())["state"], "wait")

    def test_falling_annual_line_does_not_block_low_valuation(self):
        advice = build_advice({"distance_ma250_pct": -12, "ma250_change_20d_pct": -3}, True, True, low_valuation())
        self.assertTrue(advice["eligible"])
        self.assertEqual(advice["max_tranche_budget_pct"], 20)
        self.assertIn("不因跌幅扩大而自动加倍", advice["risk"])

    def test_below_annual_line_alone_is_not_cheap(self):
        valuation = {**low_valuation(), "pe_percentile_5y": 60}
        advice = build_advice({"distance_ma250_pct": -10}, True, True, valuation)
        self.assertEqual(advice["state"], "observe")
        self.assertFalse(advice["eligible"])

    def test_missing_or_unverified_valuation_blocks_allocation(self):
        metrics = {"distance_ma250_pct": -5}
        self.assertEqual(build_advice(metrics, True, True)["state"], "paused")
        valuation = {**low_valuation(), "verification": {"status": "pending"}}
        self.assertEqual(build_advice(metrics, True, True, valuation)["state"], "paused")
        self.assertFalse(build_advice(metrics, False, True, low_valuation())["eligible"])

    def test_dividend_floor_and_low_percentile_boundaries(self):
        metrics = {"distance_ma250_pct": 0, "ma250_change_20d_pct": -1}
        valuation = {**low_valuation(), "pe_percentile_5y": 30, "dividend_yield": 4}
        self.assertTrue(build_advice(metrics, True, True, valuation)["eligible"])
        self.assertFalse(build_advice(metrics, True, True, {**valuation, "dividend_yield": 3.99})["eligible"])
        self.assertFalse(build_advice(metrics, True, True, {**valuation, "pe_percentile_5y": 30.01})["eligible"])
        self.assertFalse(build_advice({**metrics, "distance_ma250_pct": .01}, True, True, valuation)["eligible"])

    def test_percentile_is_exact_midrank_and_rejects_short_history(self):
        self.assertEqual(historical_percentile(Decimal(8), [Decimal(8)] * 1000), Decimal(50))
        self.assertEqual(historical_percentile(Decimal(8), [Decimal(7)] * 200 + [Decimal(9)] * 800), Decimal(20))
        with self.assertRaises(ValueError):
            historical_percentile(Decimal(8), [Decimal(8)] * 999)

    def test_official_valuation_is_ready_without_a_second_source(self):
        rows, indicators = valuation_inputs()
        valuation = build_valuation(rows, indicators, NOW, rows[-1]["date"])
        self.assertEqual(valuation["verification"]["status"], "official_single")
        self.assertEqual(valuation["pe_percentile_5y"], 50)
        self.assertGreaterEqual(valuation["history_days"], 1000)
        self.assertLessEqual(valuation["history_days"], 1250)
        self.assertIn("未独立核验", valuation["verification"]["label"])
        self.assertNotIn("reference", valuation["sources"])

    def test_valuation_invalid_or_missing_dividend_still_pauses(self):
        rows, indicators = valuation_inputs()
        for value in (None, 0, -1, "NaN", "Infinity"):
            bad = [{**indicators[0], "dividend_yield": value}]
            self.assertEqual(build_valuation(rows, bad, NOW, rows[-1]["date"])["verification"]["status"], "pending")
        self.assertEqual(build_valuation(rows, indicators, NOW + timedelta(days=8), rows[-1]["date"])["verification"]["status"], "pending")

    def test_valuation_missing_history_or_same_date_yield_pauses(self):
        rows, indicators = valuation_inputs()
        self.assertEqual(build_valuation(rows[-999:], indicators, NOW, rows[-1]["date"])["verification"]["status"], "pending")
        indicators[0]["date"] = "2026-10-07"
        self.assertEqual(build_valuation(rows, indicators, NOW, rows[-1]["date"])["verification"]["status"], "pending")

    def test_daily_conditions_and_source_are_explicit(self):
        advice = build_advice({"distance_ma250_pct": -5}, True, True, low_valuation())
        self.assertEqual([item["met"] for item in advice["conditions"]], [True, True, True])
        self.assertIn("未做独立来源核验", advice["source_note"])
        missing = build_advice({}, True, True)
        self.assertEqual([item["met"] for item in missing["conditions"]], [None, None, None])

    def test_single_source_data_reaches_both_wait_and_buy_paths(self):
        rows, indicators = valuation_inputs()
        rows[-1]["pe_ttm"] = "7"
        valuation = build_valuation(rows, indicators, NOW, rows[-1]["date"])
        advice = build_advice({"distance_ma250_pct": -5, "ma250_change_20d_pct": -1}, True, True, valuation)
        self.assertEqual(advice["state"], "consider")
        self.assertTrue(advice["eligible"])
        rows[-1]["pe_ttm"] = "9"
        expensive = build_valuation(rows, indicators, NOW, rows[-1]["date"])
        self.assertEqual(build_advice({"distance_ma250_pct": -5}, True, True, expensive)["state"], "wait")

    def test_collector_only_needs_official_data_and_failure_pauses_cached_advice(self):
        rows, indicators = valuation_inputs()
        rows = [{**row, "close": "1000"} for row in rows]
        rows[-1].update({"close": "900", "pe_ttm": "7"})
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}), \
             patch("scripts.fetch_dividend100.DATA_PATH", Path(directory) / "report.json"), \
             patch("scripts.fetch_dividend100.REPORT_PATH", Path(directory) / "report.md"), \
             patch("scripts.fetch_dividend100.datetime") as clock, \
             patch("scripts.fetch_dividend100.fetch_official", return_value=rows) as official, \
             patch("scripts.fetch_dividend100.fetch_indicators", return_value=indicators) as indicator:
            clock.now.return_value = NOW
            main()
            report = json.loads((Path(directory) / "report.json").read_text(encoding="utf-8"))
            official.assert_called_once()
            indicator.assert_called_once()
            self.assertTrue(report["advice"]["eligible"])
            self.assertEqual(report["verification"]["status"], "official_single")
            self.assertEqual(report["valuation"]["verification"]["status"], "official_single")
            self.assertNotIn("eastmoney", report["sources"])
            official.side_effect = RuntimeError("official endpoint unavailable")
            clock.now.return_value = NOW + timedelta(days=8)
            main()
            cached = json.loads((Path(directory) / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(cached["status"], "stale")
            self.assertEqual(cached["advice"]["state"], "paused")
            self.assertFalse(cached["advice"]["eligible"])
            self.assertEqual(cached["data_as_of"], report["data_as_of"])
            self.assertEqual(cached["valuation"]["verification"]["status"], "stale")

    def test_report_has_250_chart_points_and_safe_stale_advice(self):
        rows = history()
        report = build_report(rows, official_price_status(rows, NOW), NOW, "test")
        self.assertEqual(len(report["chart"]), 250)
        self.assertEqual(report["metrics"]["ma250"], 1424.5)
        stale = build_report(rows, official_price_status(rows, NOW), NOW + timedelta(days=8), "test")
        self.assertEqual(stale["advice"]["state"], "paused")

    def test_render_has_two_series_and_escaped_advice(self):
        rows = history()
        report = build_report(rows, official_price_status(rows, NOW), NOW, "test")
        report["advice"]["title"] = "<script>unsafe</script>"
        rendered = render_module(report)
        self.assertIn('data-series="ma250"', rendered)
        self.assertIn('data-series="close"', rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("{{DIV_", rendered)
        self.assertIn('data-eligible="false"', rendered)
        self.assertIn('id="dividend-budget-form"', rendered)
        self.assertIn("本次计算：", rendered)
        self.assertIn("中证官方单源", rendered)
        self.assertIn("待数据", rendered)


if __name__ == "__main__":
    unittest.main()
