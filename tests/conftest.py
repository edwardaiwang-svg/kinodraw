import pytest


@pytest.fixture(autouse=True)
def _keep_the_developers_own_folders(monkeypatch, tmp_path):
    """The CLI and the Studio rename Doodle Studio's folders on the first run (kinodraw.paths.migrate); tests that
    call them must not move the developer's own folders (tests/test_rename.py tests the real function), and the
    Studio's projects folder is a temporary one."""
    from kinodraw import paths
    monkeypatch.setattr(paths, 'migrate', lambda moves=None, settings=None: [])
    monkeypatch.setattr(paths, 'projects_dir', lambda: tmp_path / 'projects')
