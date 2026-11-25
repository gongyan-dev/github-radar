import base64
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
from summarize import attach, clean, fingerprint, summarize


def project(name, description='desc'):
    return {'name': name, 'description': description, 'language': 'Python', 'topics': ['ai']}


def fake_get(path):
    return {'content': base64.b64encode(b'# Title\nREADME body').decode()}


class SummarizeTests(unittest.TestCase):
    def test_generates_only_missing_or_changed(self):
        a, b, c = project('o/a'), project('o/b'), project('o/c', 'new desc')
        cache = {'o/a': {'summary': '旧的介绍文字，已经有了', 'fp': fingerprint(a)},
                 'o/c': {'summary': '过期的介绍文字内容', 'fp': 'stale'}}
        calls = []
        llm = lambda p, text: calls.append((p['name'], text)) or f"{p['name']} 是一个用于测试的开源项目"
        self.assertEqual(summarize([a, b, c], cache, fake_get, llm, workers=1), 2)
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
        self.assertEqual(summarize([project('o/bad'), project('o/ok')], cache, fake_get, llm, workers=1), 1)
        self.assertEqual(list(cache), ['o/ok'])

    def test_skips_without_key(self):
        cache = {}
        self.assertEqual(summarize([project('o/a')], cache, fake_get), 0)
        self.assertEqual(cache, {})

    def test_clean_strips_think_and_quotes(self):
        self.assertEqual(clean('<think>想一想</think>\n"这是介绍。"'), '这是介绍。')

    def test_attach(self):
        ps = attach([project('o/a'), project('o/b')], {'o/a': {'summary': 'x', 'fp': ''}})
        self.assertEqual(ps[0]['summary'], 'x')
        self.assertNotIn('summary', ps[1])


if __name__ == '__main__':
    unittest.main()
