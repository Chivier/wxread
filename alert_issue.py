"""Keep one GitHub Issue open while interactive WeRead login is required."""
import json
import os
import subprocess

TITLE = '微信读书自动阅读需要重新登录'
MARKER = '<!-- wxread-login-alert-v1 -->'
PUSHPLUS_MARKER = '<!-- wxread-pushplus-accepted-v1 -->'


def dispatch_alert(repo, issue_number):
    comments = api(f'repos/{repo}/issues/{issue_number}/comments?per_page=100')
    if any(PUSHPLUS_MARKER in (comment.get('body') or '') for comment in comments):
        return
    api(f'repos/{repo}/dispatches', 'POST', {
        'event_type': 'wxread_alert',
        'client_payload': {'issue_number': issue_number},
    })


def api(path, method='GET', payload=None):
    command = ['gh', 'api', path]
    if method != 'GET':
        command.extend(['--method', method, '--input', '-'])
    result = subprocess.run(
        command, input=json.dumps(payload).encode() if payload is not None else None,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return json.loads(result.stdout) if result.stdout else None


def open_alerts(repo):
    page = 1
    while True:
        issues = api(f'repos/{repo}/issues?state=open&per_page=100&page={page}')
        for issue in issues:
            if issue.get('title') == TITLE and MARKER in (issue.get('body') or ''):
                yield issue
        if len(issues) < 100:
            return
        page += 1


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    login_required = os.environ.get('LOGIN_REQUIRED', '').lower() == 'true'
    reader_success = os.environ.get('READER_SUCCESS', '').lower() == 'true'
    existing = list(open_alerts(repo))
    if login_required:
        if existing:
            print(f'Login alert already open: #{existing[0]["number"]}.')
            dispatch_alert(repo, existing[0]['number'])
            return
        run_url = f'https://github.com/{repo}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'
        body = (f'{MARKER}\n\n自动阅读检测到微信读书登录失效。请在本人浏览器完成登录，'
                '仅更新仓库 Secret `WXREAD_CURL_BASH`，再运行 `read_num=2` 短测。'
                '请勿在 Issue 中粘贴登录请求、Cookie 或密钥。\n\n'
                f'失败运行：{run_url}\n')
        issue = api(f'repos/{repo}/issues', 'POST', {
            'title': TITLE, 'body': body, 'assignees': [repo.split('/', 1)[0]],
        })
        print(f'Created login alert: #{issue["number"]}.')
        dispatch_alert(repo, issue['number'])
    elif reader_success:
        for issue in existing:
            api(f'repos/{repo}/issues/{issue["number"]}', 'PATCH', {'state': 'closed'})
            print(f'Closed recovered login alert: #{issue["number"]}.')


if __name__ == '__main__':
    main()
