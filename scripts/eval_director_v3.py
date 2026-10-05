"""Evaluate whole-video plans on the genre fixtures and the lion story."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kinodraw.director.v3.llm import plan_v3  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['rules', 'command', 'cloud', 'openai', 'compat', 'anthropic'], required=True)
    parser.add_argument('--model')
    parser.add_argument('--base-url')
    parser.add_argument('--out', type=Path, required=True, help='directory for evaluation reports and plans')
    args = parser.parse_args()
    fixtures = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures'
    args.out.mkdir(parents=True, exist_ok=True)
    failed = False
    for path in sorted((fixtures / 'genre').glob('*.md')) + [fixtures / 'lion_story.md']:
        provider = args.provider
        if args.model or args.base_url:
            from kinodraw.director.llm.providers import make_provider
            provider = make_provider(args.provider, model=args.model, base_url=args.base_url)
        plan, report = plan_v3(path, provider=provider)
        failed |= report['fallback']
        result = {'script': path.stem, 'provider': report['provider'], 'mode': plan['style']['mode'],
                  'treatments': dict(Counter(scene['treatment'] for scene in plan['scenes'])),
                  'cast': [{key: c[key] for key in ('name', 'species', 'age', 'marks')} for c in plan['cast']],
                  'repairs': len(report['repairs']), 'seconds': report['seconds'],
                  'fallback': report['fallback'], 'fallback_reason': report['fallback_reason'],
                  'usage': asdict(report['usage'])}
        text = json.dumps(result, ensure_ascii=False)
        print(text, flush=True)
        (args.out / f'{path.stem}.json').write_text(text + '\n', encoding='utf-8')
        (args.out / f'{path.stem}.plan.json').write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
