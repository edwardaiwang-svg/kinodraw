import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS

import pytest
from kinodraw.director.llm import cloud, providers
from kinodraw.director.v3.llm import plan_v3
from kinodraw.director.v3.schema import PLAN_SCHEMA

TEXT = '# Lesson\n\nA book holds an idea.'


@pytest.fixture
def server(monkeypatch):
    state = {'requests': [], 'plan': plan_v3(TEXT)[0], 'status': 200}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append((self.path, body, self.headers.get('Authorization')))
            status = state['status']
            if self.headers.get('Authorization') != 'Bearer test-owned':
                status, reply = 401, {'error': 'invalid token'}
            elif status != 200:
                reply = {'error': state.get('error', 'Not Found')}
            elif self.path == '/v3/videos':
                reply = {'video_id': 'owned-video'}
            elif self.path == '/v3/plan':
                if body['video_id'] != 'owned-video':
                    status, reply = 404, {'error': 'unknown video'}
                elif state.get('claimed'):
                    status, reply = 429, {'error': 'already directed'}
                else:
                    state['claimed'] = True
                    reply = {'plan': state['plan'], 'contract_version': 3,
                             'usage': {'model': 'gpt-6-luna', 'input_tokens': 30,
                                       'output_tokens': 10, 'cached_tokens': 2}}
            else:
                status, reply = 404, {'error': 'Not Found'}
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(cloud, 'URL', f'http://127.0.0.1:{http.server_port}')
    monkeypatch.setattr(cloud, '_token', lambda: pytest.fail('read credentials'))
    yield state
    http.shutdown()
    http.server_close()
    thread.join()


def test_real_http_whole_plan_and_usage(server):
    provider = cloud.CloudProvider(token='test-owned')
    plan, report = plan_v3(TEXT, provider)
    assert not report['fallback'] and plan == server['plan']
    assert [r[0] for r in server['requests']] == ['/v3/videos', '/v3/plan']
    opening, request = [r[1] for r in server['requests']]
    assert opening == {'sections': 1, 'characters': len('A book holds an idea.')}
    assert request['video_id'] == 'owned-video'
    assert request['storyboard']['section_ids'] == ['main']
    assert request['storyboard']['beats'][0]['spoken'] == 'A book holds an idea.'
    assert report['usage'].input_tokens == 30 and report['usage'].cached_tokens == 2
    assert report['usage'].cost_usd == 0 and report['usage'].calls == 1
    assert list(plan) == ['storyboard', 'style', 'cast', 'scenes']
    with pytest.raises(providers.ProviderError, match='already directed'):
        provider.direct_plan(request['storyboard'], providers.Usage())


@pytest.mark.parametrize('status,error,reason', [(404, 'Not Found', 'not deployed'),
    (404, 'unknown video', 'unknown video'), (402, 'allowance used', 'allowance used'),
    (503, 'paused', 'paused'), (401, 'invalid token', 'invalid token')])
def test_http_fallback_preserves_errors(server, status, error, reason):
    server.update(status=status, error=error)
    _, report = plan_v3(TEXT, cloud.CloudProvider(token='test-owned'))
    assert report['fallback'] and reason in report['fallback_reason']
    assert len(server['requests']) == 1


def test_http_plan_ownership(server):
    provider = cloud.CloudProvider(token='test-owned')
    provider.video_id = 'someone-elses-video'
    with pytest.raises(providers.ProviderError, match='unknown video'):
        provider.direct_plan({}, providers.Usage())


def openai_fake(answers):
    provider = providers.OpenAIProvider.__new__(providers.OpenAIProvider)
    provider.name, provider.model, provider.strict = 'openai', 'gpt-6-luna', True
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        value = answers.pop(0)
        if isinstance(value, Exception):
            raise value
        return NS(usage=NS(prompt_tokens=100, completion_tokens=20,
                          prompt_tokens_details=NS(cached_tokens=40)),
                  choices=[NS(finish_reason='stop', message=NS(content=value, refusal=None))])
    provider.client = NS(chat=NS(completions=NS(create=create)))
    return provider, calls


def test_byok_schema_root_retry_and_billed_invalid_response():
    valid = plan_v3(TEXT)[0]
    provider, calls = openai_fake(['[]', json.dumps(valid)])
    usage = providers.Usage()
    assert provider.direct_plan({}, usage) == valid
    assert len(calls) == 2 and usage.calls == 2
    assert usage.input_tokens == 120 and usage.cached_tokens == 80
    assert calls[0]['response_format']['json_schema']['schema'] == PLAN_SCHEMA
    assert calls[0]['max_completion_tokens'] == 16000


@pytest.mark.parametrize('kind', ['openai', 'anthropic'])
@pytest.mark.parametrize('metered', [False, True])
@pytest.mark.parametrize('invalid_first', [False, True])
def test_byok_missing_usage_is_unknown_but_explicit_zero_is_known(kind, metered, invalid_first):
    valid = plan_v3(TEXT)[0]
    answers = (['[]'] if invalid_first else []) + [json.dumps(valid)]
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        text = answers.pop(0)
        if kind == 'openai':
            u = NS(prompt_tokens=0, completion_tokens=0, prompt_tokens_details=None) if metered else None
            return NS(usage=u, choices=[NS(finish_reason='stop', message=NS(content=text, refusal=None))])
        u = NS(input_tokens=0, output_tokens=0, cache_creation_input_tokens=0,
               cache_read_input_tokens=0) if metered else None
        return NS(usage=u, stop_reason='end_turn', content=[NS(type='text', text=text)])
    if kind == 'openai':
        provider, _ = openai_fake([])
        provider.client.chat.completions.create = create
    else:
        provider = providers.AnthropicProvider.__new__(providers.AnthropicProvider)
        provider.name, provider.model, provider.effort = 'anthropic', 'claude-opus-5', 'medium'
        provider.client = NS(messages=NS(create=create))
    usage = providers.Usage()
    assert provider.direct_plan({}, usage) == valid
    assert len(calls) == usage.calls == 1 + invalid_first
    assert usage.input_tokens == usage.output_tokens == usage.cached_tokens == 0
    if metered:
        assert usage.cost_usd == 0
    else:
        assert usage.cost_usd is None
    usage.add('gpt-6-luna', 100, 20)
    assert (usage.cost_usd is not None) == metered


def test_byok_permanent_error_not_retried():
    error = RuntimeError('wrong key')
    error.status_code = 401
    provider, calls = openai_fake([error])
    with pytest.raises(providers.ProviderError, match='wrong key'):
        provider.direct_plan({}, providers.Usage())
    assert len(calls) == 1


def test_byok_original_root_never_extracted():
    provider, calls = openai_fake(['[{"storyboard":{}}]', 'prefix {"storyboard":{}}'])
    with pytest.raises(providers.ProviderError):
        provider.direct_plan({}, providers.Usage())
    assert len(calls) == 2


def test_frozen_server_contract_matches_client():
    from pathlib import Path
    from kinodraw.director.v3.prompt import SYSTEM
    contract = json.loads((Path(__file__).resolve().parent / 'fixtures' / 'cloud_contract_v3.json').read_text(
        encoding='utf-8'))
    assert contract['version'] == 3
    assert contract['schema'] == PLAN_SCHEMA and contract['system'] == SYSTEM


def test_compat_json_mode_includes_whole_plan_schema():
    provider, calls = openai_fake([json.dumps(plan_v3(TEXT)[0])])
    provider.name, provider.strict = 'compat', False
    provider.direct_plan({}, providers.Usage())
    assert calls[0]['response_format'] == {'type': 'json_object'}
    assert json.dumps(PLAN_SCHEMA) in calls[0]['messages'][0]['content']


@pytest.mark.parametrize('status,expected_calls', [(429, 2), (503, 2), (400, 1), (403, 1)])
def test_byok_transient_retry_is_bounded(status, expected_calls):
    error = RuntimeError('mock failure')
    error.status_code = status
    provider, calls = openai_fake([error, error])
    with pytest.raises(providers.ProviderError):
        provider.direct_plan({}, providers.Usage())
    assert len(calls) == expected_calls


def test_anthropic_schema_retry_and_cache_billing():
    provider = providers.AnthropicProvider.__new__(providers.AnthropicProvider)
    provider.name, provider.model, provider.effort = 'anthropic', 'claude-opus-5', 'medium'
    answers = ['[]', json.dumps(plan_v3(TEXT)[0])]
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return NS(usage=NS(input_tokens=100, output_tokens=20,
                          cache_creation_input_tokens=10, cache_read_input_tokens=40),
                  stop_reason='end_turn', content=[NS(type='text', text=answers.pop(0))])
    provider.client = NS(messages=NS(create=create))
    usage = providers.Usage()
    provider.direct_plan({}, usage)
    assert len(calls) == usage.calls == 2
    assert calls[0]['output_config']['format']['schema'] == PLAN_SCHEMA
    assert usage.input_tokens == 220 and usage.cached_tokens == 80
    assert usage.cost_usd == pytest.approx(2 * (100*5 + 10*5*1.25 + 40*.5 + 20*25) / 1e6)


def test_byok_refusal_is_billed_without_retry():
    provider, calls = openai_fake([])
    def create(**kwargs):
        calls.append(kwargs)
        return NS(usage=NS(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None),
                  choices=[NS(finish_reason='stop', message=NS(content='', refusal='declined'))])
    provider.client.chat.completions.create = create
    usage = providers.Usage()
    with pytest.raises(providers.ProviderError, match='declined'):
        provider.direct_plan({}, usage)
    assert len(calls) == usage.calls == 1 and usage.cost_usd > 0


def test_real_http_cloud_plan_is_saved_and_reused(server, tmp_path, monkeypatch):
    from kinodraw import pipeline
    project = tmp_path / 'cloud-project'
    pipeline.new_project(TEXT, project, direction={'story': 'story'}, director_v3=True)
    server['plan'] = plan_v3(pipeline.storyboard(project))[0]
    report = pipeline.direct_v3(project, provider=cloud.CloudProvider(token='test-owned'))
    cfg = pipeline.settings(project)
    assert not report['fallback'] and cfg['plan_v3'] == server['plan']
    assert cfg['scene_treatments'] == cfg['plan_v3']['scenes']
    saved = (project / 'project.json').read_bytes()
    monkeypatch.setattr(cloud.CloudProvider, 'direct_plan', lambda *a: pytest.fail('redirected saved plan'))
    pipeline.direct_v3(project, provider=cloud.CloudProvider(token='test-owned'))
    assert (project / 'project.json').read_bytes() == saved


def test_v3_named_cloud_spanish_uses_v3_language_contract(monkeypatch):
    from kinodraw.director.v3 import llm
    seen = []
    def factory(kind, **kwargs):
        seen.append((kind, kwargs))
        return NS(direct_plan=lambda payload, usage: plan_v3('# Lesson\n\nA book.')[0])
    monkeypatch.setattr(llm, 'make_provider', factory)
    llm.plan_v3('# Lección\n\nEl libro es una idea.', 'cloud')
    assert seen == [('cloud', {'lang': None})]


@pytest.mark.parametrize('change', ['version', 'root', 'fields'])
def test_cloud_rejects_invalid_contract_after_recording_usage(server, change):
    if change == 'root':
        server['plan'] = []
    elif change == 'fields':
        server['plan']['extra'] = 'not allowed'
    provider = cloud.CloudProvider(token='test-owned')
    usage = providers.Usage()
    if change == 'version':
        original = provider._send
        def send(path, body):
            reply = original(path, body)
            if path == '/v3/plan':
                reply['contract_version'] = 1
            return reply
        provider._send = send
    with pytest.raises(providers.ProviderError):
        provider.direct_plan({'beats': [{'section_id': 's1', 'text': 'hello', 'spoken': 'hello'}]}, usage)
    assert usage.calls == 1 and usage.output_tokens == 10


def test_sdk_hidden_retries_disabled_only_for_structured_calls():
    provider, calls = openai_fake([json.dumps(plan_v3(TEXT)[0])])
    options = []
    def with_options(**kwargs):
        options.append(kwargs)
        return provider.client
    provider.client.with_options = with_options
    provider.direct_plan({}, providers.Usage())
    assert options == [{'max_retries': 0, 'timeout': 180}]


def test_real_byok_plan_saved_and_reused(tmp_path, monkeypatch):
    from kinodraw import pipeline
    project = tmp_path / 'byok-project'
    pipeline.new_project(TEXT, project, direction={'story': 'story'}, director_v3=True)
    expected = plan_v3(pipeline.storyboard(project))[0]
    provider, calls = openai_fake([json.dumps(expected)])
    report = pipeline.direct_v3(project, provider=provider)
    assert not report['fallback'] and pipeline.settings(project)['plan_v3'] == expected
    assert report['usage']['calls'] == 1
    # The plan request is followed by the weak-match prop request; reuse sends nothing.
    assert [c['response_format']['json_schema']['name'] for c in calls] == ['video_plan', 'svg_prop']
    pipeline.direct_v3(project, provider=provider)
    assert len(calls) == 2
