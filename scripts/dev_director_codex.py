"""Command director bridge using the developer's Codex ChatGPT login."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    try:
        request = json.load(sys.stdin)
        with tempfile.TemporaryDirectory(prefix='codex-', dir='/tmp/kd1005/a2-dev') as scratch:
            schema, out = Path(scratch) / 'schema.json', Path(scratch) / 'out.txt'
            schema.write_text(json.dumps(request['schema']), encoding='utf-8')
            prompt = request['system'] + '\n\n' + request['user']
            done = subprocess.run(
                ['env', '-u', 'OPENAI_API_KEY', 'codex', 'exec', '-m',
                 os.environ.get('DEV_DIRECTOR_MODEL', 'gpt-6-luna'), '-c',
                 'model_reasoning_effort=' + os.environ.get('DEV_DIRECTOR_EFFORT', 'medium'),
                 '--sandbox', 'read-only', '--ephemeral', '--skip-git-repo-check',
                 '--output-schema', str(schema), '-o', str(out), prompt],
                capture_output=True, encoding='utf-8', timeout=600)
            if done.returncode:
                raise RuntimeError(f'codex exited with {done.returncode}: {done.stderr.strip()[-300:]}')
            plan = json.loads(out.read_text(encoding='utf-8'))
            if not isinstance(plan, dict):
                raise ValueError('codex output must be a JSON object')
        print(json.dumps(plan, ensure_ascii=False))
    except subprocess.TimeoutExpired:
        sys.exit('dev director: codex timed out after 600 seconds')
    except json.JSONDecodeError as error:
        sys.exit(f'dev director: invalid JSON ({error})')
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        sys.exit(f'dev director: {error}')


if __name__ == '__main__':
    Path('/tmp/kd1005/a2-dev').mkdir(parents=True, exist_ok=True)
    main()
