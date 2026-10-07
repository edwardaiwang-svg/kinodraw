"""AI errors in plain words: what happened and what you can do, never an exception class name or a key.

``explain(error)`` -> {kind, title, steps, setting, detail}. ``setting`` names the Settings field that fixes it (or
None); ``detail`` is the technical text, with keys and tokens removed, for "Copy details".
"""
from __future__ import annotations

import re

WHO = {'openai': 'OpenAI', 'anthropic': 'Anthropic', 'compat': 'Your OpenAI-compatible server',
       'command': 'Your director command', 'cloud': 'KinoDraw Cloud'}
TRANSIENT = {'rate', 'busy', 'network'}
NETWORK = {'APIConnectionError', 'APITimeoutError', 'TimeoutError', 'ConnectionError', 'URLError', 'TimeoutExpired',
           'ConnectError', 'ReadTimeout', 'ConnectTimeout'}
OFFLINE = 'Or switch the director to Offline in Settings: it needs no account and no internet.'

TITLES = {
    'key': '{who} did not accept your API key',
    'credit': '{who} says your account is out of credit',
    'rate': '{who} is getting too many requests from your account right now',
    'busy': '{who} is busy or having a problem right now',
    'network': 'KinoDraw could not reach {who}',
    'model': '{who} does not know the model you chose',
    'too_big': 'This script is too long for the model to plan in one go',
    'refused': 'The model declined to plan this script',
    'bad_answer': '{who} answered, but not in the JSON format KinoDraw needs',
    'other': 'Something unexpected went wrong while the AI planned this video',
}
STEPS = {
    'key': ['Open Settings and paste your key again: check for missing characters or extra spaces.',
            'Make sure the key belongs to an account that may use this model.', OFFLINE],
    'credit': ["Add credit or a payment method on the provider's billing page, then make the video again.", OFFLINE],
    'rate': ['Wait a minute, then make the video again.',
             "If it keeps happening, check your plan's rate limits with the provider.", OFFLINE],
    'busy': ['KinoDraw tried 3 times. Try again in a few minutes.', OFFLINE],
    'network': ['Check your internet connection (or, for your own server, its address in Settings).',
                'Then make the video again.', OFFLINE],
    'model': ['Check the model name in Settings (for example gpt-6-luna or claude-opus-5).',
              'Make sure your account has access to that model.'],
    'too_big': ['Split the script into shorter videos, or shorten its longest sections.',
                'Or choose a model that takes longer texts.'],
    'refused': ['Reword any part that could read as harmful, then try again.', OFFLINE],
    'bad_answer': ['Make the video again: answers vary from one try to the next.',
                   'With your own server, choose a model that can answer in JSON.', OFFLINE],
    'other': ['Try again.', 'If it keeps happening, use "Feedback or a problem?" and paste the copied details.'],
}
CLOUD_STEPS = {
    402: ['Keep making videos with the Offline director, or add your own OpenAI or Anthropic key in Settings.'],
    429: ['Try again later, or use the Offline director now.'],
    503: ['The Offline director planned this video; try KinoDraw Cloud again later.'],
    401: ['Sign in to KinoDraw Cloud again (Settings > KinoDraw Cloud).', OFFLINE],
}
SETTING = {'key': 'key', 'model': 'model', 'credit': 'director', 'network': 'base_url', 'cloud_limit': 'director'}

_SECRETS = [
    re.compile(r'(?i)\bbearer\s+[\w.\-~+/=]+'),
    re.compile(r'\b(?:sk|pk|rk)-[\w*.\-]{6,}'),                   # OpenAI, Anthropic (sk-ant-), OpenRouter (sk-or-)
    re.compile(r'\bgsk_\w{8,}'),                                  # Groq
    re.compile(r'\bAIza[\w\-]{20,}'),                             # Google
    re.compile(r'\b(?=[A-Za-z_\-]*\d)(?=[\d_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}\b'),   # any other long token
]
_LABELLED = re.compile(r'(?i)\b((?:api[_-]?key|x-api-key|token|authorization|password|secret)["\']?\s*[:=]\s*["\']?)'
                       r'(?!\[redacted\])[^\s"\',;}]+')


def redact(text: str) -> str:
    """``text`` with API keys, bearer tokens and other long secrets replaced by [redacted]."""
    text = str(text)
    for pattern in _SECRETS:
        text = pattern.sub('[redacted]', text)
    return _LABELLED.sub(r'\1[redacted]', text)


def _status(error):
    status = getattr(error, 'status_code', None) or getattr(error, 'status', None)
    return status if isinstance(status, int) else None


def _codes(error) -> str:
    """The machine-readable codes an SDK error carries (OpenAI ``code``/``type``; Anthropic body error type)."""
    body = getattr(error, 'body', None)
    inner = body.get('error') if isinstance(body, dict) else None
    found = [getattr(error, 'code', None), getattr(error, 'type', None),
             *((inner.get('type'), inner.get('code')) if isinstance(inner, dict) else ())]
    return ' '.join(str(c) for c in found if c).lower()


def classify(error) -> str:
    """One of key, credit, rate, busy, network, model, too_big, refused, bad_answer, cloud_limit or other."""
    kind = getattr(error, 'kind', None)
    if kind:
        return kind
    from .providers import StructuredResponseError
    text, codes, status, name = str(error).lower(), _codes(error), _status(error), type(error).__name__
    if isinstance(error, StructuredResponseError):
        return 'too_big' if 'cut off' in text or '(length)' in text else 'bad_answer'
    if getattr(error, 'provider', None) == 'cloud' and getattr(error, 'detail', '') and status in (402, 429, 503):
        return 'cloud_limit'
    if 'insufficient_quota' in codes or 'billing' in codes or 'credit balance' in text or status == 402:
        return 'credit'
    if status in (401, 403) or name in ('AuthenticationError', 'PermissionDeniedError'):
        return 'key'
    if (status == 413 or 'context_length' in codes or 'too_large' in codes or 'prompt is too long' in text
            or 'maximum context length' in text):
        return 'too_big'
    if status == 404 or 'model_not_found' in codes:
        return 'model'
    if status == 429:
        return 'rate'
    if (status or 0) >= 500 or 'overloaded' in codes:
        return 'busy'
    if status == 408 or name in NETWORK or isinstance(error, (TimeoutError, ConnectionError)) or 'unreachable' in text:
        return 'network'
    if 'declined' in text:
        return 'refused'
    return 'other'


def explain(error, provider: str | None = None) -> dict:
    """What happened and what to do, for any exception a director call raised."""
    from .providers import ProviderError
    kind = classify(error)
    who_id = getattr(error, 'provider', None) or provider
    who = WHO.get(who_id, 'The AI service')
    status = _status(error)
    steps = STEPS.get(kind, STEPS['other'])
    if who_id == 'cloud' and getattr(error, 'detail', ''):        # the cloud's own sentence is written for people
        title = f'KinoDraw Cloud: {redact(error.detail)}'
        steps = CLOUD_STEPS.get(status, STEPS['other'])
    elif kind == 'other':
        plain = isinstance(error, (ProviderError, ValueError)) and str(error).strip()
        title = redact(str(error)) if plain else TITLES['other']
    else:
        title = TITLES[kind].format(who=who)
    detail = getattr(error, 'technical', None) or f'{type(error).__name__}: {error}'
    if status and str(status) not in detail:
        detail = f'HTTP {status}. {detail}'
    return {'kind': kind, 'title': title, 'steps': list(steps), 'setting': SETTING.get(kind),
            'detail': redact(detail)[-1000:]}


def message(error, provider: str | None = None) -> str:
    """The title and the first thing to try, as one line."""
    problem = explain(error, provider)
    title = problem['title'].rstrip('. ')
    return f"{title}. {problem['steps'][0]}" if problem['steps'] else title
