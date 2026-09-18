"""Authenticated encryption for reader checkpoints stored in Actions artifacts."""
import json
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class Checkpoint:
    def __init__(self, path, key, source, required=False):
        self.path = Path(path)
        self.cipher = Fernet(key.encode())
        self.data = {
            'version': 1, 'source': source, 'current': None,
            'completed': [], 'daily_seconds': {}, 'storage': None,
        }
        self.restored = self.path.exists()
        if self.restored:
            try:
                data = json.loads(self.cipher.decrypt(self.path.read_bytes()))
            except (InvalidToken, ValueError):
                raise ValueError('Cannot decrypt saved reading state; refusing to reset progress.') from None
            if data.get('version') != 1 or data.get('source') != source:
                raise ValueError('Saved reading state belongs to another folder or version.')
            self.data = data
        elif required:
            raise ValueError('Saved reading state is missing; refusing to select another book.')

    def save(self, storage=None):
        if storage is not None:
            self.data['storage'] = storage
        # Retain enough daily totals for retries, without unbounded growth.
        totals = self.data['daily_seconds']
        self.data['daily_seconds'] = dict(sorted(totals.items())[-14:])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(self.cipher.encrypt(json.dumps(self.data).encode()))
        temporary.chmod(0o600)
        temporary.replace(self.path)

    def add_seconds(self, day, seconds):
        totals = self.data['daily_seconds']
        totals[day] = totals.get(day, 0) + seconds

    def complete(self, book_id):
        if book_id not in self.data['completed']:
            self.data['completed'].append(book_id)
        if self.data['current'] == book_id:
            self.data['current'] = None


def refresh_login_if_changed(state, curl):
    """A new login secret resets only the browser session, never reading progress."""
    fingerprint = hashlib.sha256(curl.encode()).hexdigest()
    if state.get('login_fingerprint') != fingerprint:
        state['storage'] = None
        state['login_fingerprint'] = fingerprint
        return True
    return False
