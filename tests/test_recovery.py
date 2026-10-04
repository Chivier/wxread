import os
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
import folder_reader
from reader_state import Checkpoint, refresh_login_if_changed
from plan_reading import remaining_today, main as check_budget


class FakePage:
    def __init__(self, context):
        self.context = context
        self.callback = None

    def set_default_timeout(self, value):
        pass

    def on(self, event, callback):
        self.callback = callback

    def goto(self, url, **kwargs):
        self.url = url
        self.context.opened.append(url)

    def get_by_role(self, *args, **kwargs):
        return self

    def wait_for(self, **kwargs):
        pass

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def press(self, key):
        pass

    def wait_for_timeout(self, milliseconds):
        if milliseconds != 30000:
            return
        self.context.requests += 1
        expired = self.context.always_expired or self.context.requests == 2
        body = {'errCode': -2010} if expired else {'succ': 1, 'synckey': 1}
        self.callback(SimpleNamespace(
            url=folder_reader.READ_URL, status=200,
            request=SimpleNamespace(post_data_json={
                'b': self.url.rsplit('/', 1)[1], 'c': 'chapter', 'co': self.context.requests * 100, 'rt': 30,
            }), json=lambda: body,
        ))

    def close(self):
        pass


class FakeBrowser:
    def __init__(self, always_expired=False):
        self.requests = 0
        self.opened = []
        self.always_expired = always_expired
        self.chromium = self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def launch(self, **kwargs):
        return self

    def new_context(self, **kwargs):
        return self

    def new_page(self):
        return FakePage(self)

    def storage_state(self):
        return {'cookies': [], 'origins': []}

    def close(self):
        pass


class RecoveryTests(unittest.TestCase):
    def test_signed_out_shelf_is_classified_without_losing_checkpoint(self):
        class SignedOutPage:
            def goto(self, url, **kwargs):
                pass

            def get_by_role(self, role, **kwargs):
                self.role = role
                return self

            def filter(self, **kwargs):
                return self

            def wait_for(self, **kwargs):
                raise TimeoutError('folder heading absent')

            def is_visible(self):
                return self.role == 'button'

            def close(self):
                pass

        context = SimpleNamespace(new_page=SignedOutPage)
        with self.assertRaises(folder_reader.LoginRequiredError):
            folder_reader.load_folder(context, 'https://weread.qq.com/web/shelf/archive/123', 'Folder')

    def exercise_recovery(self, always_expired=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'checkpoint.enc'
            key = Fernet.generate_key().decode()
            source = 'https://weread.qq.com/web/shelf/archive/123'
            curl = "curl https://weread.qq.com -b 'wr_vid=example; wr_skey=example'"
            state = Checkpoint(path, key, source)
            state.data['current'] = 'chosen'
            state.data['completed'] = ['finished']
            state.data['daily_seconds'] = {'2026-09-20': 1000}
            refresh_login_if_changed(state.data, curl)
            state.save({'cookies': [], 'origins': []})
            browser = FakeBrowser(always_expired)
            book = {'id': 'chosen', 'title': 'Book', 'url': 'https://weread.qq.com/web/reader/chosen'}
            env = dict(READER_STATE_PATH=str(path), WXREAD_STATE_KEY=key,
                       WXREAD_CURL_BASH=curl, READ_FOLDER_URL=source,
                       READ_FOLDER_NAME='Folder', READ_NUM='2', DAILY_READ_SECONDS='21600',
                       REQUIRE_READER_STATE='true')
            api = SimpleNamespace(sync_playwright=lambda: browser)
            with patch.dict(os.environ, env, clear=True), \
                 patch.dict('sys.modules', {'playwright.sync_api': api}), \
                 patch.object(folder_reader, 'china_day', return_value='2026-09-20'), \
                 patch.object(folder_reader.logging, 'warning'), \
                 patch.object(folder_reader, 'finished_page', return_value=False), \
                 patch.object(folder_reader, 'caught_up_page', return_value=False), \
                 patch.object(folder_reader, 'load_folder', return_value=[book]) as load:
                if always_expired:
                    with self.assertRaisesRegex(RuntimeError, 'Login recovery failed repeatedly'):
                        folder_reader.run()
                    self.assertEqual(load.call_count, 4)  # Initial visit plus three retries.
                else:
                    folder_reader.run()
                    self.assertEqual(load.call_count, 2)
            restored = Checkpoint(path, key, source, required=True)
            self.assertEqual(restored.data['current'], 'chosen')
            self.assertEqual(restored.data['completed'], ['finished'])
            self.assertEqual(restored.data['daily_seconds']['2026-09-20'], 1000 if always_expired else 1060)
            self.assertTrue(all(url == book['url'] for url in browser.opened))

    def test_expiry_mid_session_renews_and_finishes_remaining_budget(self):
        self.exercise_recovery()

    def test_invalid_long_lived_login_stops_after_bounded_retries(self):
        self.exercise_recovery(always_expired=True)

    def test_serial_at_latest_chapter_yields_to_next_book_without_being_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'checkpoint.enc'
            key = Fernet.generate_key().decode()
            source = 'https://weread.qq.com/web/shelf/archive/123'
            curl = "curl https://weread.qq.com -b 'wr_vid=example; wr_skey=example'"
            state = Checkpoint(path, key, source)
            state.data['current'] = 'serial'
            state.data['caught_up'] = {'old': '2026-09-19'}
            refresh_login_if_changed(state.data, curl)
            state.save({'cookies': [], 'origins': []})
            browser = FakeBrowser()
            books = [{'id': name, 'title': name, 'url': f'https://weread.qq.com/web/reader/{name}'}
                     for name in ('other', 'serial')]
            env = dict(READER_STATE_PATH=str(path), WXREAD_STATE_KEY=key,
                       WXREAD_CURL_BASH=curl, READ_FOLDER_URL=source,
                       READ_FOLDER_NAME='Folder', READ_NUM='1', DAILY_READ_SECONDS='21600',
                       REQUIRE_READER_STATE='true')
            api = SimpleNamespace(sync_playwright=lambda: browser)
            with patch.dict(os.environ, env, clear=True), \
                 patch.dict('sys.modules', {'playwright.sync_api': api}), \
                 patch.object(folder_reader, 'china_day', return_value='2026-09-20'), \
                 patch.object(folder_reader, 'finished_page', return_value=False), \
                 patch.object(folder_reader, 'caught_up_page',
                              side_effect=lambda page: page.url.endswith('/serial')), \
                 patch.object(folder_reader, 'load_folder', return_value=books):
                folder_reader.run()
            restored = Checkpoint(path, key, source, required=True)
            self.assertEqual(browser.opened, [books[1]['url'], books[0]['url']])
            self.assertEqual(restored.data['current'], 'other')
            self.assertEqual(restored.data['completed'], [])
            self.assertEqual(restored.data['caught_up'], {'serial': '2026-09-20'})
            self.assertEqual(restored.data['daily_seconds']['2026-09-20'], 30)

    def test_wait_for_next_accepts_late_back_cover_and_rejects_unknown_stall(self):
        class Next:
            def wait_for(self, **kwargs):
                raise TimeoutError('no next button')

        results = folder_reader.ReadResults('serial')
        with patch.object(folder_reader, 'finished_page', return_value=False), \
             patch.object(folder_reader, 'caught_up_page', side_effect=[False, True]):
            folder_reader.wait_for_next(None, Next(), results)
        with patch.object(folder_reader, 'finished_page', return_value=False), \
             patch.object(folder_reader, 'caught_up_page', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'Cannot advance'):
                folder_reader.wait_for_next(None, Next(), results)

    def test_checkpoint_download_retries_transient_failures(self):
        import state_artifacts
        with patch.object(state_artifacts, 'restore', side_effect=[OSError('api'), None]) as restore, \
             patch.object(state_artifacts.time, 'sleep') as sleep, \
             patch('sys.stdout', new_callable=io.StringIO):
            state_artifacts.restore_with_retries()
            self.assertEqual(restore.call_count, 2)
            sleep.assert_called_once_with(10)
        with patch.object(state_artifacts, 'restore', side_effect=OSError('api')) as restore, \
             patch.object(state_artifacts.time, 'sleep'), \
             patch('sys.stdout', new_callable=io.StringIO):
            self.assertRaises(OSError, state_artifacts.restore_with_retries)
            self.assertEqual(restore.call_count, 4)

    def test_supplemental_runs_stop_at_daily_cap_and_next_day_resets(self):
        state = {'daily_seconds': {'2026-09-20': 21600}}
        self.assertEqual(remaining_today(state, '2026-09-20', 21600), 0)
        self.assertEqual(remaining_today(state, '2026-09-21', 21600), 21600)
        state['daily_seconds']['2026-09-20'] = 11310
        self.assertEqual(remaining_today(state, '2026-09-20', 21600), 10290)

    def test_final_audit_rejects_incomplete_days_and_skip_plan_disables_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.enc'
            output = Path(directory) / 'outputs'
            key = Fernet.generate_key().decode()
            source = 'https://weread.qq.com/web/shelf/archive/123'
            checkpoint = Checkpoint(path, key, source)
            checkpoint.data['daily_seconds'] = {'2026-09-20': 11310}
            checkpoint.save()
            env = dict(READER_STATE_PATH=str(path), WXREAD_STATE_KEY=key,
                       READ_FOLDER_URL=source, REQUIRE_READER_STATE='true', GITHUB_OUTPUT=str(output))
            with patch.dict(os.environ, env, clear=True), \
                 patch('plan_reading.china_day', return_value='2026-09-20'), \
                 patch('sys.stdout', new_callable=io.StringIO):
                with self.assertRaisesRegex(SystemExit, '10290 seconds remain'):
                    check_budget(require_target=True)
                checkpoint.data['daily_seconds']['2026-09-20'] = 21600
                checkpoint.save()
                check_budget(require_target=True)
            self.assertTrue(output.read_text().endswith('should_read=false\n'))


if __name__ == '__main__':
    unittest.main()
