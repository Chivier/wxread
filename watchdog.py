"""External check for missing scheduled WeRead workflow runs."""
from datetime import datetime, timedelta, timezone
import os

from alert_issue import api, dispatch_alert

TITLE = '微信读书定时任务超过 8 小时未触发'
MARKER = '<!-- wxread-schedule-watchdog-v1 -->'
MAX_AGE = timedelta(hours=8)


def latest_scheduled_run(repo):
    data = api(f'repos/{repo}/actions/workflows/deploy.yml/runs?event=schedule&per_page=1')
    runs = data.get('workflow_runs', [])
    return runs[0] if runs else None


def watchdog_issue(repo):
    issues = api(f'repos/{repo}/issues?state=open&per_page=100')
    return next((issue for issue in issues
                 if issue.get('title') == TITLE and MARKER in (issue.get('body') or '')), None)


def main(now=None):
    repo = os.environ.get('GITHUB_REPOSITORY', 'Chivier/wxread')
    now = now or datetime.now(timezone.utc)
    run = latest_scheduled_run(repo)
    last = datetime.fromisoformat(run['created_at'].replace('Z', '+00:00')) if run else None
    stale = last is None or now - last > MAX_AGE
    issue = watchdog_issue(repo)
    if stale and not issue:
        run_line = f'最近一次计划运行：{run["html_url"]}（{run["created_at"]}）。' if run else '未找到计划运行。'
        body = (f'{MARKER}\n\nGitHub Actions 已超过 8 小时没有触发微信读书计划任务。'
                '请检查 Actions 是否启用、工作流文件与最近运行。此检查由 Artoria 独立执行。\n\n'
                f'{run_line}\n')
        created = api(f'repos/{repo}/issues', 'POST', {
            'title': TITLE, 'body': body, 'assignees': [repo.split('/', 1)[0]],
        })
        print(f'Created missing-schedule alert: #{created["number"]}.')
        dispatch_alert(repo, created['number'])
    elif not stale and issue:
        api(f'repos/{repo}/issues/{issue["number"]}', 'PATCH', {'state': 'closed'})
        print(f'Closed recovered schedule alert: #{issue["number"]}.')
    elif stale and issue:
        dispatch_alert(repo, issue['number'])
        print(f'Schedule status: stale; alert: open (#{issue["number"]}).')
    else:
        print(f'Schedule status: {"stale" if stale else "fresh"}; alert: {"open" if issue else "none"}.')


if __name__ == '__main__':
    main()
