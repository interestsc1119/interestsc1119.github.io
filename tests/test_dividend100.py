import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from scripts.fetch_dividend100 import build_advice, build_report, clean_rows, moving_average, verify_sources
from scripts.render_dividend100 import render_module


NOW = datetime(2026, 10, 8, 18, tzinfo=ZoneInfo("Asia/Hong_Kong"))


def history(count=550):
    days, cursor = [], NOW.date()
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return [{"date": day.isoformat(), "close": str(1000 + i)} for i, day in enumerate(reversed(days))]


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
        self.assertEqual(build_advice({"distance_ma250_pct": 1, "ma250_change_20d_pct": 1}, True, True)["state"], "consider")
        self.assertEqual(build_advice({"distance_ma250_pct": 9, "ma250_change_20d_pct": 1}, True, True)["state"], "wait")
        self.assertEqual(build_advice({"distance_ma250_pct": -4, "ma250_change_20d_pct": -1}, True, True)["state"], "weak")

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


if __name__ == "__main__":
    unittest.main()
