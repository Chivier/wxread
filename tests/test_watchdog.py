import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import watchdog


class WatchdogTests(unittest.TestCase):
    def test_catchup_failure_does_not_suppress_push_alert(self):
        with patch.object(watchdog, 'dispatch_catchup', side_effect=RuntimeError('failed')), \
             patch.object(watchdog, 'dispatch_alert') as alert:
            with self.assertRaises(RuntimeError):
                watchdog.recover_stale('Chivier/wxread', 5)
            alert.assert_called_once_with('Chivier/wxread', 5)

    def test_missing_schedule_alert_opens_once_and_closes_after_recovery(self):
        run = {'created_at': '2026-09-30T00:00:00Z',
               'html_url': 'https://github.com/Chivier/wxread/actions/runs/1'}
        issue = None
        posts = 0
        dispatches = []
        comments = []
        catchups = 0

        def fake_api(path, method='GET', payload=None):
            nonlocal run, issue, posts, catchups
            if '/runs?' in path:
                return {'workflow_runs': [run]}
            if method == 'GET':
                if '/comments?' in path:
                    return comments
                return [issue] if issue and issue['state'] == 'open' else []
            if method == 'POST':
                if path.endswith('/dispatches'):
                    self.assertEqual(payload, {'ref': 'main'})
                    catchups += 1
                    return None
                if path.endswith('/comments'):
                    comments.append(payload)
                    return payload
                posts += 1
                issue = {'number': 5, 'title': payload['title'], 'body': payload['body'], 'state': 'open'}
                return issue
            if method == 'PATCH':
                issue['state'] = payload['state']
                return issue
            raise AssertionError(method)

        with patch.object(watchdog, 'api', side_effect=fake_api), \
             patch.object(watchdog, 'dispatch_alert', side_effect=lambda repo, number: dispatches.append(number)), \
             patch.dict(os.environ, {'GITHUB_REPOSITORY': 'Chivier/wxread'}):
            watchdog.main(datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc))
            watchdog.main(datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc))
            self.assertEqual(posts, 1)
            self.assertEqual(dispatches, [5, 5])
            self.assertEqual(catchups, 1)
            run['created_at'] = '2026-09-30T10:00:00Z'
            watchdog.main(datetime(2026, 9, 30, 11, 0, tzinfo=timezone.utc))
            self.assertEqual(issue['state'], 'closed')


if __name__ == '__main__':
    unittest.main()
