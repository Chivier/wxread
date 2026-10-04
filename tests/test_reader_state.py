import json
from pathlib import Path
import tempfile
import unittest
from cryptography.fernet import Fernet
from reader_state import Checkpoint, refresh_login_if_changed
from folder_reader import caught_up_page, finished_page, ReadingBudget


class FakeText:
    """Visible text plus the CSS classes of the reader's back cover, if shown."""
    def __init__(self, texts, classes=()):
        self.texts = texts
        self.classes = classes
        self.first = self
    def get_by_text(self, text, exact):
        self.visible = text in self.texts
        return self
    def locator(self, selector):
        self.visible = selector.lstrip('.') in self.classes
        return self
    def is_visible(self):
        return self.visible


class StateTests(unittest.TestCase):
    def test_session_budget_survives_repeated_checkpoint_saves_and_midnight(self):
        key = Fernet.generate_key().decode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'checkpoint.enc'
            checkpoint = Checkpoint(path, key, 'folder')
            checkpoint.data['current'] = 'selected-book'
            budget = ReadingBudget(checkpoint.data, 90, 21600)
            for day in ['2026-09-18', '2026-09-18', '2026-09-19']:
                budget.record(day, 30)
                checkpoint.save()
            restored = Checkpoint(path, key, 'folder', required=True)
            self.assertEqual(budget.remaining('2026-09-19'), 0)
            self.assertEqual(restored.data['daily_seconds'], {'2026-09-18': 60, '2026-09-19': 30})
            self.assertEqual(restored.data['current'], 'selected-book')

    def test_roundtrip_persists_book_budget_and_session_without_plaintext(self):
        key = Fernet.generate_key().decode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'checkpoint.enc'
            state = Checkpoint(path, key, 'folder')
            state.data['current'] = 'selected-book'
            state.add_seconds('2026-09-18', 60)
            state.save({'cookies': [{'name': 'wr_skey', 'value': 'private-token'}]})
            raw = path.read_bytes()
            self.assertNotIn(b'private-token', raw)
            self.assertNotIn(b'selected-book', raw)
            restored = Checkpoint(path, key, 'folder', required=True)
            self.assertEqual(restored.data['current'], 'selected-book')
            restored.add_seconds('2026-09-18', 30)
            restored.add_seconds('2026-09-19', 30)
            self.assertEqual(restored.data['daily_seconds']['2026-09-18'], 90)
            self.assertEqual(restored.data['daily_seconds']['2026-09-19'], 30)
            restored.complete('selected-book')
            restored.save()
            restored = Checkpoint(path, key, 'folder', required=True)
            self.assertIsNone(restored.data['current'])
            self.assertIn('selected-book', restored.data['completed'])

    def test_missing_corrupt_wrong_key_or_folder_never_resets_progress(self):
        key = Fernet.generate_key().decode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'checkpoint.enc'
            self.assertRaises(ValueError, Checkpoint, path, key, 'folder', True)
            state = Checkpoint(path, key, 'folder')
            state.save()
            self.assertRaises(ValueError, Checkpoint, path, key, 'other-folder')
            self.assertRaises(ValueError, Checkpoint, path, Fernet.generate_key().decode(), 'folder')
            path.write_bytes(b'broken')
            self.assertRaises(ValueError, Checkpoint, path, key, 'folder')

    def test_login_refresh_preserves_book_completion_and_daily_budget(self):
        state = {'current': 'book', 'completed': ['old-book'], 'daily_seconds': {'2026-09-18': 7200}, 'storage': {'cookies': []}}
        self.assertTrue(refresh_login_if_changed(state, 'fresh request'))
        self.assertIsNone(state['storage'])
        self.assertEqual(state['current'], 'book')
        self.assertEqual(state['completed'], ['old-book'])
        self.assertEqual(state['daily_seconds']['2026-09-18'], 7200)
        state['storage'] = {'cookies': ['refreshed session']}
        self.assertFalse(refresh_login_if_changed(state, 'fresh request'))
        self.assertIsNotNone(state['storage'])

    def test_paywall_or_missing_next_page_is_not_completion(self):
        self.assertTrue(finished_page(FakeText(['全书完'])))
        for content in [[], ['购买本章'], ['未完待续'], ['下一页'], ['小说中的一句全书完']]:
            self.assertFalse(finished_page(FakeText(content)))

    def test_back_cover_class_separates_finished_book_from_waiting_serial(self):
        # The site renders the labels with spaces ("全 书 完", "未 完 待 续").
        finished = FakeText(['全 书 完'], ['readerFooter_ending_finish'])
        serial = FakeText(['未 完 待 续'], ['readerFooter_ending_continue'])
        self.assertTrue(finished_page(finished))
        self.assertFalse(caught_up_page(finished))
        self.assertTrue(caught_up_page(serial))
        self.assertFalse(finished_page(serial))
        self.assertFalse(caught_up_page(FakeText(['购买本章'])))

    def test_parking_a_serial_keeps_only_todays_entries(self):
        key = Fernet.generate_key().decode()
        with tempfile.TemporaryDirectory() as directory:
            state = Checkpoint(Path(directory) / 'checkpoint.enc', key, 'folder')
            state.park('old', '2026-10-03')
            state.park('serial', '2026-10-04')
            self.assertEqual(state.data['caught_up'], {'serial': '2026-10-04'})
            self.assertEqual(state.data['completed'], [])


if __name__ == '__main__':
    unittest.main()
