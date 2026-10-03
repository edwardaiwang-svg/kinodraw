"""Doodle Cloud client: AI-directed videos (free and paid plans) without your own API key.

The server holds the model keys, builds the prompt itself from the structured section
payload, and enforces quotas; the app only ever sees the resulting JSON.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import platformdirs

from ...net import urlopen
from .providers import ProviderError, Usage

URL = os.environ.get('DOODLE_CLOUD_URL', 'https://api.doodlecloud.org')   # the env var points a test build elsewhere
# Cloudflare refuses Python's default "Python-urllib" signature (error 1010), so the app names itself.
USER_AGENT = 'DoodleStudio (+https://github.com/edwardaiwang-svg/doodle-studio)'
INSTALL_ID = Path(platformdirs.user_data_dir('DoodleStudio')) / 'install-id'


def install_id() -> str:
    if not INSTALL_ID.exists():
        INSTALL_ID.parent.mkdir(parents=True, exist_ok=True)
        INSTALL_ID.write_text(uuid.uuid4().hex)
    return INSTALL_ID.read_text().strip()


def _token() -> str | None:
    if os.environ.get('DOODLE_CLOUD_TOKEN'):         # CI / headless machines
        return os.environ['DOODLE_CLOUD_TOKEN']
    try:
        import keyring
        return keyring.get_password('DoodleStudio', 'cloud-token')
    except Exception:  # noqa: BLE001 - no keychain backend
        return None


def _call(path: str, body: dict | None = None, token: str | None = None) -> dict:
    if not URL:
        raise ProviderError('Doodle Cloud is not available in this build yet; use offline mode or your own key')
    req = urllib.request.Request(URL.rstrip('/') + path, method='POST' if body is not None else 'GET',
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT,
                                          **({'Authorization': f'Bearer {token}'} if token else {})})
    try:
        with urlopen(req, timeout=180) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read()).get('error', '')
        except Exception:  # noqa: BLE001
            detail = ''
        raise ProviderError(f'Doodle Cloud {error.code}: {detail or error.reason}') from error
    except urllib.error.URLError as error:
        raise ProviderError(f'Doodle Cloud unreachable: {error.reason}') from error


def signup(email: str) -> dict:
    """Email a 6-digit code to ``email``."""
    return _call('/v1/signup', {'email': email})


def verify(email: str, code: str) -> dict:
    """Exchange the emailed code for a token (kept in the OS keychain)."""
    out = _call('/v1/verify', {'email': email, 'code': code, 'install_id': install_id()})
    import keyring
    from .providers import remember
    keyring.set_password('DoodleStudio', 'cloud-token', out['token'])
    remember('cloud-token')
    return {k: v for k, v in out.items() if k != 'token'}


def me() -> dict:
    return _call('/v1/me', token=_token())


class CloudProvider:
    name, model = 'cloud', 'doodle-cloud'

    def __init__(self):
        self.token = _token()
        if not self.token:
            raise ProviderError('sign in to Doodle Cloud first (Studio > Doodle Cloud, or `kinodraw login`)')
        self.video_id = None

    def open_video(self, sections: int, characters: int) -> dict:
        """Count one video against the plan (the server refuses when the quota is used up)."""
        out = _call('/v1/videos', {'sections': sections, 'characters': characters}, self.token)
        self.video_id = out['video_id']
        return out

    def direct_section(self, payload: dict, usage: Usage) -> dict:
        if not self.video_id:
            raise ProviderError('open_video() first')
        out = _call('/v1/direct', {'video_id': self.video_id, 'section': payload}, self.token)
        u = out.get('usage') or {}
        usage.add(u.get('model', 'doodle-cloud'), u.get('input_tokens', 0), u.get('output_tokens', 0),
                  u.get('cached_tokens', 0), 0.0)       # the plan pays; nothing is billed to you per call
        return out['section']
