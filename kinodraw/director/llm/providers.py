"""LLM providers: one structured-JSON call per section, with usage and cost.

- cloud:     Doodle Cloud (free and paid plans); the key stays on the server.
- openai:    your OpenAI key (default gpt-6-luna).
- anthropic: your Anthropic key (default claude-opus-5), official SDK.
- compat:    any OpenAI-compatible endpoint (OpenRouter, DeepInfra, Groq, Ollama, LM Studio).
- command:   a program you choose: it gets the request as JSON on stdin and prints the section JSON.
Keys (and the command) come from the OS keychain (service "DoodleStudio") or environment variables.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

from .schema import SECTION_SCHEMA, SYSTEM

# $ per million tokens: input, output, cached input (OpenRouter model list, 2026-09-24)
PRICES = {'gpt-6-luna': (.10, .50, .01), 'claude-opus-5-5': (4.0, 20.0, .20), 'claude-opus-5': (5.0, 25.0, .50),
          'claude-haiku-4-5': (1.0, 5.0, .10)}
SUGGESTED = {'openai': ['gpt-6-luna'], 'anthropic': ['claude-opus-5', 'claude-opus-5-5', 'claude-haiku-4-5'],
             'compat': [], 'command': []}
KEY_ENV = {'openai': 'OPENAI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY', 'compat': 'DOODLE_COMPAT_API_KEY',
           'command': 'DOODLE_DIRECTOR_COMMAND'}
# The names (never the values) of the keychain entries this app has saved. macOS asks the user before an app
# reads an entry it did not create, and every unsigned update counts as a new app, so the app only reads a key
# when a video uses it; this list answers "is a key saved?" without touching the keychain.
SAVED = Path(platformdirs.user_config_dir('DoodleStudio')) / 'saved-keys.json'


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

    def add(self, model: str, inp: int, out: int, cached: int = 0, cost: float | None = None):
        self.input_tokens += inp
        self.output_tokens += out
        self.cached_tokens += cached
        self.calls += 1
        if cost is None and model in PRICES:
            pi, po, pc = PRICES[model]
            cost = (inp * pi + out * po + cached * pc) / 1e6
        self.cost_usd = None if cost is None or self.cost_usd is None else self.cost_usd + cost
        self.by_model[model] = self.by_model.get(model, 0) + 1


def api_key(provider: str) -> str | None:
    """The user's key from the OS keychain, else the environment."""
    try:
        import keyring
        key = keyring.get_password('DoodleStudio', provider)
        if key:
            return key
    except Exception:  # noqa: BLE001 - no keychain backend (e.g. headless Linux): fall back to the environment
        pass
    return os.environ.get(KEY_ENV.get(provider, ''))


def save_key(provider: str, key: str):
    import keyring
    keyring.set_password('DoodleStudio', provider, key)
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
    return _saved_file() | {p for p, env in KEY_ENV.items() if os.environ.get(env)}


class OpenAIProvider:
    """OpenAI or any OpenAI-compatible server (set base_url)."""

    def __init__(self, model: str = 'gpt-6-luna', key: str | None = None, base_url: str | None = None,
                 name: str = 'openai', strict_schema: bool = True):
        from openai import OpenAI
        self.name, self.model, self.strict = name, model, strict_schema
        self.client = OpenAI(api_key=key or api_key(name) or 'none', base_url=base_url)

    def direct_section(self, payload: dict, usage: Usage) -> dict:
        user = json.dumps(payload, ensure_ascii=False)
        fmt = ({'type': 'json_schema', 'json_schema': {'name': 'section_visuals', 'schema': SECTION_SCHEMA, 'strict': True}}
               if self.strict else {'type': 'json_object'})
        system = SYSTEM if self.strict else SYSTEM + '\nAnswer with JSON only, matching this schema:\n' + \
            json.dumps(SECTION_SCHEMA)
        try:
            response = self.client.chat.completions.create(
                model=self.model, response_format=fmt,
                messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user}])
        except Exception as error:  # noqa: BLE001 - network, auth, rate limit: report and keep the rules draft
            raise ProviderError(f'{self.name}: {type(error).__name__}: {error}') from error
        u = response.usage
        cached = getattr(getattr(u, 'prompt_tokens_details', None), 'cached_tokens', 0) or 0 if u else 0
        usage.add(self.model, (u.prompt_tokens - cached) if u else 0, u.completion_tokens if u else 0, cached)
        choice = response.choices[0]
        if choice.finish_reason not in ('stop', None):
            raise ProviderError(f'{self.name}: stopped early ({choice.finish_reason})')
        return _parse(choice.message.content)


class AnthropicProvider:
    def __init__(self, model: str = 'claude-opus-5', key: str | None = None, effort: str = 'medium'):
        import anthropic
        self.name, self.model, self.effort = 'anthropic', model, effort
        self.client = anthropic.Anthropic(api_key=key or api_key('anthropic'))

    def direct_section(self, payload: dict, usage: Usage) -> dict:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=[{'type': 'text', 'text': SYSTEM, 'cache_control': {'type': 'ephemeral'}}],
                messages=[{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
                output_config={'format': {'type': 'json_schema', 'schema': SECTION_SCHEMA}, 'effort': self.effort},
            )
        except Exception as error:  # noqa: BLE001
            raise ProviderError(f'anthropic: {type(error).__name__}: {error}') from error
        u = response.usage
        written, read = u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0
        cost = None
        if self.model in PRICES:                      # cache writes cost 1.25x input; reads the cached rate
            pi, po, pc = PRICES[self.model]
            cost = (u.input_tokens * pi + written * pi * 1.25 + read * pc + u.output_tokens * po) / 1e6
        usage.add(self.model, u.input_tokens + written, u.output_tokens, read, cost)
        if response.stop_reason == 'refusal':
            raise ProviderError('anthropic: the model declined this section')
        if response.stop_reason == 'max_tokens':
            raise ProviderError('anthropic: the answer was cut off (max_tokens)')
        text = next((b.text for b in response.content if b.type == 'text'), '')
        return _parse(text)


class CommandProvider:
    """A program you choose. It reads {"model", "system", "user", "schema"} as JSON on stdin and prints the
    section JSON (following "schema") on stdout. Its cost is whatever the program's own account says."""

    def __init__(self, model: str | None = None, command: str | None = None, timeout: float = 900):
        self.name, self.model, self.timeout = 'command', model or '', timeout
        line = command or api_key('command')
        if not line:
            raise ValueError('save the command first (Settings, or the DOODLE_DIRECTOR_COMMAND variable)')
        self.argv = line if os.name == 'nt' else shlex.split(line)   # Windows parses a command line itself

    def direct_section(self, payload: dict, usage: Usage) -> dict:
        request = json.dumps({'model': self.model, 'system': SYSTEM, 'user': json.dumps(payload, ensure_ascii=False),
                              'schema': SECTION_SCHEMA}, ensure_ascii=False)
        try:
            done = subprocess.run(self.argv, input=request, capture_output=True, encoding='utf-8', errors='replace',
                                  timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProviderError(f'command: {type(error).__name__}: {error}') from error
        if done.returncode != 0:
            raise ProviderError(f'command exited with {done.returncode}: {done.stderr.strip()[-300:]}')
        usage.add(f'command:{self.model}', 0, 0)       # tokens and cost are the program's business
        out = done.stdout.strip()
        return _parse(out[out.find('{'):out.rfind('}') + 1] if not out.startswith('{') else out)


def _parse(text: str) -> dict:
    try:
        data = json.loads(text or '')
    except json.JSONDecodeError as error:
        raise ProviderError(f'the answer was not valid JSON ({error})') from error
    if not isinstance(data, dict) or not isinstance(data.get('beats'), list):
        raise ProviderError('the answer did not follow the section schema')
    return data


def make_provider(kind: str, model: str | None = None, base_url: str | None = None):
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
        return CloudProvider()
    raise ValueError(f'unknown provider {kind!r}')
