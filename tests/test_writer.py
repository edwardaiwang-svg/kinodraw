import json
import sys

import pytest
from kinodraw import ingest, writer
from kinodraw.director.llm import providers
from kinodraw.director.llm.providers import ProviderError, Usage


def test_grounded_writer_injected_provider():
    class Provider:
        def write_draft(self, payload, usage):
            assert payload['notes'] == ['Sales rose 12% in 2025.']
            usage.add('gpt-6-luna', 100, 20)
            return {'title': 'Sales', 'sections': [{'heading': 'Change',
                    'paragraphs': ['Sales rose 12% in 2025.'], 'source_notes': [0]}]}
    draft, report = writer.write_draft('Sales', ['Sales rose 12% in 2025.'], Provider())
    assert '12%' in writer.draft_markdown(draft)
    assert report['usage'].calls == 1


def test_writer_rejects_invented_chart_number():
    class Provider:
        def write_draft(self, payload, usage):
            return {'title': 'Sales', 'sections': [{'heading': 'Chart',
                    'paragraphs': ['Sales rose 99%.'], 'source_notes': [0]}]}
    with pytest.raises(ProviderError, match='number') as failure:
        writer.write_draft('Sales', ['Sales rose 12%.'], Provider())
    assert failure.value.usage.calls == 0


def test_writer_requires_notes_and_injection():
    with pytest.raises(ValueError):
        writer.write_draft('Topic', [], object())


@pytest.mark.parametrize('refs,paragraphs', [([1], ['A sourced claim.']),
    ([], ['A sourced claim.']), ([0], []), ([0], ['It rose 99%.'])])
def test_writer_requires_valid_citations_and_cited_numbers(refs, paragraphs):
    class Provider:
        def write_draft(self, payload, usage):
            return {'title': 'Draft', 'sections': [{'heading': 'Change',
                    'paragraphs': paragraphs, 'source_notes': refs}]}
    with pytest.raises(ProviderError):
        writer.write_draft('Topic', ['It rose 12%.'], Provider())


def test_writer_local_voice_and_original_shape():
    class Provider:
        def write_draft(self, payload, usage):
            assert payload['voice'] == 'Short sentences.'
            return [{'title': 'wrong root'}]
    with pytest.raises(ProviderError):
        writer.write_draft('Topic', ['A sourced note.'], Provider(), voice='Short sentences.')


@pytest.fixture
def command_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, 'api_key', lambda *args: pytest.fail('read credentials'))
    tool = tmp_path / 'writer_command.py'
    answers = tmp_path / 'answers.json'
    log = tmp_path / 'requests.jsonl'
    tool.write_text('''import json, sys
from pathlib import Path
sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
request = json.load(sys.stdin)
answers, log = map(Path, sys.argv[1:3])
attempt = len(log.read_text(encoding='utf-8').splitlines()) if log.exists() else 0
with log.open('a', encoding='utf-8') as stream:
    stream.write(json.dumps(request, ensure_ascii=False) + '\\n')
if int(sys.argv[3]):
    sys.exit(int(sys.argv[3]))
print(json.loads(answers.read_text(encoding='utf-8'))[attempt])
''', encoding='utf-8')

    def make(replies, returncode=0, *, env_model=False):
        answers.write_text(json.dumps(replies, ensure_ascii=False), encoding='utf-8')
        command = f'"{sys.executable}" "{tool}" "{answers}" "{log}" {returncode}'
        if env_model:
            monkeypatch.setenv('KINODRAW_DIRECTOR_COMMAND', command)
            provider = providers.make_provider('command', model='writer-test')
        else:
            provider = providers.CommandProvider('writer-test', command=command, timeout=10)
        return provider, log
    return make


def command_draft():
    return {'title': '销量', 'sections': [{'heading': '变化',
            'paragraphs': ['销量增长12%。'], 'source_notes': [0]}]}


@pytest.mark.parametrize('field,text', [('title', '销量99%'), ('heading', '增长99%'),
    ('paragraphs', '销量增长99%。'), ('paragraphs', '共99人。'), ('paragraphs', '增长99.5%。')])
def test_command_writer_rejects_chinese_uncited_numbers(command_writer, field, text):
    draft = command_draft()
    if field == 'title':
        draft[field] = text
    else:
        draft['sections'][0][field] = [text] if field == 'paragraphs' else text
    provider, log = command_writer([json.dumps(draft, ensure_ascii=False)])
    with pytest.raises(ProviderError, match='number') as failure:
        writer.write_draft('销量', ['销量增长12%。'], provider)
    assert failure.value.usage.calls == 1 and failure.value.usage.cost_usd is None
    assert len(log.read_text(encoding='utf-8').splitlines()) == 1


def test_command_writer_explicit_env_and_model_without_keychain(command_writer):
    expected = command_draft()
    provider, log = command_writer([json.dumps(expected, ensure_ascii=False)], env_model=True)
    draft, report = writer.write_draft('销量', ['销量增长12%。'], provider)
    assert draft == expected and report['usage'].cost_usd is None
    request, = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert request['model'] == 'writer-test' and request['schema'] == writer.WRITER_SCHEMA


def test_command_writer_real_stdin_and_editable_markdown(command_writer):
    expected = command_draft()
    provider, log = command_writer([json.dumps(expected, ensure_ascii=False)])
    draft, report = writer.write_draft('销量', ['销量增长12%。'], provider, voice='短句。')
    assert draft == expected and report['provider'] == 'command'
    usage = report['usage']
    assert usage.calls == 1 and usage.cost_usd is None
    assert usage.input_tokens == usage.output_tokens == usage.cached_tokens == 0
    assert usage.by_model == {'command:writer-test': 1}
    request, = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
    assert set(request) == {'model', 'system', 'user', 'schema'}
    assert request['model'] == 'writer-test' and request['system'] == writer.WRITER_SYSTEM
    assert request['schema'] == writer.WRITER_SCHEMA
    assert json.loads(request['user']) == {'topic': '销量', 'notes': ['销量增长12%。'], 'voice': '短句。'}
    document = ingest.read(writer.draft_markdown(draft))
    assert document.title == '销量' and document.lang == 'zh'
    assert '销量增长12%。' in document.preamble + [p for s in document.sections for p in s.paragraphs]


def test_command_writer_structured_retry_preserves_usage(command_writer):
    expected = command_draft()
    provider, log = command_writer(['[]', json.dumps(expected)])
    draft, report = writer.write_draft('销量', ['销量增长12%。'], provider)
    assert draft == expected and report['usage'].calls == 2
    assert report['usage'].cost_usd is None
    assert len(log.read_text(encoding='utf-8').splitlines()) == 2


@pytest.mark.parametrize('bad', ['not JSON', json.dumps([command_draft()]),
    'prefix ' + json.dumps(command_draft()), json.dumps({**command_draft(), 'extra': True}),
    json.dumps({'title': '销量', 'sections': [{'heading': '变化',
                'paragraphs': ['销量增长12%。'], 'source_notes': [False]}]})])
def test_command_writer_original_json_and_strict_schema_bounded(command_writer, bad):
    provider, log = command_writer([bad, bad, json.dumps(command_draft())])
    with pytest.raises(ProviderError) as failure:
        writer.write_draft('销量', ['销量增长12%。'], provider)
    assert failure.value.usage.calls == 2 and failure.value.usage.cost_usd is None
    assert len(log.read_text(encoding='utf-8').splitlines()) == 2


def test_command_writer_failed_process_is_not_retried(command_writer):
    provider, log = command_writer([], returncode=7)
    with pytest.raises(ProviderError, match='command exited with 7') as failure:
        writer.write_draft('销量', ['销量增长12%。'], provider)
    assert failure.value.usage.calls == 0
    assert len(log.read_text(encoding='utf-8').splitlines()) == 1
