import unittest
from folder_reader import credentials, folder_url, eligible_books, choose_book, ReadResults, ReadingBudget


class FolderReaderTests(unittest.TestCase):
    def test_midnight_preserves_session_total_and_separates_days(self):
        totals = {'2026-09-18': 120}
        budget = ReadingBudget({'daily_seconds': totals}, 7200, 21600)
        budget.record('2026-09-18', 5400)
        self.assertEqual(budget.remaining('2026-09-19'), 1800)
        budget.record('2026-09-19', 1800)
        self.assertEqual(budget.remaining('2026-09-19'), 0)
        self.assertEqual(totals, {'2026-09-18': 5520, '2026-09-19': 1800})

    def test_daily_cap_applies_to_resumed_and_following_sessions(self):
        totals = {'2026-09-19': 21570}
        budget = ReadingBudget({'daily_seconds': totals}, 7200, 21600)
        self.assertEqual(budget.remaining('2026-09-19'), 30)
        budget.record('2026-09-19', 30)
        self.assertEqual(budget.remaining('2026-09-19'), 0)
        following = ReadingBudget({'daily_seconds': totals}, 7200, 21600)
        self.assertEqual(following.remaining('2026-09-19'), 0)
        self.assertEqual(following.remaining('2026-09-20'), 7200)

    def test_cookie_header_and_bash_continuation(self):
        headers, cookies = credentials("curl 'https://weread.qq.com/web/book/read' \\\n -H 'User-Agent: test' -H 'Cookie: unrelated=private; wr_vid=123; wr_skey=abc=def'")
        self.assertEqual(cookies, {'wr_vid': '123', 'wr_skey': 'abc=def'})
        self.assertEqual(headers['user-agent'], 'test')
        self.assertRaises(ValueError, credentials, "curl 'https://weread.qq.com'")

    def test_only_configured_host_and_folder(self):
        self.assertEqual(folder_url('https://weread.qq.com/web/shelf/archive/123'), 'https://weread.qq.com/web/shelf/archive/123')
        for url in ['https://evil.example/web/shelf/archive/123', 'https://weread.qq.com/web/shelf', 'https://weread.qq.com/web/shelf/archive/123?x=1']:
            self.assertRaises(ValueError, folder_url, url)

    def test_exclusions_deduplication_and_persistent_selection(self):
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
        state = {'current': 'e', 'completed': []}
        self.assertEqual(choose_book(books, state)['id'], 'e')
        self.assertEqual(choose_book(list(reversed(books)), state)['id'], 'e')
        state['completed'].append('e')
        self.assertEqual(choose_book(books, state)['id'], 'd')
        state['completed'].append('d')
        self.assertIsNone(choose_book(books, state))
        self.assertIsNone(choose_book([], state))

    def test_new_book_does_not_replace_current_and_removed_book_can_change(self):
        books = [{'id': 'a'}, {'id': 'b'}, {'id': 'c'}]
        state = {'current': 'b', 'completed': []}
        self.assertEqual(choose_book(books, state)['id'], 'b')
        self.assertEqual(choose_book([books[0], books[2]], state)['id'], 'a')
        self.assertEqual(choose_book(books, {'current': None}, 'c')['id'], 'c')

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
