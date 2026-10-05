"""KinoDraw Cloud client: AI-directed videos (free and paid plans) without your own API key.

The server holds the model keys, builds the prompt itself from the structured section
payload, and enforces quotas; the app only ever sees the resulting JSON. Without an email
sign-in, the app asks for an anonymous token for this installation (/v1/anonymous) while the
cloud's open access is on.
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


def kept_install_id() -> str | None:
    """The ID, only if KinoDraw Cloud was ever used here (shown so its data can be deleted); never makes one."""
    return INSTALL_ID.read_text(encoding='utf-8').strip() if INSTALL_ID.exists() else None


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


ANON_KEY = 'cloud-anon-token'      # its own keychain entry: "Signed in" stays for email sign-ins only
SIGN_IN = 'sign in to KinoDraw Cloud first (Studio > KinoDraw Cloud, or `kinodraw login`)'
_anon_token: str | None = None     # kept for the process too, for when the keychain can't hold it


class SignInNeeded(ProviderError, ValueError):
    """KinoDraw Cloud wants an email sign-in (its open access is off). ``sentence`` is the server's own, if it sent one."""

    def __init__(self, sentence: str | None = None):
        super().__init__(sentence or SIGN_IN)
        self.sentence = sentence


def anonymous() -> dict:
    """The plan of the anonymous token (asking for one if there is none), for the Studio; never the token itself."""
    token = _kept_anonymous()
    if token:
        try:
            return _call('/v1/me', token=token) | {'anonymous': True}
        except ProviderError as error:
            if getattr(error, 'status', None) != 401:
                raise
            forget_anonymous()      # another cloud's token, a revoked one, or open access ended: ask once for a new one
    return {k: v for k, v in _issue_anonymous().items() if k != 'token'} | {'anonymous': True}


def forget_anonymous():
    global _anon_token
    _anon_token = None
    try:
        import keyring
        keyring.delete_password(paths.APP, ANON_KEY)
    except Exception:  # noqa: BLE001 - nothing saved, or no keychain backend
        pass


def _kept_anonymous() -> str | None:
    if _anon_token:
        return _anon_token
    try:
        import keyring
        return keyring.get_password(paths.APP, ANON_KEY)
    except Exception:  # noqa: BLE001 - no keychain backend
        return None


def _issue_anonymous() -> dict:
    global _anon_token
    try:
        out = _call('/v1/anonymous', {'install_id': install_id()})
    except ProviderError as error:
        status = getattr(error, 'status', None)
        if status in (403, 404):                     # open access off, or a server from before it (its 404 says nothing)
            raise SignInNeeded(error.detail if status == 403 else None) from error
        raise
    _anon_token = out['token']
    try:
        import keyring
        keyring.set_password(paths.APP, ANON_KEY, _anon_token)
    except Exception:  # noqa: BLE001 - no keychain backend: this process keeps it
        pass
    return out


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
        failure = ProviderError(f'KinoDraw Cloud {error.code}: {detail or error.reason}')
        failure.status, failure.detail = error.code, detail
        raise failure from error
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


def feedback(body: dict) -> dict:
    """Send what the user wrote in the Studio's feedback form. No token: feedback needs no account, even Offline."""
    return _call('/v1/feedback', body)


class CloudProvider:
    name, model = 'cloud', 'kinodraw-cloud'
    languages = ('en', 'zh')                          # what the cloud plans; anything else stays offline, unbilled

    def __init__(self, lang: str | None = None):
        self.token, self.anonymous, self.refused = _token(), False, None     # an email sign-in always wins
        self.renewable = False                     # a kept anonymous token the cloud refuses gets one new one
        if not self.token and lang not in (None, *self.languages):    # a language it never plans: no token asked
            self.refused = ProviderError('KinoDraw Cloud plans English and Chinese videos only')   # for, no ID made
        elif not self.token:
            kept = _kept_anonymous()
            self.anonymous, self.renewable = True, bool(kept)
            try:
                self.token = kept or _issue_anonymous()['token']    # SignInNeeded goes up, as 0.2.0's sign-in did
            except SignInNeeded:
                raise
            except ProviderError as error:         # throttled or unreachable: this video is planned offline
                self.refused = error
        self.video_id = None

    def open_video(self, sections: int, characters: int) -> dict:
        """Count one video against the plan (the server refuses when the quota is used up)."""
        out = self._send('/v1/videos', {'sections': sections, 'characters': characters})
        self.video_id = out['video_id']
        return out

    def _send(self, path: str, body: dict) -> dict:
        if not self.token:
            raise self.refused
        try:
            return _call(path, body, self.token)
        except ProviderError as error:
            if not (self.anonymous and getattr(error, 'status', None) == 401):
                raise
            forget_anonymous()
            if self.renewable:                     # a kept token this cloud doesn't know (another cloud's, or revoked):
                self.renewable = False             # ask once for a new one, then send again
                try:
                    self.token = _issue_anonymous()['token']
                except ProviderError as refused:   # open access is off (SignInNeeded), throttled or unreachable
                    self.token, self.refused = None, refused
                    raise
                return self._send(path, body)
            self.token, self.refused = None, SignInNeeded(error.detail)     # open access ended: the rest stays offline
            raise self.refused from error

    def direct_section(self, payload: dict, usage: Usage) -> dict:
        if not self.video_id:
            raise ProviderError('open_video() first')
        out = self._send('/v1/direct', {'video_id': self.video_id, 'section': payload})
        u = out.get('usage') or {}
        usage.add(u.get('model', 'kinodraw-cloud'), u.get('input_tokens', 0), u.get('output_tokens', 0),
                  u.get('cached_tokens', 0), 0.0)       # the plan pays; nothing is billed to you per call
        return out['section']

    def pick_style(self, payload: dict, usage: Usage) -> dict:
        """"Choose for me": GPT-6 Luna picks one of ``payload['options']`` (metered against the plan's AI allowance,
        not counted as a video)."""
        out = self._send('/v1/style', payload)
        u = out.get('usage') or {}
        usage.add(u.get('model', 'kinodraw-cloud'), u.get('input_tokens', 0), u.get('output_tokens', 0),
                  u.get('cached_tokens', 0), 0.0)
        pick = out.get('pick') or {}
        if not isinstance(pick.get('style'), str):
            raise ProviderError('KinoDraw Cloud did not name a style')
        return {'style': pick['style'], 'reason': str(pick.get('reason') or '')}
