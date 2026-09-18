import unittest
from datetime import date, timedelta
from folder_reader import credentials, folder_url, eligible_books, choose_book, ReadResults


class FolderReaderTests(unittest.TestCase):
    def test_cookie_header_and_bash_continuation(self):
        headers, cookies = credentials("curl 'https://weread.qq.com/web/book/read' \\\n -H 'User-Agent: test' -H 'Cookie: unrelated=private; wr_vid=123; wr_skey=abc=def'")
        self.assertEqual(cookies, {'wr_vid': '123', 'wr_skey': 'abc=def'})
        self.assertEqual(headers['user-agent'], 'test')
        self.assertRaises(ValueError, credentials, "curl 'https://weread.qq.com'")

    def test_only_configured_host_and_folder(self):
        self.assertEqual(folder_url('https://weread.qq.com/web/shelf/archive/123'), 'https://weread.qq.com/web/shelf/archive/123')
        for url in ['https://evil.example/web/shelf/archive/123', 'https://weread.qq.com/web/shelf', 'https://weread.qq.com/web/shelf/archive/123?x=1']:
            self.assertRaises(ValueError, folder_url, url)

    def test_exclusions_deduplication_and_daily_rotation(self):
        books = eligible_books([
            {'title': '三体全集', 'url': 'https://weread.qq.com/web/reader/a'},
            {'title': '三體2', 'url': 'https://weread.qq.com/web/reader/b'},
            {'title': 'The Three-Body Problem', 'url': 'https://weread.qq.com/web/reader/c'},
            {'title': 'A', 'url': 'https://weread.qq.com/web/reader/d'},
            {'title': 'A', 'url': 'https://weread.qq.com/web/reader/d'},
            {'title': 'B', 'url': 'https://weread.qq.com/web/reader/e'},
            {'title': 'external', 'url': 'https://evil.example/web/reader/f'},
        ])
        self.assertEqual(len(books), 2)
        today = date(2026, 9, 18)
        self.assertNotEqual(choose_book(books, today), choose_book(books, today + timedelta(days=1)))
        self.assertRaises(ValueError, choose_book, [])

    def test_response_must_match_selected_book_and_succeed(self):
        results = ReadResults('chosen')
        results.record({'b': 'chosen', 'rt': 30}, {'succ': 1, 'synckey': 123})
        results.record({'b': 'chosen', 'rt': 30}, {'succ': 0, 'synckey': 123})
        results.record({'b': 'other', 'rt': 30}, {'succ': 1, 'synckey': 123})
        self.assertEqual(results.successes, 1)
        self.assertEqual(results.reported_seconds, 30)
        self.assertEqual(results.failures, 1)
        self.assertTrue(results.outside_folder)


if __name__ == '__main__':
    unittest.main()
