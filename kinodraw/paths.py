"""Where KinoDraw keeps its files, its environment variables, and the one-time move from Doodle Studio's folders.

KinoDraw was called Doodle Studio up to version 0.1.6. The first run of 0.2.0 renames the old folders (models, settings,
the doodle-search cache, the projects folder) so nothing is downloaded or lost again. Saved keys and the sign-in
live in the keychain under the old name and are not read: the user enters them again once, so the list of their
names (saved-keys.json) is deleted after the move instead of claiming keys and a sign-in KinoDraw doesn't have.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

import platformdirs

APP = 'KinoDraw'
OLD_APP = 'DoodleStudio'
OLD_PROJECTS = 'Doodle Studio'


def getenv(name: str) -> str | None:
    """``os.environ.get(name)``; a ``KINODRAW_`` variable also accepts its Doodle Studio name, ``DOODLE_...``."""
    value = os.environ.get(name)
    if not value and name.startswith('KINODRAW_'):
        value = os.environ.get('DOODLE_' + name[len('KINODRAW_'):])
    return value


def data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP))


def config_dir() -> Path:
    return Path(platformdirs.user_config_dir(APP))


def cache_dir() -> Path:
    return Path(platformdirs.user_cache_dir(APP))


def projects_dir() -> Path:
    return Path(platformdirs.user_videos_dir()) / APP


def legacy_moves() -> list[tuple[Path, Path]]:
    """(Doodle Studio folder, KinoDraw folder) pairs. Data first: on Windows the config and cache folders are
    inside the data folder, so they move with it."""
    return [(Path(platformdirs.user_data_dir(OLD_APP)), data_dir()),
            (Path(platformdirs.user_config_dir(OLD_APP)), config_dir()),
            (Path(platformdirs.user_cache_dir(OLD_APP)), cache_dir()),
            (Path(platformdirs.user_videos_dir()) / OLD_PROJECTS, projects_dir())]


def migrate(moves: list[tuple[Path, Path]] | None = None, settings: Path | None = None) -> list[tuple[Path, Path]]:
    """Rename each old folder that exists to its new name, unless the new one already exists. A rename that fails
    (another drive, a file in use) leaves the old folder where it is and the app starts fresh. A projects folder
    saved in the Studio's settings follows its move; the moved list of saved keys is deleted (its keychain entries
    stay under Doodle Studio's name). Returns the moves made."""
    done = []
    for old, new in legacy_moves() if moves is None else moves:
        if old == new or not old.is_dir():
            continue
        with contextlib.suppress(OSError):
            new.rmdir()                             # an empty new folder doesn't count (rmdir only removes empty ones)
        if new.exists():
            continue
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
        except OSError:
            continue
        done.append((old, new))
        if old.parent.name == OLD_APP:              # Windows: %LOCALAPPDATA%\DoodleStudio\DoodleStudio
            with contextlib.suppress(OSError):
                old.parent.rmdir()                  # only if now empty
    keys = config_dir() / 'saved-keys.json'          # Doodle Studio's names, not KinoDraw's (providers.SAVED)
    if any(keys.is_relative_to(new) for _, new in done):
        with contextlib.suppress(OSError):
            keys.unlink(missing_ok=True)
    settings = settings or config_dir() / 'studio.json'
    with contextlib.suppress(OSError, ValueError, AttributeError):
        cfg = json.loads(settings.read_text())
        moved = {str(old): str(new) for old, new in done}
        if cfg.get('projects') in moved:
            cfg['projects'] = moved[cfg['projects']]
            settings.write_text(json.dumps(cfg, indent=1))
    return done
