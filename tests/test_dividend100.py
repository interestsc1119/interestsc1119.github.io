import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from scripts.fetch_dividend100 import build_advice, build_report, clean_rows, moving_average, verify_sources
from scripts.render_dividend100 import render_module
from scripts.dividend_strategy import BASIS, build_valuation, historical_percentile


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
            "verification": {"status": "verified", "label": "测试数据"}}


def valuation_inputs():
    rows = [{**row, "pe_ttm": "8"} for row in history(1400)]
    day = rows[-1]["date"]
    indicators = [{"date": day, "pe_total": 8, "dividend_yield": 5}]
    reference = {"code": "930955", "date": day, "basis": BASIS, "pe_ttm": 8, "dividend_yield": 5,
                 "source": {"name": "Independent test fixture", "url": "https://independent.test/data"}}
    return rows, indicators, reference


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

    def test_double_source_and_historical_mismatch(self):
        rows = history()
        self.assertEqual(verify_sources(rows, rows)["status"], "verified")
        altered = [dict(row) for row in rows]
        altered[-10]["close"] = "9999"
        self.assertEqual(verify_sources(rows, altered)["status"], "mismatch")

    def test_date_mismatch_suspends_verification(self):
        rows = history()
        self.assertEqual(verify_sources(rows, rows[:-1])["status"], "pending")

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

    def test_valuation_is_verified_only_with_same_basis_independent_source(self):
        rows, indicators, reference = valuation_inputs()
        valuation = build_valuation(rows, indicators, reference, NOW, rows[-1]["date"])
        self.assertEqual(valuation["verification"]["status"], "verified")
        self.assertEqual(valuation["pe_percentile_5y"], 50)
        self.assertGreaterEqual(valuation["history_days"], 1000)
        self.assertLessEqual(valuation["history_days"], 1250)
        self.assertEqual(build_valuation(rows, indicators, None, NOW, rows[-1]["date"])["verification"]["status"], "pending")
        same_source = {**reference, "source": {"name": "CSI", "url": "https://oss-ch.csindex.com.cn/data"}}
        self.assertEqual(build_valuation(rows, indicators, same_source, NOW, rows[-1]["date"])["verification"]["status"], "pending")

    def test_valuation_mismatch_dates_and_basis_pause(self):
        rows, indicators, reference = valuation_inputs()
        for altered in ({**reference, "code": "000922"}, {**reference, "basis": "equal_weight_pe"},
                        {**reference, "date": "2026-10-07"}, {**reference, "dividend_yield": None}):
            self.assertNotEqual(build_valuation(rows, indicators, altered, NOW, rows[-1]["date"])["verification"]["status"], "verified")
        for altered in ({**reference, "pe_ttm": 9}, {**reference, "dividend_yield": 6}):
            self.assertEqual(build_valuation(rows, indicators, altered, NOW, rows[-1]["date"])["verification"]["status"], "mismatch")
        self.assertEqual(build_valuation(rows, indicators, reference, NOW + timedelta(days=8), rows[-1]["date"])["verification"]["status"], "pending")

    def test_valuation_missing_history_or_same_date_yield_pauses(self):
        rows, indicators, reference = valuation_inputs()
        self.assertNotEqual(build_valuation(rows[-999:], indicators, reference, NOW, rows[-1]["date"])["verification"]["status"], "verified")
        indicators[0]["date"] = "2026-10-07"
        self.assertNotEqual(build_valuation(rows, indicators, reference, NOW, rows[-1]["date"])["verification"]["status"], "verified")

    def test_report_has_250_chart_points_and_safe_stale_advice(self):
        rows = history()
        report = build_report(rows, verify_sources(rows, rows), NOW, "test")
        self.assertEqual(len(report["chart"]), 250)
        self.assertEqual(report["metrics"]["ma250"], 1424.5)
        stale = build_report(rows, verify_sources(rows, rows), NOW + timedelta(days=8), "test")
        self.assertEqual(stale["advice"]["state"], "paused")

    def test_render_has_two_series_and_escaped_advice(self):
        rows = history()
        report = build_report(rows, verify_sources(rows, rows), NOW, "test")
        report["advice"]["title"] = "<script>unsafe</script>"
        rendered = render_module(report)
        self.assertIn('data-series="ma250"', rendered)
        self.assertIn('data-series="close"', rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("{{DIV_", rendered)
        self.assertIn('data-eligible="false"', rendered)
        self.assertIn('id="dividend-budget-form"', rendered)


if __name__ == "__main__":
    unittest.main()
