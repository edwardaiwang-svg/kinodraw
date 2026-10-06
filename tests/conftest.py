import keyring.core
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError


@pytest.fixture(autouse=True)
def _keep_the_developers_own_folders(monkeypatch, tmp_path):
    """The CLI and the Studio rename Doodle Studio's folders on the first run (kinodraw.paths.migrate); tests that
    call them must not move the developer's own folders (tests/test_rename.py tests the real function), and the
    Studio's projects folder is a temporary one."""
    from kinodraw import paths
    monkeypatch.setattr(paths, 'migrate', lambda moves=None, settings=None: [])
    monkeypatch.setattr(paths, 'left_behind', [])
    monkeypatch.setattr(paths, 'projects_dir', lambda: tmp_path / 'projects')


class _Keychain(KeyringBackend):
    """An empty keychain in memory for each test, so no test reads or writes the developer's own (a kept KinoDraw Cloud
    token there would change what a signed-out test sees)."""
    priority = 1

    def __init__(self):
        super().__init__()
        self.saved = {}

    def get_password(self, service, name):
        return self.saved.get((service, name))

    def set_password(self, service, name, value):
        self.saved[(service, name)] = value

    def delete_password(self, service, name):
        if (service, name) not in self.saved:
            raise PasswordDeleteError(name)
        del self.saved[(service, name)]


@pytest.fixture(autouse=True)
def _keep_the_developers_own_keychain(monkeypatch):
    from kinodraw.director.llm import cloud
    monkeypatch.setattr(keyring.core, '_keyring_backend', _Keychain())   # tests that stub keyring's functions still win
    monkeypatch.setattr(cloud, '_anon_token', None)                    # the process fallback belongs to this test too
