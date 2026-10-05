"""Job-local cancellation and FFmpeg's encoded-frame progress."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


class Cancelled(RuntimeError):
    pass


class CancellationToken:
    """Own only explicitly registered processes; never discover by command line."""
    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.RLock()
        self._owned = {}

    def check(self):
        if self._event.is_set():
            raise Cancelled('render cancelled')

    def register(self, process, group=False):
        with self._lock:
            self._owned[process] = group
            if self._event.is_set():
                self.stop(process)
        return process

    def unregister(self, process):
        with self._lock:
            self._owned.pop(process, None)

    @staticmethod
    def _group_exists(pid):
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # A denied probe cannot establish absence. Retain ownership and
            # let the bounded wait require an eventual ESRCH.
            return True
        return True

    @staticmethod
    def _stop(process, group):
        # Groups are created by us with start_new_session, never borrowed.
        try:
            if process.poll() is None:
                # A render worker handles TERM by cancelling/reaping its own
                # encoder. Give it time before the group-level fallback.
                process.terminate()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5 if group else 2)
        except subprocess.TimeoutExpired:
            if not group:
                process.kill()
                process.wait()
        if group:
            # Reaping the leader does not prove its descendants have exited.
            # Signal only this registered group, then verify it is absent.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    break
                deadline = time.monotonic() + 2
                while CancellationToken._group_exists(process.pid) and time.monotonic() < deadline:
                    process.poll()
                    time.sleep(.02)
                if not CancellationToken._group_exists(process.pid):
                    break
            if CancellationToken._group_exists(process.pid):
                raise RuntimeError(f'owned process group {process.pid} survived cancellation')
            process.wait()

    def stop(self, process):
        with self._lock:
            group = self._owned.get(process)
            if group is not None:
                self._stop(process, group)
                self._owned.pop(process, None)

    def cancel(self):
        with self._lock:
            self._event.set()
            for process in list(self._owned):
                self.stop(process)

    def commit(self, source, output):
        with self._lock:
            self.check()
            Path(source).replace(output)

    @property
    def owned_pids(self):
        with self._lock:
            return tuple(p.pid for p, group in self._owned.items()
                         if p.poll() is None or (group and self._group_exists(p.pid)))


@dataclass(frozen=True)
class Progress:
    frames: int
    total: int
    elapsed: float
    eta: float | None


class RenderContext:
    """Share one instance across relevant jobs. Callbacks run on job threads."""
    def __init__(self, token=None, callback=None):
        self.token = token if token is not None else CancellationToken()
        self.callback = callback
        self.started = time.monotonic()
        self._last = -1
        self._lock = threading.Lock()

    def begin(self):
        """Reset sequential-job progress while retaining token and callback."""
        with self._lock:
            self.started = time.monotonic()
            self._last = -1

    def report(self, frames, total):
        with self._lock:
            frames = min(total, max(self._last, frames))
            if frames == self._last:
                return
            self._last = frames
            elapsed = time.monotonic() - self.started
            eta = elapsed * (total - frames) / frames if frames else None
            if self.callback:
                self.callback(Progress(frames, total, elapsed, eta))


def encoded_frames(path):
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return 0
    return max((int(s[6:]) for s in lines if s.startswith('frame=') and s[6:].strip().isdigit()), default=0)


def wait_process(process, context, progress_paths=(), total=0):
    while process.poll() is None:
        context.token.check()
        if progress_paths:
            context.report(sum(encoded_frames(p) for p in progress_paths), total)
        time.sleep(.03)
    context.token.check()
    if process.returncode:
        raise RuntimeError(f'encoder exited {process.returncode}')
    if progress_paths:
        context.report(sum(encoded_frames(p) for p in progress_paths), total)


def validate_frames(ffmpeg, source, expected, context, *, group=True):
    """Fully decode the staged video before allowing it to replace an output."""
    context.token.check()
    progress = Path(str(source) + '.decode-progress')
    process = context.token.register(subprocess.Popen([
        ffmpeg, '-v', 'error', '-xerror', '-err_detect', 'explode', '-i', str(source),
        '-map', '0:v:0', '-vsync', '0', '-progress', str(progress), '-f', 'null', '-'],
        start_new_session=group), group=group)
    try:
        wait_process(process, context)
        actual = encoded_frames(progress)
        if actual != expected:
            raise RuntimeError(f'encoded frames {actual} != expected {expected}')
    finally:
        context.token.stop(process)
