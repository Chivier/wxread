"""Send a generic issue alert through PushPlus and mark accepted submissions."""
import json
import os
from urllib.request import Request, urlopen

from alert_issue import MARKER as LOGIN_MARKER, PUSHPLUS_MARKER, api
from watchdog import MARKER as SCHEDULE_MARKER

URL = 'https://www.pushplus.plus/send'


def send(token, title, content):
    request = Request(URL, data=json.dumps({
        'token': token, 'title': title, 'content': content, 'template': 'txt',
    }).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=20) as response:
        result = json.load(response)
    if result.get('code') != 200:
        raise RuntimeError(f'PushPlus rejected alert (code {result.get("code")}).')
    print('PushPlus accepted the message; delivery is asynchronous.')


def main():
    token = os.environ.get('PUSHPLUS_TOKEN')
    if not token:
        raise RuntimeError('PUSHPLUS_TOKEN secret is missing.')
    if os.environ.get('TEST_ONLY', '').lower() == 'true':
        send(token, '微信读书告警测试', '这是一条微信读书自动阅读告警通道测试。')
        return
    repo = os.environ['GITHUB_REPOSITORY']
    number = int(os.environ['ISSUE_NUMBER'])
    issue = api(f'repos/{repo}/issues/{number}')
    if issue.get('state') != 'open':
        print('Alert issue is closed; no message sent.')
        return
    body = issue.get('body') or ''
    if LOGIN_MARKER in body:
        title = '微信读书需要重新登录'
    elif SCHEDULE_MARKER in body:
        title = '微信读书定时任务未触发'
    else:
        raise RuntimeError('Issue is not a recognized WeRead alert.')
    comments = api(f'repos/{repo}/issues/{number}/comments?per_page=100')
    if any(PUSHPLUS_MARKER in (comment.get('body') or '') for comment in comments):
        print('PushPlus alert was already accepted for this issue.')
        return
    send(token, title, f'{title}。详情：https://github.com/{repo}/issues/{number}')
    api(f'repos/{repo}/issues/{number}/comments', 'POST', {
        'body': f'{PUSHPLUS_MARKER}\nPushPlus 接口已接收提醒；最终投递由 PushPlus 异步处理。',
    })


if __name__ == '__main__':
    main()
