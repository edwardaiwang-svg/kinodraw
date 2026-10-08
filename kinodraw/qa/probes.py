"""FFmpeg measurements and small-frame QA; declared holds are explicit exemptions."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import math
import re
import subprocess
from typing import Literal

import imageio_ffmpeg
import numpy as np

ProbeDefect = Literal['dead_air', 'frozen_picture', 'blank_opening', 'flash_safety',
                      'motion_floor', 'loudness', 'cut_timing']

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
# A story or motion page holds still while its narration speaks (J 10/8: no camera push or idle sway to keep the
# picture moving); freezedetect sees such a page as frozen. It is exempt for up to HELD_PAGE seconds; a page held
# longer than that, or a freeze outside its narration, is still a frozen_picture.
HELD_PAGE = 8.
REPAIRS = {
    'dead_air': 'Shorten the silent transition to less than 1.5 seconds; advance the next narration.',
    'frozen_picture': 'Raise motion_floor; add breathing or camera drift outside declared reading holds.',
    'blank_opening': 'Start the first visible scene at time zero; remove the blank lead-in.',
    'flash_safety': 'Remove alternating bright/dark frames; keep luma swings below 20% and at most 3 per second.',
    'motion_floor': 'Add ambient motion to static 0.5-second windows outside declared holds.',
    'loudness': 'Normalize the audio master to -16 LUFS before muxing.',
    'cut_timing': 'Snap scene cuts to the supplied music beat grid within 0.1 seconds.',
}


@dataclass(frozen=True)
class Span:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Finding:
    defect: ProbeDefect
    start: float
    end: float
    note: str
    repair: str


@dataclass
class QAReport:
    video: str
    duration: float
    findings: list[Finding] = field(default_factory=list)
    silences: list[Span] = field(default_factory=list)
    freezes: list[Span] = field(default_factory=list)
    black: list[Span] = field(default_factory=list)
    exemptions: list[Span] = field(default_factory=list)
    held_pages: list[Span] = field(default_factory=list)     # freezes exempt as narrated held pages
    motion_static_share: float = 0.0
    motion_windows: int = 0
    flash_ok: bool = True
    flash_max_swings_per_second: int = 0
    integrated_lufs: float | None = None
    cut_offsets: list[float] = field(default_factory=list)
    audio_present: bool = True

    @property
    def package_ok(self) -> bool:
        return not any(f.defect in ('dead_air', 'frozen_picture') for f in self.findings)

    @property
    def ok(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict:
        return {**asdict(self), 'ok': self.ok, 'package_ok': self.package_ok,
                'repairs': {f.defect: f.repair for f in self.findings}}


def declared_holds(timeline: dict) -> list[Span]:
    intervals = list(timeline.get('holds', []))
    if timeline.get('end_card'):
        intervals.append(timeline['end_card'])
    intervals += [{'start': t['speech_end'], 'end': t['hold_end']}
                  for t in timeline.get('transitions', [])]
    for key, seconds in timeline.get('pauses', {}).items():
        beat = timeline.get('beats', {}).get(key)
        if beat and seconds > 0:
            intervals.append({'start': beat['speech_end'], 'end': beat['speech_end'] + seconds})
    result = []
    for interval in intervals:
        start, end = float(interval['start']), float(interval['end'])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
            raise ValueError('holds must have finite, ordered nonnegative timestamps')
        result.append(Span(start, end))
    return sorted(result, key=lambda s: s.start)


def _outside(span: Span, exemptions: list[Span]) -> list[Span]:
    parts = [span]
    for hold in exemptions:
        next_parts = []
        for part in parts:
            if hold.end <= part.start or hold.start >= part.end:
                next_parts.append(part)
            else:
                if part.start < hold.start:
                    next_parts.append(Span(part.start, hold.start))
                if hold.end < part.end:
                    next_parts.append(Span(hold.end, part.end))
        parts = next_parts
    return parts


def _events(log: str, prefix: str, duration: float) -> list[Span]:
    result, start = [], None
    for event, value in re.findall(rf'{prefix}_(start|end):\s*(-?[\d.]+)', log):
        if event == 'start':
            start = max(0., float(value))
        elif start is not None:
            result.append(Span(start, min(duration, float(value))))
            start = None
    if start is not None:
        result.append(Span(start, duration))
    return result


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([FFMPEG, '-hide_banner', '-nostdin', *args], capture_output=True, check=True)


def probe(video: Path | str, timeline: dict | None = None, beat_grid: list[float] | None = None,
          narrated_pages: list[tuple[float, float]] | None = None) -> QAReport:
    """``narrated_pages`` are (start, end) stretches where a story or motion page is shown while its narration
    speaks; a freeze inside one of them lasting at most HELD_PAGE seconds is a held page, not a frozen picture."""
    video = Path(video)
    log = _run(['-i', str(video), '-map', '0:v:0', '-vf',
                'freezedetect=n=-50dB:d=1,blackdetect=d=0.1:pix_th=0.1', '-an', '-f', 'null', '-']).stderr.decode('utf-8', 'replace')
    duration_match = re.search(r'Duration: (\d+):(\d+):([\d.]+)', log)
    if not duration_match:
        raise ValueError('video has no finite duration')
    duration = int(duration_match[1]) * 3600 + int(duration_match[2]) * 60 + float(duration_match[3])
    report = QAReport(str(video), duration, exemptions=declared_holds(timeline or {}))
    report.freezes = _events(log, 'freeze', duration)
    report.black = [Span(float(a), float(b)) for a, b in
                    re.findall(r'black_start:([\d.]+) black_end:([\d.]+)', log)]
    report.audio_present = 'Audio:' in log.split('Output #0')[0]
    if report.audio_present:
        audio_log = _run(['-i', str(video), '-map', '0:a:0', '-af',
                          'silencedetect=n=-40dB:d=1.5,ebur128', '-vn', '-f', 'null', '-']).stderr.decode('utf-8', 'replace')
        report.silences = _events(audio_log, 'silence', duration)
        loudness = re.findall(r'I:\s*(-?\d+(?:\.\d+)?) LUFS', audio_log)
        report.integrated_lufs = float(loudness[-1]) if loudness else None
    else:
        report.silences = [Span(0, duration)]

    def add(defect: ProbeDefect, start: float, end: float, note: str):
        report.findings.append(Finding(defect, float(start), float(end), note, REPAIRS[defect]))

    for defect, spans, threshold in (('dead_air', report.silences, 1.5),
                                      ('frozen_picture', report.freezes, 1.0)):
        exemptions = declared_holds({'end_card': timeline['end_card']}) \
            if defect == 'dead_air' and timeline and timeline.get('end_card') else \
            [] if defect == 'dead_air' else report.exemptions
        for span in spans:
            for part in _outside(span, exemptions):
                if part.duration < threshold - 1e-6:
                    continue
                if defect == 'frozen_picture' and part.duration <= HELD_PAGE + 1e-6 and any(
                        a - 1 / 30 <= part.start and part.end <= b + 1 / 30 for a, b in narrated_pages or ()):
                    report.held_pages.append(part)
                    continue
                add(defect, part.start, part.end, f'{part.duration:.3f}s outside permitted exemptions')
    if report.integrated_lufs is None or not -20 <= report.integrated_lufs <= -12:
        add('loudness', 0, duration, f'integrated loudness: {report.integrated_lufs} LUFS')

    # 30 Hz sampling retains flashes which a 2 Hz motion sample would alias away.
    command = [FFMPEG, '-hide_banner', '-nostdin', '-v', 'error', '-i', str(video), '-an',
               '-vf', 'fps=30,scale=160:90', '-pix_fmt', 'gray', '-f', 'rawvideo', '-']
    changes, lumas, opening = [], [], []
    previous = None
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        while True:
            raw = process.stdout.read(160 * 90)
            if not raw:
                break
            if len(raw) != 160 * 90:
                process.kill()
                raise ValueError('incomplete decoded frame')
            frame = np.frombuffer(raw, np.uint8).astype(np.float32)
            lumas.append(float(frame.mean() / 255))
            if len(lumas) <= 15:
                opening.append(float(frame.std()))
            if previous is not None:
                changes.append(float(np.abs(frame - previous).mean() / 255))
            previous = frame
        error = process.stderr.read()
        status = process.wait()
        if status:
            raise subprocess.CalledProcessError(status, command, stderr=error)
    if opening and (max(opening) < 1.0 or any(s.start <= .05 for s in report.black)):
        add('blank_opening', 0, min(.5, duration), 'uniform or black opening at sampled resolution')
    swings = np.flatnonzero(np.abs(np.diff(lumas)) >= .2) / 30 + 1 / 30
    maximum = max((int(np.sum((swings >= t) & (swings < t + 1))) for t in swings), default=0)
    report.flash_max_swings_per_second = maximum
    report.flash_ok = maximum <= 3
    if not report.flash_ok:
        add('flash_safety', float(swings[0]), min(duration, float(swings[-1] + 1 / 30)),
            f'{maximum} luma swings >=20% in a rolling second (screening only)')
    static = 0
    for i in range(0, len(changes) - 14, 15):
        span = Span(i / 30, (i + 15) / 30)
        if sum(p.duration for p in _outside(span, report.exemptions)) < .5 - 1e-6:
            continue
        report.motion_windows += 1
        static += max(changes[i:i + 15]) < .001
    report.motion_static_share = static / max(1, report.motion_windows)
    if report.motion_static_share > .1:
        add('motion_floor', 0, duration, f'{report.motion_static_share:.1%} of eligible 0.5s windows static')
    if beat_grid is not None:
        if not beat_grid or any(not math.isfinite(t) or t < 0 for t in beat_grid):
            raise ValueError('beat_grid must contain finite nonnegative timestamps')
        cuts = np.flatnonzero(np.asarray(changes) >= .2) / 30 + 1 / 30
        report.cut_offsets = [min(abs(float(t) - b) for b in beat_grid) for t in cuts]
        for t, offset in zip(cuts, report.cut_offsets):
            if offset > .1:
                add('cut_timing', t, t, f'candidate cut {offset:.3f}s from nearest beat')
    return report
