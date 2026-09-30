import os
import unittest
from unittest.mock import patch

import alert_target


class TargetAlertTests(unittest.TestCase):
    def test_failed_target_alert_is_idempotent_and_closes_after_success(self):
        issue = None
        dispatches = []

        def fake_api(path, method='GET', payload=None):
            nonlocal issue
            if method == 'GET':
                return [issue] if issue and issue['state'] == 'open' else []
            if method == 'POST':
                issue = {'number': 8, 'title': payload['title'], 'body': payload['body'], 'state': 'open'}
                self.assertNotIn('credential', issue['body'])
                return issue
            if method == 'PATCH':
                issue['state'] = payload['state']
                return issue
            raise AssertionError(method)

        base = {'GITHUB_REPOSITORY': 'Chivier/wxread', 'GITHUB_RUN_ID': '123',
                'TARGET_SUCCESS': 'false', 'LOGIN_REQUIRED': 'false'}
        with patch.object(alert_target, 'api', side_effect=fake_api), \
             patch.object(alert_target, 'dispatch_alert', side_effect=lambda repo, number: dispatches.append(number)), \
             patch.dict(os.environ, base):
            alert_target.main()
            alert_target.main()
            self.assertEqual(dispatches, [8, 8])
            self.assertEqual(issue['state'], 'open')
            os.environ['TARGET_SUCCESS'] = 'true'
            alert_target.main()
            self.assertEqual(issue['state'], 'closed')

    def test_login_failure_uses_login_alert(self):
        with patch.object(alert_target, 'api', return_value=[]), \
             patch.object(alert_target, 'dispatch_alert') as dispatch, \
             patch.dict(os.environ, {'GITHUB_REPOSITORY': 'Chivier/wxread',
                                      'TARGET_SUCCESS': 'false', 'LOGIN_REQUIRED': 'true'}):
            alert_target.main()
            dispatch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
