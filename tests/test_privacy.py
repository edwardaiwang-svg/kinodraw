"""What the privacy page promises about the app itself."""
import os
import subprocess
import sys


def test_onnxruntime_is_told_not_to_report_usage():
    """onnxruntime (the voice, the doodle search) sends Microsoft usage events with a device id unless
    ORT_DISABLE_TELEMETRY is set before it loads; "no analytics and no tracking" means the app sets it first."""
    env = {k: v for k, v in os.environ.items() if k != 'ORT_DISABLE_TELEMETRY'}
    run = subprocess.run([sys.executable, '-c', 'import os, kinodraw; print(os.environ.get("ORT_DISABLE_TELEMETRY"))'],
                         env=env, capture_output=True, text=True, check=True, encoding='utf-8')
    assert run.stdout.strip() == '1'


def _page() -> str:
    import html
    import re
    from pathlib import Path
    raw = (Path(__file__).parents[1] / 'docs' / 'privacy.html').read_text(encoding='utf-8')
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', raw)).split())


def test_the_privacy_page_says_where_your_own_key_sends_your_sentences():
    """Settings > Advanced directors send each section straight to the user's own AI provider (or program);
    v0.1.6's page described only the offline director and Doodle Cloud."""
    import re
    from kinodraw.studio import server
    labels = re.findall(r"\['\w+', '([^']+)'\]", re.search(r'const ADVANCED = \[(.*?)\];', (server.STATIC / 'app.js')
                                                              .read_text(encoding='utf-8'), re.S).group(1))
    page = _page()
    assert len(labels) == 4 and all(label in page for label in labels), labels
    assert 'Advanced directors' in page


def test_the_privacy_page_names_every_host_the_app_downloads_from():
    from urllib.parse import urlparse
    from kinodraw import voice
    from kinodraw.director import match
    names = {'github.com': 'GitHub', 'huggingface.co': 'Hugging Face'}
    hosts = {urlparse(url).hostname for url, *_ in voice.FILES.values()} | {urlparse(match.HF).hostname}
    page = _page()
    assert all(names[host] in page for host in hosts)            # KeyError: a new host the page does not name


def test_the_privacy_page_says_how_to_delete_kinodraw_cloud_data_without_a_sign_in():
    """Anonymous KinoDraw Cloud use stores an install ID: the page names where the app shows it."""
    from kinodraw import cli
    from kinodraw.studio import server
    page = _page()
    assert 'Settings > KinoDraw Cloud' in page and 'kinodraw cloud-id' in page and 'privacy@doodlecloud.org' in page
    assert 'kinodraw cloud-id' in cli.__doc__ and "This installation's ID" in (server.STATIC / 'app.js').read_text(encoding='utf-8')
    assert 'with or without a sign-in, is not meant for children under 13' in page
