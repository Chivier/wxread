"""Track an incomplete daily reading target without exposing reader state."""
import os

from alert_issue import api, dispatch_alert

TITLE = '微信读书每日阅读目标未达成'
MARKER = '<!-- wxread-target-alert-v1 -->'


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
    target_success = os.environ.get('TARGET_SUCCESS', '').lower() == 'true'
    login_required = os.environ.get('LOGIN_REQUIRED', '').lower() == 'true'
    existing = list(open_alerts(repo))
    if target_success:
        for issue in existing:
            api(f'repos/{repo}/issues/{issue["number"]}', 'PATCH', {'state': 'closed'})
            print(f'Closed recovered daily-target alert: #{issue["number"]}.')
        return
    if login_required:
        print('Login alert covers this incomplete target.')
        return
    if existing:
        print(f'Daily-target alert already open: #{existing[0]["number"]}.')
        dispatch_alert(repo, existing[0]['number'])
        return
    run_url = f'https://github.com/{repo}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'
    body = (f'{MARKER}\n\n微信读书完整运行结束后，最终检查未确认当日目标。'
            '请查看 Actions 的阅读回执、累计秒数与失败步骤。'
            '不要在 Issue 中粘贴 Cookie、登录请求或密钥。\n\n'
            f'失败运行：{run_url}\n')
    issue = api(f'repos/{repo}/issues', 'POST', {
        'title': TITLE, 'body': body, 'assignees': [repo.split('/', 1)[0]],
    })
    print(f'Created daily-target alert: #{issue["number"]}.')
    dispatch_alert(repo, issue['number'])


if __name__ == '__main__':
    main()
