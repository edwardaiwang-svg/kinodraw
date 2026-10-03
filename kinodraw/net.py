"""HTTPS for the model downloads and KinoDraw Cloud: the system's certificates plus certifi's.

The packaged Mac app's OpenSSL looks for certificates in a folder only the build machine has,
so without certifi's bundle every HTTPS call there failed with CERTIFICATE_VERIFY_FAILED.
"""
from __future__ import annotations

import hashlib
import ssl
import urllib.request
from functools import cache
from pathlib import Path

import certifi


@cache
def _context() -> ssl.SSLContext:
    context = ssl.create_default_context()      # keeps the system store (Windows, Linux, a school's own certificate)
    context.load_verify_locations(certifi.where())
    return context


def urlopen(request, **kwargs):
    return urllib.request.urlopen(request, context=_context(), **kwargs)


def download(files: list[tuple[str, Path, str, int]], progress=None):
    """Fetch each (url, path, sha256, size) that is not on disk yet, checksum-verified, reporting
    ``progress(done, total)`` in bytes over all of them (sizes are known up front, so the total never moves)."""
    files = [f for f in files if not f[1].is_file()]
    total, done = sum(size for *_, size in files), 0
    for url, path, digest, _ in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(f'{path.name}.part')
        h = hashlib.sha256()
        with urlopen(url) as response, open(part, 'wb') as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(min(done, total), total)
        if h.hexdigest() != digest:
            part.unlink()
            raise RuntimeError(f'{path.name}: checksum mismatch; download again')
        part.rename(path)
