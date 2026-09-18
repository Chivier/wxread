"""Read only books from a configured WeRead shelf folder through its web reader."""
import json
import logging
import os
import re
import shlex
import sys
import time
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ORIGIN = 'https://weread.qq.com'
READ_URL = ORIGIN + '/web/book/read'
EXCLUDED = re.compile(r'三[体體]|three[ -]body', re.IGNORECASE)


def credentials(curl):
    """Parse a captured request as data; never execute the shell command."""
    tokens = shlex.split(curl.replace('\\\n', ' '))
    headers, cookie_string = {}, ''
    for i, token in enumerate(tokens[:-1]):
        if token in ('-H', '--header'):
            key, sep, value = tokens[i + 1].partition(':')
            if sep:
                headers[key.lower()] = value.strip()
        elif token in ('-b', '--cookie'):
            cookie_string = tokens[i + 1]
    cookie_string = cookie_string or headers.get('cookie', '')
    cookies = dict(item.strip().split('=', 1) for item in cookie_string.split(';') if '=' in item)
    if not all(cookies.get(key) for key in ('wr_vid', 'wr_skey')):
        raise ValueError('Missing WeRead login cookies; replace WXREAD_CURL_BASH.')
    return headers, {key: value for key, value in cookies.items() if key.startswith('wr_')}


def folder_url(value):
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.netloc != 'weread.qq.com' or not re.fullmatch(r'/web/shelf/archive/\d+', parsed.path) or parsed.query or parsed.fragment:
        raise ValueError('READ_FOLDER_URL must be a WeRead shelf/archive URL.')
    return value


def eligible_books(links):
    unique = {}
    for link in links:
        url, title = link['url'], link['title'].strip()
        parsed = urlparse(url)
        if parsed.scheme == 'https' and parsed.netloc == 'weread.qq.com' and re.fullmatch(r'/web/reader/[a-zA-Z0-9]+', parsed.path) and title and not EXCLUDED.search(title):
            unique[parsed.path] = {'url': ORIGIN + parsed.path, 'title': title, 'id': parsed.path.rsplit('/', 1)[1]}
    return sorted(unique.values(), key=lambda book: book['id'])


def choose_book(books, state, initial_id=None):
    """Keep the same book across sessions until its end is confirmed."""
    completed = set(state.get('completed', []))
    pending = [book for book in books if book['id'] not in completed]
    current = state.get('current')
    for book in pending:
        if book['id'] == current:
            return book
    if not current and initial_id:
        for book in pending:
            if book['id'] == initial_id:
                return book
    return pending[0] if pending else None


def china_day():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()


class ReadingBudget:
    """Keep the session total across midnight, with a separate daily cap."""
    def __init__(self, state, session_seconds, daily_cap):
        self.state = state
        self.session_seconds = session_seconds
        self.daily_cap = daily_cap
        self.accepted = 0

    def remaining(self, day):
        return max(0, min(self.session_seconds - self.accepted,
                          self.daily_cap - self.state['daily_seconds'].get(day, 0)))

    def record(self, day, seconds):
        self.accepted += seconds
        totals = self.state['daily_seconds']
        totals[day] = totals.get(day, 0) + seconds


def finished_page(page):
    # The website's endingTexts component uses this exact label for a finished
    # book. A disabled Next button, paywall, or ongoing serial is insufficient.
    return page.get_by_text('全书完', exact=True).is_visible()


class ReadResults:
    def __init__(self, book_id):
        self.book_id = book_id
        self.successes = 0
        self.reported_seconds = 0
        self.failures = 0
        self.outside_folder = False

    def record(self, request, response):
        if request.get('b') != self.book_id:
            self.outside_folder = True
            return
        if response.get('succ') == 1 and response.get('synckey') is not None:
            self.successes += 1
            seconds = request.get('rt', 0)
            if isinstance(seconds, (int, float)) and 0 <= seconds <= 120:
                self.reported_seconds += seconds
        else:
            self.failures += 1


def run():
    from playwright.sync_api import sync_playwright
    from reader_state import Checkpoint, refresh_login_if_changed

    source = folder_url(os.environ.get('READ_FOLDER_URL', ''))
    units = os.environ.get('READ_NUM', '').strip()
    session_seconds = int(units) * 30 if units else int(os.environ.get('SESSION_READ_SECONDS') or 7200)
    daily_cap = int(os.environ.get('DAILY_READ_SECONDS') or 21600)
    if not 30 <= session_seconds <= 10800 or not 30 <= daily_cap <= 21600:
        raise ValueError('Session must be 30–10800 seconds; daily target 30–21600 seconds.')
    headers, cookies = credentials(os.environ.get('WXREAD_CURL_BASH', ''))
    folder_name = os.environ.get('READ_FOLDER_NAME', '').strip()
    checkpoint = Checkpoint(
        os.environ.get('READER_STATE_PATH', '.reader-state/checkpoint.enc'),
        os.environ['WXREAD_STATE_KEY'], source,
        required=os.environ.get('REQUIRE_READER_STATE', '').lower() == 'true',
    )
    state = checkpoint.data
    if refresh_login_if_changed(state, os.environ.get('WXREAD_CURL_BASH', '')):
        logging.info('Login configuration changed; replacing browser session while preserving book and totals.')
    budget = ReadingBudget(state, session_seconds, daily_cap)
    logging.info('Checkpoint restored: %s; same book will resume if still in folder.', checkpoint.restored)
    if not budget.remaining(china_day()):
        logging.info('Daily target already reached; no reading started.')
        return
    deadline = time.monotonic() + session_seconds * 1.25 + 180
    total_successes = 0
    all_finished = False
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        options = dict(user_agent=headers.get('user-agent'), locale='zh-CN',
                       timezone_id='Asia/Shanghai', viewport={'width': 1440, 'height': 1000})
        if state.get('storage'):
            options['storage_state'] = state['storage']
        context = browser.new_context(**options)
        # Once saved, use the browser's refreshed session instead of overwriting
        # it with the original, possibly older login request.
        if not state.get('storage'):
            context.add_cookies([{'name': key, 'value': value, 'url': ORIGIN, 'secure': True}
                                 for key, value in cookies.items()])
        page = context.new_page()
        page.set_default_timeout(30000)
        session_verified = False
        try:
            page.goto(source, wait_until='domcontentloaded')
            page.wait_for_timeout(3000)
            heading = page.locator('h1, h2').all_text_contents()
            if folder_name and not any(folder_name in title for title in heading):
                raise RuntimeError('Folder not found or session expired; no reading started.')
            links = page.locator('a[href*="/web/reader/"]').evaluate_all(
                '(links) => links.map(a => ({url: a.href, title: a.textContent.trim()}))'
            )
            session_verified = True
            books = eligible_books(links)
            if not books:
                raise RuntimeError('The selected folder has no eligible books; nothing will be read.')
            logging.info('Folder loaded: %d eligible books.', len(books))
            page.close()
            checkpoint.save(context.storage_state())
            while budget.remaining(china_day()):
                if time.monotonic() >= deadline:
                    raise RuntimeError('Session deadline exceeded before target was acknowledged.')
                book = choose_book(books, state, os.environ.get('READ_INITIAL_BOOK_ID'))
                if book is None:
                    all_finished = True
                    logging.info('All eligible books have reached the end; no books will be reread.')
                    break
                resumed = state['current'] == book['id']
                state['current'] = book['id']
                checkpoint.save(context.storage_state())
                logging.info('Selected book %d; resuming saved book: %s.', books.index(book) + 1, resumed)
                results = ReadResults(book['id'])
                last_success = [time.monotonic()]
                page = context.new_page()
                page.set_default_timeout(30000)

                def record_response(response):
                    if response.url != READ_URL:
                        return
                    before_seconds, before_successes = results.reported_seconds, results.successes
                    try:
                        results.record(response.request.post_data_json, response.json())
                    except Exception:
                        results.failures += 1
                        return
                    if results.successes > before_successes:
                        last_success[0] = time.monotonic()
                        budget.record(china_day(), results.reported_seconds - before_seconds)
                        # Atomic, encrypted checkpoint after every accepted request.
                        checkpoint.save()

                page.on('response', record_response)
                page.goto(book['url'], wait_until='domcontentloaded')
                page.wait_for_timeout(3000)
                next_page = page.get_by_role('button', name='下一页', exact=True)
                if not finished_page(page):
                    next_page.wait_for(state='visible', timeout=45000)
                while budget.remaining(china_day()):
                    if results.outside_folder:
                        raise RuntimeError('Unexpected book in reading request; stopping.')
                    if results.failures >= 3 or time.monotonic() - last_success[0] > 180:
                        raise RuntimeError('Reading requests are failing or no longer acknowledged.')
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Session deadline reached.')
                    if finished_page(page):
                        checkpoint.complete(book['id'])
                        checkpoint.save(context.storage_state())
                        logging.info('End-of-book marker confirmed; next unfinished book can be selected.')
                        break
                    if not next_page.is_visible() or not next_page.is_enabled():
                        raise RuntimeError('Cannot advance and no end-of-book marker is present; book unchanged.')
                    page.wait_for_timeout(30000)
                    # Recheck after the wait, before any further page interaction.
                    if results.outside_folder or results.failures >= 3:
                        raise RuntimeError('Reading verification failed; book unchanged.')
                    if not budget.remaining(china_day()):
                        break
                    next_page.click()
                    page.wait_for_timeout(1000)
                    checkpoint.save(context.storage_state())
                    logging.info('Accepted this session: %gs; today: %gs / %ds; current book unchanged.',
                                 budget.accepted,
                                 state['daily_seconds'].get(china_day(), 0), daily_cap)
                page.wait_for_timeout(1000)
                total_successes += results.successes
                if results.outside_folder:
                    raise RuntimeError('Unexpected book in reading request; stopping.')
                page.close()
                checkpoint.save(context.storage_state())
            accepted = budget.accepted
            if not all_finished and (budget.remaining(china_day()) or total_successes < 1):
                raise RuntimeError('Reading target was not acknowledged; progress was saved for resumption.')
            summary = (f'Session accepted: {accepted:g} seconds; '
                       f'today: {state["daily_seconds"].get(china_day(), 0):g}/{daily_cap} seconds; '
                       f'{total_successes} successful responses. '
                       'Leaderboard/challenge credit has not been independently verified.')
            logging.info(summary)
            if os.environ.get('GITHUB_STEP_SUMMARY'):
                with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
                    output.write(summary + '\n')
        finally:
            checkpoint.save(context.storage_state() if session_verified else None)
            context.close()
            browser.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        run()
    except Exception as error:
        # Browser exceptions can contain URLs and page data; do not dump them to public logs.
        logging.error('Folder reader stopped (%s). No fallback book was used.', type(error).__name__)
        if isinstance(error, (ValueError, RuntimeError)):
            logging.error('%s', error)
        sys.exit(1)
