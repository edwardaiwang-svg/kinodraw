"""KinoDraw Cloud client: AI-directed videos (free and paid plans) without your own API key.

The server holds the model keys, builds the prompt itself from the structured section
payload, and enforces quotas; the app only ever sees the resulting JSON.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

from ... import paths
from ...net import urlopen
from .providers import ProviderError, Usage

URL = paths.getenv('KINODRAW_CLOUD_URL') or 'https://api.doodlecloud.org'   # the env var points a test build elsewhere
# Cloudflare refuses Python's default "Python-urllib" signature (error 1010), so the app names itself.
USER_AGENT = 'KinoDraw (+https://github.com/edwardaiwang-svg/kinodraw)'
INSTALL_ID = paths.data_dir() / 'install-id'


def install_id() -> str:
    if not INSTALL_ID.exists():
        INSTALL_ID.parent.mkdir(parents=True, exist_ok=True)
        INSTALL_ID.write_text(uuid.uuid4().hex, encoding='utf-8')
    return INSTALL_ID.read_text(encoding='utf-8').strip()


def _token() -> str | None:
    if paths.getenv('KINODRAW_CLOUD_TOKEN'):         # CI / headless machines
        return paths.getenv('KINODRAW_CLOUD_TOKEN')
    try:
        import keyring
        return keyring.get_password(paths.APP, 'cloud-token')
    except Exception:  # noqa: BLE001 - no keychain backend
        return None


class EmailUnavailable(ValueError):
    """KinoDraw Cloud can't send sign-in emails right now (its email provider's limit, for example). The message is the
    plain sentence to show, with the way to go on offline."""


def _call(path: str, body: dict | None = None, token: str | None = None) -> dict:
    if not URL:
        raise ProviderError('KinoDraw Cloud is not available in this build yet; use offline mode or your own key')
    req = urllib.request.Request(URL.rstrip('/') + path, method='POST' if body is not None else 'GET',
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT,
                                          **({'Authorization': f'Bearer {token}'} if token else {})})
    try:
        with urlopen(req, timeout=180) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            reply = json.loads(error.read())
            detail = reply.get('error', '')
        except Exception:  # noqa: BLE001
            reply, detail = {}, ''
        if reply.get('code') == 'email_unavailable' and detail:     # no "KinoDraw Cloud 502:" and no error codes
            raise EmailUnavailable(detail[0].upper() + detail[1:] + '.') from error
        raise ProviderError(f'KinoDraw Cloud {error.code}: {detail or error.reason}') from error
    except urllib.error.URLError as error:
        raise ProviderError(f'KinoDraw Cloud unreachable: {error.reason}') from error


def signup(email: str) -> dict:
    """Email a 6-digit code to ``email``."""
    return _call('/v1/signup', {'email': email})


def verify(email: str, code: str) -> dict:
    """Exchange the emailed code for a token (kept in the OS keychain)."""
    out = _call('/v1/verify', {'email': email, 'code': code, 'install_id': install_id()})
    import keyring
    from .providers import remember
    keyring.set_password(paths.APP, 'cloud-token', out['token'])
    remember('cloud-token')
    return {k: v for k, v in out.items() if k != 'token'}


def me() -> dict:
    return _call('/v1/me', token=_token())


class CloudProvider:
    name, model = 'cloud', 'kinodraw-cloud'
    languages = ('en', 'zh')                          # what the cloud plans; anything else stays offline, unbilled

    def __init__(self):
        self.token = _token()
        if not self.token:
            raise ProviderError('sign in to KinoDraw Cloud first (Studio > KinoDraw Cloud, or `kinodraw login`)')
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
        usage.add(u.get('model', 'kinodraw-cloud'), u.get('input_tokens', 0), u.get('output_tokens', 0),
                  u.get('cached_tokens', 0), 0.0)       # the plan pays; nothing is billed to you per call
        return out['section']

    def pick_style(self, payload: dict, usage: Usage) -> dict:
        """"Choose for me": GPT-6 Luna picks one of ``payload['options']`` (metered against the plan's AI allowance,
        not counted as a video)."""
        out = _call('/v1/style', payload, self.token)
        u = out.get('usage') or {}
        usage.add(u.get('model', 'kinodraw-cloud'), u.get('input_tokens', 0), u.get('output_tokens', 0),
                  u.get('cached_tokens', 0), 0.0)
        pick = out.get('pick') or {}
        if not isinstance(pick.get('style'), str):
            raise ProviderError('KinoDraw Cloud did not name a style')
        return {'style': pick['style'], 'reason': str(pick.get('reason') or '')}
