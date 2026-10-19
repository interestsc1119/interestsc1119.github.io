import json
import os
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.dividend_yield_history import BASIS, build_yield_percentile, clean_observations, update_archive
from scripts.dividend_strategy import build_valuation
from scripts.fetch_dividend100 import main


NOW = datetime(2026, 10, 19, 18, tzinfo=ZoneInfo("Asia/Hong_Kong"))


def observations(count=20):
    days, cursor = [], NOW.date()
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return [{"date": day, "dividend_yield": "4"} for day in reversed(days)]


class DividendYieldHistoryTests(unittest.TestCase):
    def test_short_sample_is_explicitly_not_five_year_percentile(self):
        rows = observations()
        rows[-1]["dividend_yield"] = "5"
        rank = build_yield_percentile(rows, 5, rows[-1]["date"], rows[-1]["date"], NOW)
        self.assertEqual(rank["percentile"], 97.5)
        self.assertIsNone(rank["percentile_5y"])
        self.assertEqual(rank["status"], "recent_sample")
        self.assertIn("非5年", rank["label"])
        self.assertEqual(rank["sample_days"], 20)
        self.assertEqual((rank["start"], rank["end"]), (rows[0]["date"], rows[-1]["date"]))

    def test_midrank_ties_and_lower_yield_have_lower_rank(self):
        rows = observations()
        equal = build_yield_percentile(rows, 4, rows[-1]["date"], rows[-1]["date"], NOW)
        self.assertEqual(equal["percentile"], 50)
        rows[-1]["dividend_yield"] = "3"
        lower = build_yield_percentile(rows, 3, rows[-1]["date"], rows[-1]["date"], NOW)
        self.assertEqual(lower["percentile"], 2.5)
        for row in rows[:10]:
            row["dividend_yield"] = "3"
        for row in rows[10:]:
            row["dividend_yield"] = "4"
        ties = build_yield_percentile(rows, 4, rows[-1]["date"], rows[-1]["date"], NOW)
        self.assertEqual(ties["percentile"], 75)

    def test_insufficient_missing_stale_and_misaligned_data_do_not_show_rank(self):
        rows = observations()
        cases = [
            (rows[-19:], 4, rows[-1]["date"], rows[-1]["date"], NOW),
            (rows, None, rows[-1]["date"], rows[-1]["date"], NOW),
            (rows, 4, rows[-1]["date"], "2026-10-20", NOW),
            (rows, 4, rows[-1]["date"], rows[-1]["date"], NOW + timedelta(days=8)),
            (rows, 5, rows[-1]["date"], rows[-1]["date"], NOW),
        ]
        for args in cases:
            with self.subTest(args=args[1:]):
                result = build_yield_percentile(*args)
                self.assertIsNone(result["percentile"])
                self.assertIsNone(result["percentile_5y"])

    def test_only_long_history_unlocks_five_year_window(self):
        rows = observations(1400)
        rank = build_yield_percentile(rows, 4, rows[-1]["date"], rows[-1]["date"], NOW)
        self.assertEqual(rank["status"], "five_year_window")
        self.assertEqual(rank["percentile_5y"], 50)
        self.assertLessEqual(rank["sample_days"], 1250)
        self.assertGreaterEqual(rank["sample_days"], 1000)
        self.assertGreaterEqual(rank["start"], "2021-10-19")

    def test_invalid_future_weekend_and_open_session_values_are_filtered(self):
        row = observations(1)[0]
        invalid = [{**row, "dividend_yield": value} for value in (None, "NaN", "Infinity", 0, -1, 101)]
        invalid += [{"date": "2026-10-20", "dividend_yield": "4"}, {"date": "2026-10-18", "dividend_yield": "4"}]
        self.assertEqual(clean_observations(invalid + [row], NOW), [row])
        self.assertEqual(clean_observations([row], NOW.replace(hour=10)), [])

    def test_duplicate_dates_do_not_inflate_sample_and_conflicts_reject(self):
        row = observations(1)[0]
        self.assertEqual(len(clean_observations([row, {**row, "dividend_yield": "4.00"}], NOW)), 1)
        with self.assertRaises(ValueError):
            clean_observations([row, {**row, "dividend_yield": "5"}], NOW)

    def test_archive_retains_old_sessions_and_audits_official_revisions(self):
        rows = observations(25)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            first = update_archive(path, rows[:20], NOW)
            self.assertEqual(len(first), 20)
            second = update_archive(path, rows[5:], NOW)
            self.assertEqual(len(second), 25)
            self.assertEqual(second[0]["date"], rows[0]["date"])
            revised = update_archive(path, [{**rows[-1], "dividend_yield": "4.1"}], NOW)
            self.assertEqual(len(revised), 25)
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["basis"], BASIS)
            self.assertEqual(len(stored["revisions"]), 1)
            self.assertEqual(stored["revisions"][0]["old"], "4")
            before = path.read_bytes()
            self.assertEqual(update_archive(path, [], NOW), revised)
            self.assertEqual(path.read_bytes(), before)

    def test_wrong_basis_or_corrupt_archive_is_not_overwritten(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            update_archive(path, observations(), NOW)
            data = json.loads(path.read_text(encoding="utf-8"))
            for change in ({**data, "basis": "DP2"}, {**data, "code": "000922"}, {**data, "unit": "fraction"}):
                path.write_text(json.dumps(change), encoding="utf-8")
                before = path.read_bytes()
                with self.assertRaises(ValueError):
                    update_archive(path, observations(), NOW)
                self.assertEqual(path.read_bytes(), before)
            path.write_text("not JSON", encoding="utf-8")
            with self.assertRaises(ValueError):
                update_archive(path, observations(), NOW)
            self.assertEqual(path.read_text(encoding="utf-8"), "not JSON")

    def test_new_percentile_does_not_change_allocation_readiness(self):
        rows = [{"date": row["date"], "close": "1000", "pe_ttm": "8"} for row in observations(1400)]
        indicators = [{"date": row["date"], "pe_total": 8, "dividend_yield": 4} for row in observations()]
        without = build_valuation(rows, indicators, NOW, rows[-1]["date"])
        with_rank = build_valuation(rows, indicators, NOW, rows[-1]["date"], observations())
        self.assertEqual(with_rank["dividend_history"]["percentile"], 50)
        self.assertEqual(without["verification"], with_rank["verification"])

    def test_archive_error_does_not_pause_existing_buy_rule(self):
        rows = [{"date": row["date"], "close": "1000", "pe_ttm": "8"} for row in observations(1400)]
        rows[-1].update({"close": "900", "pe_ttm": "7"})
        indicators = [{"date": NOW.date().isoformat(), "pe_total": 7, "dividend_yield": 5}]
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}), \
             patch("scripts.fetch_dividend100.DATA_PATH", Path(directory) / "report.json"), \
             patch("scripts.fetch_dividend100.REPORT_PATH", Path(directory) / "report.md"), \
             patch("scripts.fetch_dividend100.datetime") as clock, \
             patch("scripts.fetch_dividend100.fetch_official", return_value=rows), \
             patch("scripts.fetch_dividend100.fetch_indicators", return_value=indicators), \
             patch("scripts.fetch_dividend100.update_archive", side_effect=ValueError("corrupt archive")):
            clock.now.return_value = NOW
            main()
            report = json.loads((Path(directory) / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["advice"]["eligible"])
            self.assertEqual(report["valuation"]["dividend_history"]["status"], "invalid")
            self.assertIsNone(report["valuation"]["dividend_history"]["percentile"])


if __name__ == "__main__":
    unittest.main()
