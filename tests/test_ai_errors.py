"""Plain-language AI errors, transient retries with backoff, and lenient JSON for non-strict providers."""
import json
from types import SimpleNamespace as NS

import anthropic
import httpx
import openai
import pytest
from kinodraw.director.llm import errors, providers
from kinodraw.director.v3.llm import plan_v3

TEXT = '# Lesson\n\nA book holds an idea.'
KEY = 'sk-' 'proj-Zx81kQm3Vb7Lp2Nw9Rt4Yh6Js0Df5Gc'       # a made-up key the messages must never repeat (split: no key shape in the source)
REQUEST = httpx.Request('POST', 'https://api.example.test/v1/chat/completions')


def sdk(cls, status, message, body=None):
    return cls(message, response=httpx.Response(status, request=REQUEST), body=body)


def cloud_error(status, sentence):
    error = providers.ProviderError(f'KinoDraw Cloud {status}: {sentence}')
    error.status, error.detail, error.provider = status, sentence, 'cloud'
    return error


# Real SDK exception classes, shaped as the services send them.
CASES = [
    ('key', 'openai', sdk(openai.AuthenticationError, 401,
        f"Error code: 401 - {{'error': {{'message': 'Incorrect API key provided: {KEY}.'}}}}",
        {'message': f'Incorrect API key provided: {KEY}.', 'type': 'invalid_request_error', 'code': 'invalid_api_key'})),
    ('key', 'anthropic', sdk(anthropic.PermissionDeniedError, 403, 'Error code: 403 - permission_error',
        {'type': 'error', 'error': {'type': 'permission_error', 'message': 'Your key cannot use this model.'}})),
    ('credit', 'openai', sdk(openai.RateLimitError, 429, 'Error code: 429 - You exceeded your current quota',
        {'message': 'You exceeded your current quota.', 'type': 'insufficient_quota', 'code': 'insufficient_quota'})),
    ('credit', 'anthropic', sdk(anthropic.BadRequestError, 400,
        'Error code: 400 - Your credit balance is too low to access the Anthropic API.',
        {'type': 'error', 'error': {'type': 'invalid_request_error',
                                    'message': 'Your credit balance is too low to access the Anthropic API.'}})),
    ('rate', 'openai', sdk(openai.RateLimitError, 429, 'Error code: 429 - Rate limit reached',
        {'message': 'Rate limit reached for requests', 'type': 'requests', 'code': 'rate_limit_exceeded'})),
    ('busy', 'anthropic', sdk(anthropic.OverloadedError, 529, 'Error code: 529 - Overloaded',
        {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'Overloaded'}})),
    ('busy', 'openai', sdk(openai.InternalServerError, 503, 'Error code: 503 - The server is overloaded', None)),
    ('network', 'openai', openai.APIConnectionError(request=REQUEST)),
    ('network', 'compat', openai.APITimeoutError(request=REQUEST)),
    ('model', 'compat', sdk(openai.NotFoundError, 404, 'Error code: 404 - The model `gpt-9` does not exist',
        {'message': 'The model `gpt-9` does not exist', 'type': 'invalid_request_error', 'code': 'model_not_found'})),
    ('too_big', 'openai', sdk(openai.BadRequestError, 400, "Error code: 400 - This model's maximum context length is",
        {'message': "This model's maximum context length is 128000 tokens.", 'code': 'context_length_exceeded'})),
    ('too_big', 'anthropic', sdk(anthropic.RequestTooLargeError, 413, 'Error code: 413 - request_too_large',
        {'type': 'error', 'error': {'type': 'request_too_large', 'message': 'Request exceeds the maximum size'}})),
]


def failing_openai(name, error):
    """An OpenAI-shaped provider whose one call raises ``error``, so the real _api_failure path is used."""
    provider = providers.OpenAIProvider.__new__(providers.OpenAIProvider)
    provider.name, provider.model, provider.strict = name, 'gpt-6-luna', name != 'compat'
    def create(**kwargs):
        raise error
    provider.client = NS(chat=NS(completions=NS(create=create)))
    return provider


def failing_anthropic(error):
    provider = providers.AnthropicProvider.__new__(providers.AnthropicProvider)
    provider.name, provider.model, provider.effort = 'anthropic', 'claude-opus-5', 'medium'
    def create(**kwargs):
        raise error
    provider.client = NS(messages=NS(create=create))
    return provider


@pytest.mark.parametrize('kind,name,error', CASES, ids=[f'{k}-{n}-{type(e).__name__}' for k, n, e in CASES])
def test_sdk_errors_are_explained_in_plain_words_without_class_names_or_keys(kind, name, error, monkeypatch):
    monkeypatch.setattr(providers, '_sleep', lambda seconds: None)
    provider = failing_anthropic(error) if name == 'anthropic' else failing_openai(name, error)
    with pytest.raises(providers.ProviderError) as failure:
        provider.direct_plan({}, providers.Usage())
    for problem in (errors.explain(failure.value), errors.explain(error, name)):
        assert problem['kind'] == kind
        assert problem['steps'] and all(s.strip() for s in problem['steps'])
        shown = ' '.join([problem['title'], *problem['steps']])
        for word in (type(error).__name__, 'ProviderError', 'Error code', 'Traceback'):
            assert word not in shown
        assert KEY not in json.dumps(problem) and 'Zx81kQm3' not in json.dumps(problem)
    assert type(error).__name__ not in str(failure.value) and KEY not in str(failure.value)
    assert failure.value.kind == kind and failure.value.transient == (kind in ('rate', 'busy', 'network'))


def test_refusal_bad_answer_and_cloud_limits_have_their_own_kinds():
    refused = providers.ProviderError('openai: the model declined the request')
    assert errors.explain(refused, 'openai')['kind'] == 'refused'
    bad = providers.StructuredResponseError('the answer was not valid JSON')
    assert errors.explain(bad, 'compat')['kind'] == 'bad_answer'
    for status, sentence in [(402, "this month's AI allowance is used up: videos use offline mode until the month resets"),
                             (503, "today's AI budget is used up; this video will use offline mode"),
                             (429, "today's video limit is reached: try again tomorrow, or use offline mode")]:
        problem = errors.explain(cloud_error(status, sentence))
        assert problem['kind'] == 'cloud_limit' and sentence in problem['title']
        assert 'Offline' in ' '.join(problem['steps'])


def test_secrets_are_redacted_from_details():
    text = (f'Incorrect API key provided: {KEY}; Authorization: Bearer abc.def-123; '
            'sk-' 'ant-api03-AbCdEf0123456789xyz; gsk_0123456789abcdefABCDEF; api_key=hunter2hunter2')
    clean = errors.redact(text)
    for secret in (KEY, 'abc.def-123', 'sk-' 'ant-api03', 'gsk_0123456789', 'hunter2'):
        assert secret not in clean
    assert 'Incorrect API key provided' in clean


def fake_openai(name, answers):
    provider = providers.OpenAIProvider.__new__(providers.OpenAIProvider)
    provider.name, provider.model, provider.strict = name, 'gpt-6-luna', name != 'compat'
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        value = answers.pop(0)
        if isinstance(value, Exception):
            raise value
        return NS(model=provider.model, usage=NS(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None),
                  choices=[NS(finish_reason='stop', message=NS(content=value, refusal=None))])
    provider.client = NS(chat=NS(completions=NS(create=create)))
    return provider, calls


def test_two_busy_replies_then_success_backs_off_1_5_then_4_seconds(monkeypatch):
    slept = []
    monkeypatch.setattr(providers, '_sleep', slept.append)
    valid = plan_v3(TEXT)[0]
    busy = [sdk(openai.InternalServerError, 503, 'Error code: 503 - busy', None) for _ in range(2)]
    provider, calls = fake_openai('openai', [*busy, json.dumps(valid)])
    assert provider.direct_plan({}, providers.Usage()) == valid
    assert slept == [1.5, 4.0] and len(calls) == 3


def test_transient_failures_stop_after_three_attempts_and_permanent_ones_after_one(monkeypatch):
    slept = []
    monkeypatch.setattr(providers, '_sleep', slept.append)
    busy = [sdk(openai.InternalServerError, 503, 'Error code: 503 - busy', None) for _ in range(3)]
    provider, calls = fake_openai('openai', busy)
    with pytest.raises(providers.ProviderError) as failure:
        provider.direct_plan({}, providers.Usage())
    assert len(calls) == 3 and slept == [1.5, 4.0] and failure.value.kind == 'busy'
    slept.clear()
    for _kind, name, error in CASES:
        if _kind in ('key', 'credit', 'model', 'too_big') and name != 'anthropic':
            provider, calls = fake_openai(name, [error])
            with pytest.raises(providers.ProviderError):
                provider.direct_plan({}, providers.Usage())
            assert len(calls) == 1
    assert slept == []


FENCED = '```json\n{"title": "Sales", "sections": [{"heading": "Change", "paragraphs": ["Sales rose 12%."],' \
         ' "source_notes": [0],},],}\n```'
DRAFT = {'title': 'Sales', 'sections': [{'heading': 'Change', 'paragraphs': ['Sales rose 12%.'], 'source_notes': [0]}]}


def test_compat_reads_a_fenced_answer_with_trailing_commas_but_strict_openai_does_not(monkeypatch):
    monkeypatch.setattr(providers, '_sleep', lambda seconds: None)
    provider, calls = fake_openai('compat', [FENCED])
    assert provider.write_draft({}, providers.Usage()) == DRAFT and len(calls) == 1
    provider, calls = fake_openai('openai', [FENCED, FENCED])
    with pytest.raises(providers.StructuredResponseError):
        provider.write_draft({}, providers.Usage())
    assert len(calls) == 2


@pytest.mark.parametrize('text', [
    'Here is the plan:\n{"a": "b, }", "c": [1, 2,],}\nHope this helps {:)}',
    '```\n{"a": "b, }", "c": [1, 2]}\n```',
    '{"a": "b, }", "c": [1, 2]}'])
def test_lenient_json_keeps_string_contents(text):
    assert providers.loads(text, lenient=True) == {'a': 'b, }', 'c': [1, 2]}


def test_lenient_json_still_needs_the_schema():
    with pytest.raises(providers.StructuredResponseError):
        providers.loads('no object here', lenient=True)
    provider, _ = fake_openai('compat', ['```json\n{"title": "x",}\n```'] * 2)
    with pytest.raises(providers.StructuredResponseError):
        provider.write_draft({}, providers.Usage())


def test_v3_fallback_reason_is_plain_and_keyless(monkeypatch):
    monkeypatch.setattr(providers, '_sleep', lambda seconds: None)
    provider = failing_openai('openai', CASES[0][2])
    _, report = plan_v3(TEXT, provider)
    assert report['fallback'] and report['fallback_help']['kind'] == 'key'
    assert 'AuthenticationError' not in report['fallback_reason'] and 'ProviderError' not in report['fallback_reason']
    assert 'did not accept your API key' in report['fallback_reason']
    assert KEY not in json.dumps(report, default=str)


def test_studio_job_failure_says_what_to_do(monkeypatch):
    from kinodraw.studio import server
    monkeypatch.setattr(providers, '_sleep', lambda seconds: None)
    with pytest.raises(providers.ProviderError) as failure:
        failing_openai('openai', CASES[2][2]).direct_plan({}, providers.Usage())
    text = server._plain(failure.value)
    assert 'out of credit' in text and 'RateLimitError' not in text and 'ProviderError' not in text
    assert server._help(failure.value)['kind'] == 'credit'
    assert server._help(RuntimeError('a bug')) is None
