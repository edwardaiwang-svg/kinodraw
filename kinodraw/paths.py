"""Where KinoDraw keeps its files, its environment variables, and the one-time move from Doodle Studio's folders.

KinoDraw was called Doodle Studio up to version 0.1.6. The first run of 0.2.0 renames the old folders (models, settings,
the doodle-search cache, the projects folder) so nothing is downloaded or lost again. A folder that cannot be renamed
(on Windows: Doodle Studio still open, an antivirus scan) is tried again at every launch until it moves, and the user
is told meanwhile. Saved keys and the sign-in live in the keychain under the old name and are not read: the user
enters them again once, so the list of their names (saved-keys.json) is deleted after the move instead of claiming
keys and a sign-in KinoDraw doesn't have.
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
KEYS = 'saved-keys.json'                     # Doodle Studio's names, not KinoDraw's (providers.SAVED)
PENDING = 'doodle-studio-move.json'          # in config_dir(): the old folders that could not move yet
NOT_MOVED = ("KinoDraw couldn't bring over your Doodle Studio projects, voices and settings yet, usually because "
             "Doodle Studio is still open. Close Doodle Studio, then close and reopen KinoDraw (if this keeps coming "
             "back, restart your computer first). Nothing has been deleted.")
left_behind: list[Path] = []                 # this launch's old folders that could not move (the CLI and Studio say so)


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
    (a file in use, another drive) leaves the old folder, and everything inside it, where it is; it is listed in
    ``left_behind`` and in PENDING, and at the next launches it is merged into the new folder (which KinoDraw may
    have used in the meantime) until nothing is left to move. A projects folder saved in the Studio's settings
    follows its move; the moved list of saved keys is deleted (its keychain entries stay under Doodle Studio's name).
    Returns the moves made."""
    moves = legacy_moves() if moves is None else moves
    marker = config_dir() / PENDING
    try:
        pending = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pending = []
    done, merged, failed = [], [], []
    for old, new in moves:
        if old == new or not old.is_dir() or any(old.is_relative_to(o) for o in [o for o, _ in done] + failed):
            continue                                # Windows: config and cache are inside data, and go with it
        with contextlib.suppress(OSError):
            new.rmdir()                             # an empty new folder doesn't count (rmdir only removes empty ones)
        try:
            if not new.exists():
                new.parent.mkdir(parents=True, exist_ok=True)
                old.rename(new)
            elif str(old) in pending:               # KinoDraw ran after a failed move: bring over what it lacks
                merged.append((old, new))
                _merge(old, new)
            else:
                continue                            # KinoDraw's own folder is never replaced
        except OSError:
            failed.append(old)
            continue
        done.append((old, new))
        if old.parent.name == OLD_APP:              # Windows: %LOCALAPPDATA%\DoodleStudio\DoodleStudio
            with contextlib.suppress(OSError):
                old.parent.rmdir()                  # only if now empty
    left_behind[:] = failed
    with contextlib.suppress(OSError):
        if failed:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps([str(f) for f in failed]), encoding='utf-8')
        else:
            marker.unlink(missing_ok=True)
    keys = config_dir() / KEYS
    if any(keys.is_relative_to(new) for old, new in done if (old, new) not in merged):
        with contextlib.suppress(OSError):
            keys.unlink(missing_ok=True)
    settings = settings or config_dir() / 'studio.json'
    with contextlib.suppress(OSError, ValueError, AttributeError, TypeError):
        cfg = before = json.loads(settings.read_text(encoding='utf-8'))
        for old, new in merged:                     # Doodle Studio's settings fill in what KinoDraw's lack
            if settings.is_relative_to(new) and (theirs := old / settings.relative_to(new)).is_file():
                cfg = {**json.loads(theirs.read_text(encoding='utf-8')), **cfg}
        root = Path(cfg.get('projects') or '')
        for old, new in moves:                      # the projects folder, or a folder inside it, moved
            if root.is_relative_to(old) and not root.exists() and (new / root.relative_to(old)).is_dir():
                cfg = {**cfg, 'projects': str(new / root.relative_to(old))}
        if cfg != before:
            settings.write_text(json.dumps(cfg, indent=1), encoding='utf-8')
    return done


def _merge(old: Path, new: Path):
    """Move into ``new`` what it lacks from ``old``, folder by folder. KinoDraw's own files stay (the old copy is left
    where it is), a Doodle Studio project named like a KinoDraw one comes over as "Name (Doodle Studio)", and the old
    list of saved keys never comes over. Raises OSError when something could not be moved (it is tried again)."""
    for item in sorted(old.iterdir()):
        target = new / item.name
        if item.name == KEYS:
            continue
        if target.exists() and (item / 'project.json').is_file():
            n = 1
            while target.exists():
                target = new / f"{item.name} (Doodle Studio{f' {n}' if n > 1 else ''})"
                n += 1
        elif target.exists():
            if item.is_dir() and target.is_dir():
                _merge(item, target)
            continue
        item.rename(target)
    with contextlib.suppress(OSError):
        old.rmdir()                                 # only if now empty
