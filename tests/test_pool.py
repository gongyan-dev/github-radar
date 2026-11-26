import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))

from pool import admit, prune, record_stars, seed

TODAY = dt.date(2026, 11, 30)


def days_ago(n):
    return (TODAY - dt.timedelta(days=n)).isoformat()


class PoolTests(unittest.TestCase):
    def test_seed_from_existing_snapshots(self):
        pool = seed({days_ago(5): {'o/a': 1}, days_ago(2): {'o/a': 2, 'o/b': 3}}, TODAY)
        self.assertEqual(pool['o/a']['added'], days_ago(5))
        self.assertEqual(pool['o/b']['added'], days_ago(2))

    def test_admit_keeps_added_and_refreshes_seen(self):
        pool = {'o/a': {'added': days_ago(10), 'source': 'trending', 'seen': days_ago(10)}}
        admit(pool, [('o/a', 'clickhouse'), ('o/b', 'library')], TODAY)
        self.assertEqual(pool['o/a'], {'added': days_ago(10), 'source': 'trending', 'seen': TODAY.isoformat()})
        self.assertEqual(pool['o/b']['source'], 'library')

    def test_record_keeps_recent_days(self):
        h = record_stars({days_ago(60): {'o/a': 1}, days_ago(10): {'o/a': 2}}, [{'name': 'o/a', 'stars': 3}], TODAY)
        self.assertEqual(list(h), [days_ago(10), TODAY.isoformat()])

    def test_prune_idle_and_slow(self):
        entry = {'added': days_ago(40), 'source': 'clickhouse', 'seen': days_ago(30)}
        pool = {'o/slow': dict(entry), 'o/fast': dict(entry), 'o/seen': dict(entry, seen=days_ago(1)), 'o/young': dict(entry)}
        h = {days_ago(29): {'o/slow': 1000, 'o/fast': 1000, 'o/seen': 1000},
             TODAY.isoformat(): {'o/slow': 1100, 'o/fast': 1500, 'o/seen': 1000, 'o/young': 10}}
        self.assertEqual(prune(pool, h, TODAY), ['o/slow'])  # o/young 没有 28 天前的快照，先留着
        self.assertEqual(set(pool), {'o/fast', 'o/seen', 'o/young'})
