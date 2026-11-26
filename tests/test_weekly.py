import datetime as dt
import pathlib
import sys
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))

from collect import update_reports
from github import fetch, from_graphql, lookup, parse_trending, rate_limit_wait, to_project
from rank import count_recent_stars, measure, pick_weekly, previous_week, score, streak

TODAY = dt.date(2026, 11, 30)  # 周一


def http_error(code, headers):
    return urllib.error.HTTPError('u', code, 'err', headers, None)


def repo(name, stars, created='2026-01-01T00:00:00Z', **extra):
    return dict(name=name, stars=stars, created=created, **extra)


def days_ago(n):
    return (TODAY - dt.timedelta(days=n)).isoformat()


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


class MeasureTests(unittest.TestCase):
    def test_exact_from_snapshot_seven_days_ago(self):
        h = {days_ago(8): {'o/a': 50}, days_ago(7): {'o/a': 100}, days_ago(3): {'o/a': 150}}
        self.assertEqual(measure(repo('o/a', 300), h, TODAY), (200, 'snapshot'))

    def test_older_base_is_scaled_back_to_seven_days(self):
        h = {days_ago(9): {'o/a': 100}}
        self.assertEqual(measure(repo('o/a', 1000), h, TODAY), (700, 'snapshot'))

    def test_base_older_than_nine_days_is_not_used(self):
        h = {days_ago(10): {'o/a': 100}}
        self.assertEqual(measure(repo('o/a', 1000), h, TODAY), (None, None))

    def test_short_history_is_not_extrapolated(self):
        h = {days_ago(2): {'o/a': 100}}
        self.assertEqual(measure(repo('o/a', 120), h, TODAY), (None, None))

    def test_new_repo_counts_all_stars(self):
        self.assertEqual(measure(repo('o/n', 80, days_ago(3) + 'T00:00:00Z'), {}, TODAY), (80, 'new'))

    def test_ignores_today_snapshot(self):
        self.assertEqual(measure(repo('o/a', 120), {TODAY.isoformat(): {'o/a': 120}}, TODAY), (None, None))

    def test_previous_week(self):
        h = {days_ago(14): {'o/a': 100}, days_ago(7): {'o/a': 400}}
        self.assertEqual(previous_week(repo('o/a', 1000), h, TODAY), 300)

    def test_repo_created_this_week_has_no_previous_week(self):
        self.assertIsNone(previous_week(repo('o/n', 80, days_ago(2) + 'T00:00:00Z'), {}, TODAY))


class ScoreTests(unittest.TestCase):
    def test_acceleration_is_clamped(self):
        self.assertEqual(score(1000, 10, 0), 1500)    # 上周不到 100 按 100 算，系数封顶 1.5
        self.assertEqual(score(1000, 5000, 0), 800)   # 减速最多打 8 折
        self.assertEqual(score(1000, None, 0), 1000)  # 没有上周数据不调整

    def test_streak_decay(self):
        self.assertEqual(score(1000, 1000, 1), 700)
        self.assertEqual(score(1000, 1000, 3), 500)

    def test_streak_counts_consecutive_prior_weeks(self):
        reports = [{'date': '2026-11-16', 'projects': [{'name': 'o/a'}]},
                   {'date': '2026-11-23', 'projects': [{'name': 'o/a'}]},
                   {'date': '2026-11-30', 'projects': [{'name': 'o/a'}]}]  # 本周自己的存档（重跑）不算
        self.assertEqual(streak('o/a', reports, TODAY), 2)
        self.assertEqual(streak('o/a', reports[:1], TODAY), 0)  # 上周没上榜，连续中断


class PickWeeklyTests(unittest.TestCase):
    def history(self, **weekly):
        """每个仓库 14 天前 0、7 天前 prev、今天的 stars 由 repo() 给出。"""
        return {days_ago(14): {n: 0 for n in weekly}, days_ago(7): {n: prev for n, prev in weekly.items()}}

    def test_repeat_winner_drops_below_newcomer(self):
        # 上周 13501、本周 3626 的老面孔，减速且连续上榜，排到本周 3000 的新面孔后面
        h = self.history(**{'o/old': 13501, 'o/new': 500})
        members = [repo('o/old', 13501 + 3626), repo('o/new', 500 + 3000)]
        reports = [{'date': '2026-11-23', 'projects': [{'name': 'o/old'}]}]
        weekly = pick_weekly(members, h, TODAY, reports=reports)
        self.assertEqual([p['name'] for p in weekly], ['o/new', 'o/old'])
        self.assertEqual((weekly[1]['weekly_stars'], weekly[1]['prev_stars'], weekly[1]['streak']), (3626, 13501, 1))

    def test_floor_then_fill(self):
        h = self.history(**{'o/big': 0, 'o/small': 0})
        members = [repo('o/small', 400), repo('o/big', 600)]
        weekly = pick_weekly(members, h, TODAY, n=2)
        self.assertEqual([p['name'] for p in weekly], ['o/big', 'o/small'])

    def test_forks_are_excluded(self):
        h = self.history(**{'o/f': 0})
        self.assertEqual(pick_weekly([repo('o/f', 9000, fork=True)], h, TODAY), [])

    def test_fallbacks_stargazers_then_trending(self):
        members = [repo('o/hot', 50000), repo('o/trend', 50000), repo('o/none', 50000)]
        asked = []
        def counter(name, pages):
            asked.append(name)
            return 2000, 20, False
        weekly = pick_weekly(members, {}, TODAY, trending=[('o/trend', 900)], hot=[('o/hot', 10)], counter=counter)
        self.assertEqual(asked, ['o/hot'])  # 只对 ClickHouse 榜上的数时间戳
        self.assertEqual([(p['name'], p['weekly_stars'], p['source']) for p in weekly], [('o/hot', 2000, 'stargazers'), ('o/trend', 900, 'trending')])
        self.assertTrue(weekly[1]['weekly_est'])

    def test_capped_count_takes_trending_if_larger(self):
        weekly = pick_weekly([repo('o/a', 99999)], {}, TODAY, trending=[('o/a', 12000)], hot=[('o/a', 1)],
                             counter=lambda name, pages: (5000, 50, True))
        self.assertEqual(weekly[0]['weekly_stars'], 12000)


class StargazerCountTests(unittest.TestCase):
    def page(self, times, more):
        return {'data': {'repository': {'stargazers': {'pageInfo': {'hasPreviousPage': more, 'startCursor': 'c'},
                                                       'edges': [{'starredAt': t} for t in times]}}}}

    def test_stops_at_first_old_star(self):
        pages = [self.page(['2026-11-25T00:00:00Z'] * 100, True), self.page(['2026-11-01T00:00:00Z', '2026-11-24T00:00:00Z'], True)]
        self.assertEqual(count_recent_stars('o/a', '2026-11-23T00:00:00Z', lambda q, v: pages.pop(0)), (101, 2, False))

    def test_reports_cap(self):
        post = lambda q, v: self.page(['2026-11-25T00:00:00Z'] * 100, True)
        self.assertEqual(count_recent_stars('o/a', '2026-11-23T00:00:00Z', post, max_pages=3), (300, 3, True))


class LookupTests(unittest.TestCase):
    node = {'nameWithOwner': 'o/a', 'url': 'https://github.com/o/a', 'description': None, 'stargazerCount': 12,
            'createdAt': '2026-11-20T00:00:00Z', 'pushedAt': '2026-11-25T00:00:00Z', 'isArchived': False, 'isFork': False,
            'primaryLanguage': None, 'licenseInfo': {'spdxId': 'MIT'},
            'repositoryTopics': {'nodes': [{'topic': {'name': 'ai'}}]}}

    def test_graphql_node_matches_rest_fields(self):
        p = to_project(from_graphql(self.node))
        self.assertEqual((p['name'], p['stars'], p['language'], p['description'], p['topics'], p['license'], p['fork']),
                         ('o/a', 12, '其他', '暂无介绍', ['ai'], 'MIT', False))

    def test_missing_and_archived_are_none_failed_batch_omitted(self):
        archived = dict(self.node, isArchived=True)
        replies = [{'data': {'r0': self.node, 'r1': None, 'r2': archived}}, {'data': None, 'errors': ['rate limited']}]
        result = lookup(['o/a', 'o/gone', 'o/old', 'o/unknown'], batch=3, post=lambda q: replies.pop(0))
        self.assertEqual(set(result), {'o/a', 'o/gone', 'o/old'})
        self.assertIsNone(result['o/gone'])
        self.assertIsNone(result['o/old'])


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
