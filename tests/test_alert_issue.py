import os
import unittest
from unittest.mock import patch

import alert_issue


class AlertIssueTests(unittest.TestCase):
    def test_login_alert_is_created_once_and_closed_after_verified_read(self):
        issue = None
        calls = []

        def fake_api(path, method='GET', payload=None):
            nonlocal issue
            calls.append((path, method))
            if method == 'GET':
                if '/comments?' in path:
                    return []
                return [issue] if issue and issue['state'] == 'open' else []
            if method == 'POST':
                if path.endswith('/dispatches'):
                    self.assertEqual(payload['client_payload']['issue_number'], 42)
                    return None
                issue = {'number': 42, 'title': payload['title'], 'body': payload['body'], 'state': 'open'}
                self.assertNotIn('secret-value', issue['body'])
                self.assertIn('assignees', payload)
                return issue
            if method == 'PATCH':
                issue['state'] = payload['state']
                return issue
            raise AssertionError(method)

        base = {'GITHUB_REPOSITORY': 'Chivier/wxread', 'GITHUB_RUN_ID': '123'}
        with patch.object(alert_issue, 'api', side_effect=fake_api), \
             patch.dict(os.environ, {**base, 'LOGIN_REQUIRED': 'true', 'READER_SUCCESS': 'false'}):
            alert_issue.main()
            alert_issue.main()
        self.assertEqual(sum(path.endswith('/issues') and method == 'POST' for path, method in calls), 1)
        self.assertEqual(sum(path.endswith('/dispatches') for path, _ in calls), 2)
        with patch.object(alert_issue, 'api', side_effect=fake_api), \
             patch.dict(os.environ, {**base, 'LOGIN_REQUIRED': 'false', 'READER_SUCCESS': 'true'}):
            alert_issue.main()
        self.assertEqual(issue['state'], 'closed')


if __name__ == '__main__':
    unittest.main()
