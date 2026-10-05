"""Numbered timeline contact sheets and strict, provider-independent visual review."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .probes import _run

DEFECTS = ('wrong_meaning_picture', 'text_clipped', 'title_cut', 'character_indistinct',
           'static_too_long', 'quote_misplaced', 'unreadable_text', 'off_style', 'other')
REPAIRS = {
    'wrong_meaning_picture': 'Replace the visual with a scene matching the narration and subject species.',
    'text_clipped': 'Wrap and fit the text inside the safe-area margins.',
    'title_cut': 'Replace the title with a complete short clause and fit it inside the title safe area.',
    'character_indistinct': 'Give each named character distinct species, age, palette and distinguishing marks.',
    'static_too_long': 'Raise motion_floor and add breathing or camera drift outside declared holds.',
    'quote_misplaced': 'Schedule the quote mark, body and speaker as one card at the spoken quote.',
    'unreadable_text': 'Shorten the label and increase its font size and contrast.',
    'off_style': 'Apply the video palette and type style to the scene.',
    'other': 'Route the reviewer note to manual review; do not apply an unspecified automatic repair.',
}
REVIEW_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['tiles'],
    'properties': {'tiles': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False, 'required': ['tile', 'defects', 'note'],
        'properties': {'tile': {'type': 'integer', 'minimum': 1},
                       'defects': {'type': 'array', 'uniqueItems': True,
                                   'items': {'type': 'string', 'enum': list(DEFECTS)}},
                       'note': {'type': 'string'}}}}},
}


@dataclass(frozen=True)
class Tile:
    tile: int
    timestamp: float
    narration: str


@dataclass(frozen=True)
class VisualFinding:
    tile: int
    defects: list[str]
    note: str


@dataclass(frozen=True)
class Repair:
    tile: int
    timestamp: float
    defect: str
    recommendation: str
    note: str


def contact_sheet(video: Path | str, timeline: Path | dict, output: Path,
                  every: float = 10.0) -> list[Tile]:
    """Use build/timeline.json captions as the available narration text (not a transcript)."""
    tl = json.loads(Path(timeline).read_text(encoding='utf-8')) if not isinstance(timeline, dict) else timeline
    duration = float(tl['duration'])
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(every) or every <= 0:
        raise ValueError('duration and every must be finite and positive')
    times = {float(t) for t in np.arange(0, duration, every)}
    times.update(float(c['start']) for c in tl.get('chapters', []))
    tiles = [Tile(i + 1, t, ' '.join(c['text'] for c in tl.get('captions', [])
                                    if c['start'] <= t < c['end']))
             for i, t in enumerate(sorted(t for t in times if 0 <= t < duration))]
    width, height, cols = 320, 180, 4
    font = ImageFont.truetype(str(Path(__file__).resolve().parents[1] / 'assets/fonts/NotoSansSC-Bold.otf'), 14)
    measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    labels = []
    for tile in tiles:
        stamp = f'{int(tile.timestamp) // 60:02}:{tile.timestamp % 60:06.3f}'
        line, lines = '', []
        narration = tile.narration or ('[no active narration]' if 'captions' in tl else '[narration unavailable]')
        for char in narration:
            if char == '\n' or measure.textlength(line + char, font=font) > width - 8:
                lines.append(line)
                line = '' if char == '\n' else char
            else:
                line += char
        lines.append(line)
        labels.append(f'#{tile.tile}  {stamp}\n' + '\n'.join(lines))
    label_height = max(measure.multiline_textbbox((0, 0), text, font=font)[3] for text in labels) + 12
    sheet = Image.new('RGB', (cols * width, math.ceil(len(tiles) / cols) * (height + label_height)), 'white')
    draw = ImageDraw.Draw(sheet)
    for tile in tiles:
        raw = _run(['-v', 'error', '-ss', str(tile.timestamp), '-i', str(video), '-frames:v', '1',
                    '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2',
                    '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']).stdout
        if len(raw) != width * height * 3:
            raise ValueError(f'cannot decode contact-sheet tile {tile.tile}')
        x = ((tile.tile - 1) % cols) * width
        y = ((tile.tile - 1) // cols) * (height + label_height)
        sheet.paste(Image.frombytes('RGB', (width, height), raw), (x, y))
        text = labels[tile.tile - 1]
        draw.multiline_text((x + 4, y + height + 4), text, font=font, fill='black')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    output.with_suffix('.tiles.json').write_text(json.dumps([asdict(t) for t in tiles], indent=2, ensure_ascii=False) + '\n')
    return tiles


class Reviewer(Protocol):
    def __call__(self, sheet_png: Path, tiles: list[dict], schema: dict) -> dict | str: ...


class Repairer(Protocol):
    def __call__(self, plan: list[Repair], round_number: int) -> tuple[Path, list[Tile]]: ...


def review(sheet_png: Path, tiles: list[Tile], llm: Reviewer) -> list[VisualFinding]:
    """llm(sheet_png, tile_dicts, schema) returns a JSON object or its serialized text.

    Require every tile exactly once, including clean tiles; reject partial or invented coverage.
    """
    answer = llm(Path(sheet_png), [asdict(t) for t in tiles], REVIEW_SCHEMA)
    if isinstance(answer, str):
        answer = json.loads(answer)
    if not isinstance(answer, dict) or set(answer) != {'tiles'} or not isinstance(answer['tiles'], list):
        raise ValueError('review must contain only a tiles array')
    expected = {t.tile for t in tiles}
    if len(expected) != len(tiles):
        raise ValueError('input tile IDs must be unique')
    seen, findings = set(), []
    for entry in answer['tiles']:
        if not isinstance(entry, dict) or set(entry) != {'tile', 'defects', 'note'}:
            raise ValueError('tile requires exactly tile, defects and note')
        number, defects, note = entry['tile'], entry['defects'], entry['note']
        if type(number) is not int or number not in expected or number in seen:
            raise ValueError('invalid or duplicate tile ID')
        if (not isinstance(defects, list) or any(type(d) is not str or d not in DEFECTS for d in defects)
                or len(defects) != len(set(defects)) or not isinstance(note, str)):
            raise ValueError('invalid defects or note')
        seen.add(number)
        findings.append(VisualFinding(number, defects, note))
    if seen != expected:
        raise ValueError('review must cover every tile')
    return findings


def repairs(findings: list[VisualFinding], tiles: list[Tile]) -> list[Repair]:
    times = {t.tile: t.timestamp for t in tiles}
    return [Repair(f.tile, times[f.tile], d, REPAIRS[d], f.note) for f in findings for d in f.defects]


@dataclass
class RepairLoopResult:
    rounds: int
    sheet_png: Path
    tiles: list[Tile]
    findings: list[VisualFinding]
    history: list[list[Repair]]

    @property
    def ok(self) -> bool:
        return not any(f.defects for f in self.findings)


def repair_loop(sheet_png: Path, tiles: list[Tile], llm: Reviewer, apply: Repairer,
                max_rounds: int = 2) -> RepairLoopResult:
    """apply(repairs, round_number) returns a newly rendered (sheet_png, tiles).

    Review once initially and after each repair; preserve unresolved findings at the cap.
    No edits, renders or network are performed without the injected callbacks.
    """
    if type(max_rounds) is not int or not 0 <= max_rounds <= 2:
        raise ValueError('repair loop permits at most two rounds')
    findings = review(sheet_png, tiles, llm)
    history = []
    for round_number in range(1, max_rounds + 1):
        plan = repairs(findings, tiles)
        if not plan or any(r.defect == 'other' for r in plan):
            break
        history.append(plan)
        sheet_png, tiles = apply(plan, round_number)
        findings = review(sheet_png, tiles, llm)
    return RepairLoopResult(len(history), Path(sheet_png), tiles, findings, history)
