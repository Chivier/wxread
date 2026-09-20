"""Skip browser installation when the saved daily target is already reached."""
import os

from folder_reader import china_day, folder_url
from reader_state import Checkpoint


def remaining_today(state, day, cap):
    if not 30 <= cap <= 21600:
        raise ValueError('Daily target must be 30–21600 seconds.')
    return max(0, cap - state['daily_seconds'].get(day, 0))


def main():
    checkpoint = Checkpoint(
        os.environ.get('READER_STATE_PATH', '.reader-state/checkpoint.enc'),
        os.environ['WXREAD_STATE_KEY'], folder_url(os.environ['READ_FOLDER_URL']),
        required=os.environ.get('REQUIRE_READER_STATE', '').lower() == 'true',
    )
    cap = int(os.environ.get('DAILY_READ_SECONDS') or 21600)
    day = china_day()
    remaining = remaining_today(checkpoint.data, day, cap)
    summary = f'Beijing date {day}: {cap - remaining:g}/{cap} seconds recorded; {remaining:g} seconds remaining.'
    print(summary)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write(f'should_read={str(remaining > 0).lower()}\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write(summary + '\n')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Daily budget check failed; refusing to reset or ignore saved progress.') from None
