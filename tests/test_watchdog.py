import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import watchdog


class WatchdogTests(unittest.TestCase):
    def test_missing_schedule_alert_opens_once_and_closes_after_recovery(self):
        run = {'created_at': '2026-09-30T00:00:00Z',
               'html_url': 'https://github.com/Chivier/wxread/actions/runs/1'}
        issue = None
        posts = 0

        def fake_api(path, method='GET', payload=None):
            nonlocal run, issue, posts
            if '/runs?' in path:
                return {'workflow_runs': [run]}
            if method == 'GET':
                return [issue] if issue and issue['state'] == 'open' else []
            if method == 'POST':
                posts += 1
                issue = {'number': 5, 'title': payload['title'], 'body': payload['body'], 'state': 'open'}
                return issue
            if method == 'PATCH':
                issue['state'] = payload['state']
                return issue
            raise AssertionError(method)

        with patch.object(watchdog, 'api', side_effect=fake_api), \
             patch.dict(os.environ, {'GITHUB_REPOSITORY': 'Chivier/wxread'}):
            watchdog.main(datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc))
            watchdog.main(datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc))
            self.assertEqual(posts, 1)
            run['created_at'] = '2026-09-30T10:00:00Z'
            watchdog.main(datetime(2026, 9, 30, 11, 0, tzinfo=timezone.utc))
            self.assertEqual(issue['state'], 'closed')


if __name__ == '__main__':
    unittest.main()
