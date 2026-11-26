import datetime as dt
import pathlib
import sys
import unittest
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import time
import urllib.error

from collect import fetch, growth, parse_trending, pick_weekly, rate_limit_wait, record_stars, update_reports


def http_error(code, headers):
    return urllib.error.HTTPError('u', code, 'err', headers, None)


class RateLimitTests(unittest.TestCase):
    def test_waits_for_search_reset(self):
        e = http_error(403, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': str(int(time.time()) + 30)})
        self.assertTrue(25 <= rate_limit_wait(e) <= 32)

    def test_gives_up_when_hourly_quota_gone(self):
        e = http_error(403, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': str(int(time.time()) + 1800)})
        self.assertIsNone(rate_limit_wait(e))

    def test_retry_after(self):
        self.assertEqual(rate_limit_wait(http_error(429, {'Retry-After': '5'})), 5)

    def test_not_found_is_not_retried(self):
        calls = []
        def opener(*a, **k):
            calls.append(1)
            raise http_error(404, {})
        original = urllib.request.urlopen
        urllib.request.urlopen = opener
        try:
            with self.assertRaises(urllib.error.HTTPError):
                fetch('https://api.github.com/x', {}, sleep=lambda s: self.fail('404 不该重试'))
        finally:
            urllib.request.urlopen = original
        self.assertEqual(len(calls), 1)


def repo(name, stars, created='2026-01-01T00:00:00Z'):
    return {'name': name, 'stars': stars, 'created': created}


class GrowthTests(unittest.TestCase):
    today = dt.date(2026, 11, 26)

    def test_exact_from_snapshot_seven_days_ago(self):
        h = {'2026-11-18': {'o/a': 50}, '2026-11-19': {'o/a': 100}, '2026-11-22': {'o/a': 150}}
        self.assertEqual(growth(repo('o/a', 300), h, self.today), (200, False))

    def test_new_repo_counts_all_stars(self):
        self.assertEqual(growth(repo('o/n', 80, '2026-11-24T00:00:00Z'), {}, self.today), (80, False))

    def test_short_history_is_scaled_and_marked(self):
        h = {'2026-11-24': {'o/a': 100}}
        self.assertEqual(growth(repo('o/a', 120), h, self.today), (70, True))

    def test_unknown_without_history(self):
        self.assertEqual(growth(repo('o/a', 120), {}, self.today), (None, False))

    def test_ignores_today_snapshot(self):
        h = record_stars({}, [repo('o/a', 120)], self.today)
        self.assertEqual(growth(repo('o/a', 120), h, self.today), (None, False))

    def test_record_keeps_recent_days(self):
        h = record_stars({'2026-10-01': {'o/a': 1}, '2026-11-20': {'o/a': 2}}, [repo('o/a', 3)], self.today)
        self.assertEqual(list(h), ['2026-11-20', '2026-11-26'])


class PickWeeklyTests(unittest.TestCase):
    def test_ranks_by_growth_with_trending_fallback(self):
        projects = [
            dict(repo('o/big', 1), growth=900),               # 不在 Trending，但实际涨得多
            dict(repo('o/trend', 1), growth=None),            # 只有 Trending 数字
            dict(repo('o/est', 1), growth=5000, growth_est=True),  # 估算值，不参与
            dict(repo('o/est-trend', 1), growth=5000, growth_est=True),
        ]
        weekly = pick_weekly(projects, [('o/trend', 300), ('o/est-trend', 600)])
        self.assertEqual([(p['name'], p['weekly_stars']) for p in weekly], [('o/big', 900), ('o/est-trend', 600), ('o/trend', 300)])


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
