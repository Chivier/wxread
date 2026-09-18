"""Read only books from a configured WeRead shelf folder through its web reader."""
import json
import logging
import os
import re
import shlex
import sys
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


def choose_book(books, day=None):
    if not books:
        raise ValueError('The selected folder has no eligible books; nothing will be read.')
    day = day or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    return books[day.toordinal() % len(books)]


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

    source = folder_url(os.environ.get('READ_FOLDER_URL', ''))
    read_num = int(os.environ.get('READ_NUM') or 40)
    if not 1 <= read_num <= 100:
        raise ValueError('READ_NUM must be between 1 and 100 (30 seconds per unit).')
    headers, cookies = credentials(os.environ.get('WXREAD_CURL_BASH', ''))
    folder_name = os.environ.get('READ_FOLDER_NAME', '').strip()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=headers.get('user-agent'), locale='zh-CN', timezone_id='Asia/Shanghai',
            viewport={'width': 1440, 'height': 1000},
        )
        context.add_cookies([{'name': key, 'value': value, 'url': ORIGIN, 'secure': True} for key, value in cookies.items()])
        page = context.new_page()
        page.set_default_timeout(30000)
        page.goto(source, wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        heading = page.locator('h1, h2').all_text_contents()
        if folder_name and not any(folder_name in title for title in heading):
            raise RuntimeError('Folder not found or session expired; no reading started.')
        links = page.locator('a[href*="/web/reader/"]').evaluate_all(
            '(links) => links.map(a => ({url: a.href, title: a.textContent.trim()}))'
        )
        books = eligible_books(links)
        book = choose_book(books)
        # Titles and the user's shelf stay out of public Actions logs.
        logging.info('Folder loaded: %d eligible books; selected book %d.', len(books), books.index(book) + 1)
        results = ReadResults(book['id'])

        def record_response(response):
            if response.url != READ_URL:
                return
            try:
                results.record(response.request.post_data_json, response.json())
            except Exception:
                results.failures += 1

        page.on('response', record_response)
        page.goto(book['url'], wait_until='domcontentloaded')
        next_page = page.get_by_role('button', name='下一页', exact=True)
        next_page.wait_for(state='visible', timeout=45000)
        logging.info('Reader ready; starting %d seconds of page reading.', read_num * 30)
        for index in range(read_num):
            page.wait_for_timeout(30000)
            if results.outside_folder:
                raise RuntimeError('Unexpected book in reading request; stopping.')
            if results.failures >= 3:
                raise RuntimeError('Reading API rejected requests; stopping.')
            if index >= 2 and not results.successes:
                raise RuntimeError('No successful reading response after 90 seconds; stopping.')
            if not next_page.is_visible() or not next_page.is_enabled():
                raise RuntimeError('No next page available (end of book or access required); stopping.')
            next_page.click()
            page.wait_for_timeout(1000)
            logging.info('Progress %d/%d; successful responses: %d.', index + 1, read_num, results.successes)
        # Allow any last page-turn request to finish before closing the reader.
        page.wait_for_timeout(3000)
        if results.outside_folder or results.failures or results.successes < 2:
            raise RuntimeError('Reading verification failed; check login and book availability.')
        summary = (f'Folder reading finished: {read_num * 30} seconds elapsed; '
                   f'{results.successes} successful reading responses; '
                   f'{results.reported_seconds:g} seconds reported in accepted requests. '
                   'Leaderboard/challenge credit has not been independently verified.')
        logging.info(summary)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
                output.write(summary + '\n')
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
