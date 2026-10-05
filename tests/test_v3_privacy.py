"""Default whole-story planning must not be described as section-only upload."""
import html
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]


def readable(text):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', text)).split())


def check_disclosure(text):
    text = readable(text)
    for disclosure in ('Director v3', 'full story and prompt', 'spoken beats',
                       'Legacy projects with Director v3 off', 'first 600 characters',
                       'generated SVG props', 'source notes', 'voice guidance',
                       'reused locally', 'Choose Offline for local planning'):
        assert disclosure in text, disclosure


def test_readme_and_privacy_disclose_full_story_and_optional_requests():
    for page in (ROOT / 'README.md', ROOT / 'docs/privacy.html'):
        check_disclosure(page.read_text(encoding='utf-8'))
