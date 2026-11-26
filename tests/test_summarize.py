import base64
import pathlib
import sys
import unittest
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
from summarize import attach, clean, fingerprint, readme, retry, summarize


def project(name, description='desc'):
    return {'name': name, 'description': description, 'language': 'Python', 'topics': ['ai']}


def fake_get(path):
    return {'content': base64.b64encode(b'# Title\nREADME body').decode()}


def no_raw(name):  # 模拟 raw 链接拿不到，走 API
    return None


class SummarizeTests(unittest.TestCase):
    def test_generates_only_missing_or_changed(self):
        a, b, c = project('o/a'), project('o/b'), project('o/c', 'new desc')
        cache = {'o/a': {'summary': '旧的介绍文字，已经有了', 'fp': fingerprint(a)},
                 'o/c': {'summary': '过期的介绍文字内容', 'fp': 'stale'}}
        calls = []
        llm = lambda p, text: calls.append((p['name'], text)) or f"{p['name']} 是一个用于测试的开源项目"
        self.assertEqual(summarize([a, b, c], cache, fake_get, llm, workers=1, raw=no_raw), 2)
        self.assertEqual([n for n, _ in calls], ['o/b', 'o/c'])
        self.assertIn('README body', calls[0][1])
        self.assertEqual(cache['o/a']['summary'], '旧的介绍文字，已经有了')
        self.assertEqual(cache['o/c']['fp'], fingerprint(c))

    def test_failure_keeps_going(self):
        def llm(p, text):
            if p['name'] == 'o/bad':
                raise RuntimeError('boom')
            return '这是一个正常生成的项目介绍'
        cache = {}
        self.assertEqual(summarize([project('o/bad'), project('o/ok')], cache, fake_get, llm, workers=1, raw=no_raw), 1)
        self.assertEqual(list(cache), ['o/ok'])

    def test_skips_without_key(self):
        cache = {}
        self.assertEqual(summarize([project('o/a')], cache, fake_get), 0)
        self.assertEqual(cache, {})

    def test_clean_strips_think_and_quotes(self):
        self.assertEqual(clean('<think>想一想</think>\n"这是介绍。"'), '这是介绍。')

    def test_clean_drops_unclosed_think(self):
        self.assertEqual(clean('<think>想到一半被截断'), '')

    def test_retry_on_rate_limit_then_succeeds(self):
        waits, calls = [], []
        def call():
            calls.append(1)
            if len(calls) < 3:
                raise urllib.error.HTTPError('u', 429, 'Too Many Requests', {'Retry-After': '7'}, None)
            return 'ok'
        self.assertEqual(retry(call, sleep=waits.append), 'ok')
        self.assertEqual(waits, [7, 7])

    def test_retry_gives_up_on_client_error(self):
        def call():
            raise urllib.error.HTTPError('u', 401, 'Unauthorized', {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            retry(call, sleep=lambda s: self.fail('不应重试'))

    def test_readme_prefers_raw_and_skips_api(self):
        api = lambda path: self.fail('raw 拿到了就不该调 API')
        self.assertEqual(readme(api, 'o/a', raw=lambda name: '# T\n\n\nbody'), '# T\nbody')

    def test_readme_falls_back_to_api(self):
        self.assertIn('README body', readme(fake_get, 'o/a', raw=no_raw))

    def test_attach(self):
        ps = attach([project('o/a'), project('o/b')], {'o/a': {'summary': 'x', 'fp': ''}})
        self.assertEqual(ps[0]['summary'], 'x')
        self.assertNotIn('summary', ps[1])


if __name__ == '__main__':
    unittest.main()
