import json

from kinodraw import net
from kinodraw.director.llm import cloud


def test_requests_carry_the_app_signature(monkeypatch):
    """Cloudflare answers 403 (error 1010) to Python's default "Python-urllib" signature."""
    seen = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({'ok': True}).encode()

    def urlopen(req, timeout):
        seen['ua'] = req.get_header('User-agent')
        return Reply()

    monkeypatch.setattr(cloud, 'URL', 'https://api.example.org')
    monkeypatch.setattr(cloud, 'urlopen', urlopen)
    cloud.signup('someone@example.org')
    assert seen['ua'].startswith('DoodleStudio')


def test_https_trusts_certifi_where_the_system_has_no_certificates(monkeypatch):
    """The packaged Mac app finds no system certificates; v0.1.4 failed every sign-in with CERTIFICATE_VERIFY_FAILED."""
    monkeypatch.setenv('SSL_CERT_FILE', '/nonexistent')
    monkeypatch.setenv('SSL_CERT_DIR', '/nonexistent')
    assert net._context.__wrapped__().cert_store_stats()['x509_ca'] > 100
