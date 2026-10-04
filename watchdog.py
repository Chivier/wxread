"""External check for missing scheduled WeRead workflow runs."""
from datetime import datetime, timedelta, timezone
import os

from alert_issue import api, dispatch_alert

TITLE = '微信读书定时任务超过 12 小时未触发'
MARKER = '<!-- wxread-schedule-watchdog-v1 -->'
CATCHUP_MARKER = '<!-- wxread-schedule-catchup-dispatched-v1 -->'
# GitHub routinely delays or drops single schedules; gaps of 9–11 hours occur
# while the daily target is still met, so only a longer silence is an incident.
MAX_AGE = timedelta(hours=12)


def latest_scheduled_run(repo):
    data = api(f'repos/{repo}/actions/workflows/deploy.yml/runs?event=schedule&per_page=1')
    runs = data.get('workflow_runs', [])
    return runs[0] if runs else None


def watchdog_issue(repo):
    issues = api(f'repos/{repo}/issues?state=open&per_page=100')
    return next((issue for issue in issues
                 if issue.get('title') == TITLE and MARKER in (issue.get('body') or '')), None)


def dispatch_catchup(repo, issue_number):
    comments = api(f'repos/{repo}/issues/{issue_number}/comments?per_page=100')
    if any(CATCHUP_MARKER in (comment.get('body') or '') for comment in comments):
        return
    api(f'repos/{repo}/actions/workflows/deploy.yml/dispatches', 'POST', {'ref': 'main'})
    api(f'repos/{repo}/issues/{issue_number}/comments', 'POST', {
        'body': f'{CATCHUP_MARKER}\n已触发一次完整补跑；每日阅读上限和串行锁仍由工作流控制。',
    })
    print('Dispatched one catch-up workflow run.')


def recover_stale(repo, issue_number):
    errors = []
    for action in (dispatch_catchup, dispatch_alert):
        try:
            action(repo, issue_number)
        except Exception as exc:
            print(f'{getattr(action, "__name__", "watchdog action")} failed; will retry on next watchdog run.')
            errors.append(exc)
    if errors:
        raise errors[0]


def main(now=None):
    repo = os.environ.get('GITHUB_REPOSITORY', 'Chivier/wxread')
    now = now or datetime.now(timezone.utc)
    run = latest_scheduled_run(repo)
    last = datetime.fromisoformat(run['created_at'].replace('Z', '+00:00')) if run else None
    stale = last is None or now - last > MAX_AGE
    issue = watchdog_issue(repo)
    if stale and not issue:
        run_line = f'最近一次计划运行：{run["html_url"]}（{run["created_at"]}）。' if run else '未找到计划运行。'
        body = (f'{MARKER}\n\nGitHub Actions 已超过 12 小时没有触发微信读书计划任务。'
                '请检查 Actions 是否启用、工作流文件与最近运行。此检查由 Artoria 独立执行。\n\n'
                f'{run_line}\n')
        created = api(f'repos/{repo}/issues', 'POST', {
            'title': TITLE, 'body': body, 'assignees': [repo.split('/', 1)[0]],
        })
        print(f'Created missing-schedule alert: #{created["number"]}.')
        recover_stale(repo, created['number'])
    elif not stale and issue:
        api(f'repos/{repo}/issues/{issue["number"]}', 'PATCH', {'state': 'closed'})
        print(f'Closed recovered schedule alert: #{issue["number"]}.')
    elif stale and issue:
        recover_stale(repo, issue['number'])
        print(f'Schedule status: stale; alert: open (#{issue["number"]}).')
    else:
        print(f'Schedule status: {"stale" if stale else "fresh"}; alert: {"open" if issue else "none"}.')


if __name__ == '__main__':
    main()
