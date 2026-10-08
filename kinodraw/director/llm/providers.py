"""LLM providers: one structured-JSON call per section (and one per "Choose for me" style pick), with usage and cost.

- cloud:     KinoDraw Cloud (free and paid plans); the key stays on the server.
- openai:    your OpenAI key (default gpt-6-luna).
- anthropic: your Anthropic key (default claude-opus-5), official SDK.
- compat:    any OpenAI-compatible endpoint (OpenRouter, DeepInfra, Groq, Ollama, LM Studio).
- command:   a program you choose: it gets the request as JSON on stdin and prints the requested JSON.
Keys (and the command) come from the OS keychain (service "KinoDraw") or environment variables.
"""
from __future__ import annotations

import json
import math
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field

from ... import paths
from . import errors
from .schema import SECTION_SCHEMA, STYLE_SYSTEM, SYSTEM, style_schema

# $ per million tokens: input, output, cached input (OpenRouter model list, 2026-09-24)
PRICES = {'gpt-6-luna': (.10, .50, .01), 'claude-opus-5-5': (4.0, 20.0, .20), 'claude-opus-5': (5.0, 25.0, .50),
          'claude-haiku-4-5': (1.0, 5.0, .10)}
SUGGESTED = {'openai': ['gpt-6-luna'], 'anthropic': ['claude-opus-5', 'claude-opus-5-5', 'claude-haiku-4-5'],
             'compat': [], 'command': []}
KEY_ENV = {'openai': 'OPENAI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY', 'compat': 'KINODRAW_COMPAT_API_KEY',
           'command': 'KINODRAW_DIRECTOR_COMMAND'}
# The names (never the values) of the keychain entries this app has saved. macOS asks the user before an app
# reads an entry it did not create, and every unsigned update counts as a new app, so the app only reads a key
# when a video uses it; this list answers "is a key saved?" without touching the keychain.
SAVED = paths.config_dir() / 'saved-keys.json'


class ProviderError(RuntimeError):
    """The call failed or returned nothing usable; the rules draft is kept for that section."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float | None = 0.0
    calls: int = 0
    by_model: dict = field(default_factory=dict)

    def add(self, model: str, inp: int | None, out: int | None, cached: int = 0, cost: float | None = None):
        # Missing metering contributes no known tokens and must not imply a free call.
        self.input_tokens += inp or 0
        self.output_tokens += out or 0
        self.cached_tokens += cached
        self.calls += 1
        if cost is None and model in PRICES and inp is not None and out is not None:
            pi, po, pc = PRICES[model]
            cost = (inp * pi + out * po + cached * pc) / 1e6
        self.cost_usd = None if cost is None or self.cost_usd is None else self.cost_usd + cost
        self.by_model[model] = self.by_model.get(model, 0) + 1


def api_key(provider: str) -> str | None:
    """The user's key from the OS keychain, else the environment."""
    try:
        import keyring
        key = keyring.get_password(paths.APP, provider)
        if key:
            return key
    except Exception:  # noqa: BLE001 - no keychain backend (e.g. headless Linux): fall back to the environment
        pass
    return paths.getenv(KEY_ENV.get(provider, ''))


def save_key(provider: str, key: str):
    import keyring
    keyring.set_password(paths.APP, provider, key)
    remember(provider)


def _saved_file() -> set:
    try:
        return set(json.loads(SAVED.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return set()


def remember(name: str):
    """Note that a keychain entry called ``name`` was saved."""
    SAVED.parent.mkdir(parents=True, exist_ok=True)
    SAVED.write_text(json.dumps(sorted(_saved_file() | {name})), encoding='utf-8')


def saved() -> set:
    """Names with a saved key (or an environment variable set), found without reading the keychain."""
    return _saved_file() | {p for p, env in KEY_ENV.items() if paths.getenv(env)}


class StructuredResponseError(ProviderError):
    """Invalid structured content; eligible for one bounded retry."""


def validate_structure(value, schema, path='plan'):
    """Validate the original JSON value, before any semantic repair or coercion. A field added to the plan
    contract later (v3 ``OPTIONAL``) may be absent, as in plans saved or served before it existed. The error
    names the first place that is wrong, so a re-ask can tell the model what to fix."""
    from ..v3.schema import OPTIONAL
    kind = schema['type']
    valid = (isinstance(value, dict) if kind == 'object' else
             isinstance(value, list) if kind == 'array' else
             isinstance(value, str) if kind == 'string' else
             isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
             and (kind != 'integer' or isinstance(value, int)))
    if not valid or ('enum' in schema and value not in schema['enum']):
        allowed = f' one of {schema["enum"]}' if 'enum' in schema and len(schema['enum']) <= 12 else ''
        raise StructuredResponseError(f'the answer did not follow the schema ({path}: expected {kind}{allowed})')
    if kind == 'object':
        extra = sorted(set(value) - set(schema['required']))
        missing = sorted(set(schema['required']) - set(value) - OPTIONAL)
        if extra or missing:
            raise StructuredResponseError(f'the answer did not follow the schema ({path}: object fields'
                                          + (f', unknown {extra}' if extra else '')
                                          + (f', missing {missing}' if missing else '') + ')')
        for key, sub in schema['properties'].items():
            if key in value:
                validate_structure(value[key], sub, f'{path}.{key}')
    elif kind == 'array':
        for n, item in enumerate(value):
            validate_structure(item, schema['items'], f'{path}[{n}]')
    return value


BACKOFF = (1.5, 4.0)      # seconds before the 2nd and 3rd try of a busy, rate-limited or unreachable service
_sleep = time.sleep       # tests replace it


def _object_text(text: str) -> str:
    """The first {...} in ``text`` (code fences and prose around it dropped), without trailing commas; strings kept."""
    start = text.find('{')
    if start < 0:
        return text
    out, depth, quoted, escaped = [], 0, False, False
    for ch in text[start:]:
        if quoted:
            quoted = escaped or ch != '"'
            escaped = not escaped and ch == '\\'
        elif ch == '"':
            quoted = True
        elif ch in '}]':
            while out and out[-1] in ' \t\r\n,':        # a trailing comma before the closing bracket
                if out.pop() == ',':
                    break
            depth -= 1
        elif ch in '{[':
            depth += 1
        out.append(ch)
        if depth == 0:
            break
    return ''.join(out)


def loads(text, lenient: bool = False):
    """The answer's JSON value. ``lenient`` (OpenAI-compatible servers that only promise JSON mode) also reads an
    answer wrapped in a code fence or prose, or with trailing commas; the schema is still checked afterwards."""
    try:
        return json.loads(text or '')
    except (ValueError, TypeError) as error:
        if lenient and isinstance(text, str):
            try:
                return json.loads(_object_text(text))
            except ValueError:
                pass
        raise StructuredResponseError('the answer was not valid JSON') from error


def _noted(payload, rejected):
    """The request again, telling the model why its previous answer was rejected."""
    return payload if not rejected or not isinstance(payload, dict) else \
        {**payload, 'previous_answer_rejected': f'{rejected}. Return the whole corrected answer.'}


def _structured(ask, schema, lenient=False, notes=None):
    """One answer that follows ``schema``: one more try after a malformed answer, told what was wrong
    (``ask(rejected)``), and up to 3 tries in all, after BACKOFF waits, while the service is busy, rate-limiting or
    unreachable. Other failures are not retried."""
    reasked = waited = 0
    rejected = None
    while True:
        try:
            value = loads(ask(rejected), lenient)
            if not isinstance(value, dict):
                raise StructuredResponseError('the answer must be a JSON object')
            value = validate_structure(value, schema)
            if rejected and notes is not None:
                notes.append(f're-asked once: {rejected}')
            return value
        except ProviderError as error:
            if isinstance(error, StructuredResponseError) and not reasked:
                reasked, rejected = 1, str(error)
            elif getattr(error, 'transient', False) and waited < len(BACKOFF):
                _sleep(BACKOFF[waited])
                waited += 1
            else:
                raise


def _api_failure(name, error):
    """A ProviderError whose message says in plain words what happened (errors.explain); never a class name or key."""
    kind = errors.classify(error)
    failure = ProviderError(errors.explain(error, name)['title'])
    failure.kind, failure.provider, failure.status = kind, name, getattr(error, 'status_code', None)
    failure.transient = kind in errors.TRANSIENT
    failure.technical = errors.redact(f'{type(error).__name__}: {error}')
    return failure


class StructuredProvider:
    def direct_plan(self, payload: dict, usage: Usage) -> dict:
        from ..v3.prompt import SYSTEM as PLAN_SYSTEM
        from ..v3.schema import PLAN_SCHEMA
        self.served_repairs = []                    # a re-ask is reported with the plan's repairs
        return self.structured(PLAN_SYSTEM, PLAN_SCHEMA, 'video_plan', payload, usage)

    def write_draft(self, payload: dict, usage: Usage) -> dict:
        from ...writer import WRITER_SCHEMA, WRITER_SYSTEM
        return self.structured(WRITER_SYSTEM, WRITER_SCHEMA, 'script_draft', payload, usage)


class OpenAIProvider(StructuredProvider):
    """OpenAI or any OpenAI-compatible server (set base_url)."""

    def __init__(self, model: str = 'gpt-6-luna', key: str | None = None, base_url: str | None = None,
                 name: str = 'openai', strict_schema: bool = True):
        from openai import OpenAI
        self.name, self.model, self.strict = name, model, strict_schema
        self.client = OpenAI(api_key=key or api_key(name) or 'none', base_url=base_url)

    def direct_section(self, payload: dict, usage: Usage) -> dict:
        return _parse(self._ask(SYSTEM, SECTION_SCHEMA, 'section_visuals', payload, usage), not self.strict)

    def pick_style(self, payload: dict, usage: Usage) -> dict:
        return _parse_style(self._ask(STYLE_SYSTEM, style_schema(_ids(payload)), 'style_pick', payload, usage),
                            not self.strict)

    def structured(self, system, schema, name, payload, usage):
        return _structured(lambda rejected: self._ask(system, schema, name, _noted(payload, rejected), usage, whole=True), schema,
                           lenient=not self.strict, notes=getattr(self, 'served_repairs', None))

    def _ask(self, system: str, schema: dict, name: str, payload: dict, usage: Usage, whole=False) -> str:
        user = json.dumps(payload, ensure_ascii=False)
        fmt = ({'type': 'json_schema', 'json_schema': {'name': name, 'schema': schema, 'strict': True}}
               if self.strict else {'type': 'json_object'})
        system = system if self.strict else system + '\nAnswer with JSON only, matching this schema:\n' + \
            json.dumps(schema)
        try:
            client = (self.client.with_options(max_retries=0, timeout=180)
                      if whole and hasattr(self.client, 'with_options') else self.client)
            response = client.chat.completions.create(
                model=self.model, response_format=fmt,
                messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                **({'max_completion_tokens': 16000} if whole else {}))
        except Exception as error:  # noqa: BLE001 - network, auth, rate limit: report and keep the rules draft
            raise _api_failure(self.name, error) from error
        u = getattr(response, 'usage', None)
        cached = getattr(getattr(u, 'prompt_tokens_details', None), 'cached_tokens', 0) or 0 if u else 0
        inp, out = getattr(u, 'prompt_tokens', None), getattr(u, 'completion_tokens', None)
        usage.add(getattr(response, 'model', None) or self.model,
                  inp - cached if inp is not None else None, out, cached)
        if not response.choices:
            raise StructuredResponseError(f'{self.name}: empty response')
        choice = response.choices[0]
        if getattr(choice.message, 'refusal', None):
            raise ProviderError(f'{self.name}: the model declined the request')
        if choice.finish_reason not in ('stop', None):
            raise (StructuredResponseError if choice.finish_reason == 'length' else ProviderError)(
                f'{self.name}: stopped early ({choice.finish_reason})')
        return choice.message.content


class AnthropicProvider(StructuredProvider):
    def __init__(self, model: str = 'claude-opus-5', key: str | None = None, effort: str = 'medium'):
        import anthropic
        self.name, self.model, self.effort = 'anthropic', model, effort
        self.client = anthropic.Anthropic(api_key=key or api_key('anthropic'))

    def direct_section(self, payload: dict, usage: Usage) -> dict:
        return _parse(self._ask(SYSTEM, SECTION_SCHEMA, payload, usage, 'this section'))

    def pick_style(self, payload: dict, usage: Usage) -> dict:
        return _parse_style(self._ask(STYLE_SYSTEM, style_schema(_ids(payload)), payload, usage, 'the style pick'))

    def structured(self, system, schema, name, payload, usage):
        return _structured(lambda rejected: self._ask(system, schema, _noted(payload, rejected), usage, name, whole=True), schema,
                           notes=getattr(self, 'served_repairs', None))

    def _ask(self, system: str, schema: dict, payload: dict, usage: Usage, what: str, whole=False) -> str:
        try:
            client = (self.client.with_options(max_retries=0, timeout=180)
                      if whole and hasattr(self.client, 'with_options') else self.client)
            response = client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
                messages=[{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
                output_config={'format': {'type': 'json_schema', 'schema': schema}, 'effort': self.effort},
            )
        except Exception as error:  # noqa: BLE001
            raise _api_failure('anthropic', error) from error
        u = getattr(response, 'usage', None)
        inp, out = getattr(u, 'input_tokens', None), getattr(u, 'output_tokens', None)
        written = getattr(u, 'cache_creation_input_tokens', 0) or 0
        read = getattr(u, 'cache_read_input_tokens', 0) or 0
        cost = None
        billed_model = getattr(response, 'model', None) or self.model
        if billed_model in PRICES and inp is not None and out is not None:
            # cache writes cost 1.25x input; reads the cached rate
            pi, po, pc = PRICES[billed_model]
            cost = (inp * pi + written * pi * 1.25 + read * pc + out * po) / 1e6
        usage.add(billed_model, inp + written if inp is not None else None, out, read, cost)
        if response.stop_reason == 'refusal':
            raise ProviderError(f'anthropic: the model declined {what}')
        if response.stop_reason == 'max_tokens':
            raise StructuredResponseError('anthropic: the answer was cut off (max_tokens)')
        return next((b.text for b in response.content if b.type == 'text'), '')


class CommandProvider(StructuredProvider):
    """A program you choose. It reads {"model", "system", "user", "schema"} as JSON on stdin and prints JSON
    following "schema" on stdout (section visuals, a style pick, a whole plan or a script draft). Its cost is whatever the
    program's own account says."""

    def __init__(self, model: str | None = None, command: str | None = None, timeout: float = 900):
        self.name, self.model, self.timeout = 'command', model or '', timeout
        line = command or os.environ.get('KINODRAW_DIRECTOR_COMMAND') or api_key('command')
        if not line:
            raise ValueError('save the command first (Settings, or the KINODRAW_DIRECTOR_COMMAND variable)')
        self.argv = line if os.name == 'nt' else shlex.split(line)   # Windows parses a command line itself

    def direct_section(self, payload: dict, usage: Usage) -> dict:
        return _parse(self._ask(SYSTEM, SECTION_SCHEMA, payload, usage))

    def structured(self, system, schema, name, payload, usage):
        return _structured(lambda rejected: self._ask(system, schema, _noted(payload, rejected), usage, strict=True), schema,
                           notes=getattr(self, 'served_repairs', None))

    def pick_style(self, payload: dict, usage: Usage) -> dict:
        return _parse_style(self._ask(STYLE_SYSTEM, style_schema(_ids(payload)), payload, usage))

    def _ask(self, system: str, schema: dict, payload: dict, usage: Usage, strict=False) -> str:
        request = json.dumps({'model': self.model, 'system': system, 'user': json.dumps(payload, ensure_ascii=False),
                              'schema': schema}, ensure_ascii=False)
        try:
            done = subprocess.run(self.argv, input=request, capture_output=True, encoding='utf-8', errors='replace',
                                  timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProviderError(f'command: {type(error).__name__}: {error}') from error
        if done.returncode != 0:
            raise ProviderError(f'command exited with {done.returncode}: {errors.redact(done.stderr.strip()[-300:])}')
        usage.add(f'command:{self.model}', 0, 0)       # tokens and cost are the program's business
        out = done.stdout.strip()
        return out if strict or out.startswith('{') else out[out.find('{'):out.rfind('}') + 1]


def _parse(text: str, lenient: bool = False) -> dict:
    data = loads(text, lenient)
    if not isinstance(data, dict) or not isinstance(data.get('beats'), list):
        raise ProviderError('the answer did not follow the section schema')
    return data


def _ids(payload: dict) -> list[str]:
    return [o['id'] for o in payload['options']]


def _parse_style(text: str, lenient: bool = False) -> dict:
    """{style, reason} as the model answered; director/style.py checks the style is one it offered."""
    data = loads(text, lenient)
    if not isinstance(data, dict) or not isinstance(data.get('style'), str):
        raise ProviderError('the answer did not name a style')
    return {'style': data['style'], 'reason': str(data.get('reason') or '')}


def make_provider(kind: str, model: str | None = None, base_url: str | None = None, lang: str | None = None):
    if kind == 'openai':
        return OpenAIProvider(model or 'gpt-6-luna')
    if kind == 'anthropic':
        return AnthropicProvider(model or 'claude-opus-5')
    if kind == 'compat':
        if not (base_url and model):
            raise ValueError('an OpenAI-compatible provider needs --base-url and --model')
        return OpenAIProvider(model, base_url=base_url, name='compat', strict_schema=False)
    if kind == 'command':
        return CommandProvider(model)
    if kind == 'cloud':
        from .cloud import CloudProvider
        return CloudProvider(lang)
    raise ValueError(f'unknown provider {kind!r}')
