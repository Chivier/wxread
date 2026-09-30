import os
import unittest
from unittest.mock import patch

import notify_pushplus
from alert_issue import MARKER, PUSHPLUS_MARKER


class NotifyPushPlusTests(unittest.TestCase):
    def test_send_once_and_mark_accepted(self):
        comments = []
        calls = []

        def fake_api(path, method='GET', payload=None):
            if path.endswith('/issues/7'):
                return {'state': 'open', 'body': MARKER}
            if '/comments?' in path:
                return comments
            if path.endswith('/comments') and method == 'POST':
                comments.append(payload)
                return payload
            raise AssertionError(path)

        env = {'PUSHPLUS_TOKEN': 'test-token', 'GITHUB_REPOSITORY': 'Chivier/wxread',
               'ISSUE_NUMBER': '7', 'TEST_ONLY': 'false'}
        with patch.dict(os.environ, env), patch.object(notify_pushplus, 'api', side_effect=fake_api), \
             patch.object(notify_pushplus, 'send', side_effect=lambda *args: calls.append(args)):
            notify_pushplus.main()
            notify_pushplus.main()
        self.assertEqual(len(calls), 1)
        self.assertIn(PUSHPLUS_MARKER, comments[0]['body'])

    def test_closed_alert_does_not_send(self):
        with patch.dict(os.environ, {'PUSHPLUS_TOKEN': 'test-token',
                                      'GITHUB_REPOSITORY': 'Chivier/wxread', 'ISSUE_NUMBER': '7',
                                      'TEST_ONLY': 'false'}), \
             patch.object(notify_pushplus, 'api', return_value={'state': 'closed'}), \
             patch.object(notify_pushplus, 'send') as send:
            notify_pushplus.main()
            send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
