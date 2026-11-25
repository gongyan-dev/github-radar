import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
from collect import parse_trending, update_reports


class TrendingTests(unittest.TestCase):
    def test_ranks_weekly_stars_and_caps_at_ten(self):
        articles = [f'<article class="Box-row"><h2><a href="/owner/repo{i}">repo</a></h2><span>{i:,} stars this week</span></article>' for i in range(12)]
        articles.append('<article class="Box-row"><h2><a href="/ignored/repo">repo</a></h2>no weekly count</article>')
        self.assertEqual(parse_trending(''.join(articles)), [(f'owner/repo{i}', i) for i in range(11, 1, -1)])

    def test_fails_when_page_structure_changes(self):
        with self.assertRaises(ValueError):
            parse_trending('<article class="Box-row">missing weekly count</article>')


class ReportTests(unittest.TestCase):
    weekly = [{'name': 'a/b'}]

    def test_archives_on_monday(self):
        reports = update_reports([], self.weekly, dt.date(2026, 11, 23))
        self.assertEqual([r['date'] for r in reports], ['2026-11-23'])

    def test_monday_rerun_replaces_same_day(self):
        old = [{'date': '2026-11-23', 'projects': []}]
        reports = update_reports(old, self.weekly, dt.date(2026, 11, 23))
        self.assertEqual(reports, [{'date': '2026-11-23', 'projects': self.weekly}])

    def test_backfills_when_monday_missed(self):
        old = [{'date': '2026-11-16', 'projects': []}]
        reports = update_reports(old, self.weekly, dt.date(2026, 11, 25))
        self.assertEqual([r['date'] for r in reports], ['2026-11-16', '2026-11-25'])

    def test_skips_when_week_already_archived(self):
        old = [{'date': '2026-11-23', 'projects': []}]
        self.assertIs(update_reports(old, self.weekly, dt.date(2026, 11, 25)), old)

    def test_skips_without_weekly_data(self):
        self.assertEqual(update_reports([], [], dt.date(2026, 11, 23)), [])
