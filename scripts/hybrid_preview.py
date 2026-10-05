#!/usr/bin/env python3
"""Offline production acceptance: source beats, tone clips, saved plan, both worker modes."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kinodraw import pipeline, voice
from kinodraw.audio import mix
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render
from kinodraw.qa.probes import probe

SOURCE = '''# Hybrid field notes

A book holds an idea.

Ideas move and connect.

Mara, a tigress, nudged Pendo, a lion cub. Kojo, a male lion with a massive black mane, roared at the hyenas.

Thick fog held a shooting star.
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    project = args.output
    project.mkdir(parents=True, exist_ok=True)
    board = pipeline.new_project(SOURCE, project, direction={'story': 'story'}, director_v3=True, credit=False)
    plan = from_rules(board)
    plan['style'].update(mode='hybrid', motion_floor='lively', music_mood='warm', tempo_bpm=96)
    # A short book beat opens with the plan's animated prop; source spans stay untouched.
    plan['style']['palette'].update(background='#ECEBE6', ink='#1B1B1B')
    treatments = ('motion', 'kinetic_type', 'character', 'atmosphere')
    for i, scene in enumerate(plan['scenes']):
        scene.update(treatment=treatments[i], transition_in=('cut', 'wipe', 'iris', 'zoom_through')[i])
        if i == 1:
            scene['text'] = {'kind': 'kinetic', 'ref': scene['beat_ids'][0]}
    plan['scenes'][0]['elements'] = [{'kind': 'picture', 'ref': 'book_stack'}]
    calls = []
    class Provider:
        name = 'offline-fixture'
        def direct_plan(self, payload, usage):
            calls.append(1)
            return copy.deepcopy(plan)
    cfg = pipeline.settings(project)
    cfg['series_bible'] = {'cast': copy.deepcopy(plan['cast'])}
    # Showcase override is in the project, never in engine code.
    mother = next(c for c in cfg['series_bible']['cast'] if c['name'] == 'Mara')
    mother.update(species='tigress', marks=['stripes'])
    pipeline._save(project / 'project.json', cfg)
    report = pipeline.direct_v3(project, Provider())
    assert not report['fallback'], report
    board = pipeline.storyboard(project)
    clips = {}
    (project / 'voice').mkdir(exist_ok=True)
    for b in board['beats']:
        text = b['spoken']['en']
        duration = max(1.0, len(text) / 45)
        t = np.arange(round(duration * mix.SR)) / mix.SR
        pcm = .1 * np.sin(2 * np.pi * (220 + 17 * len(clips)) * t)
        ramp = min(round(.03 * mix.SR), len(t) // 2)
        pcm[:ramp] *= np.linspace(0, 1, ramp)
        pcm[-ramp:] *= np.linspace(1, 0, ramp)
        wav = project / 'voice' / f'{b["id"]}.wav'
        mix.write_wav(wav, pcm)
        clips[b['id']] = voice.Clip(wav, duration, np.linspace(0, duration, len(text)).tolist())
    tl = pipeline.build_audio(project, clips)
    prod = render.make_production(board, tl, 'en', project)
    assert type(prod).__name__ == 'HybridProduction'
    # Independent reconstruction matches at and around the actual two-worker split.
    split = round(round(tl['duration'] * render.FPS) / 2) / render.FPS
    reconstructed = render.make_production(json.loads((project / 'storyboard.json').read_text(encoding='utf-8')),
                                           json.loads((project / 'build/timeline.json').read_text(encoding='utf-8')), 'en', project)
    hashes = {}
    for t in (split - 1/30, split, split + 1/30):
        a, b = prod.frame(t).convert('RGB').tobytes(), reconstructed.frame(t).convert('RGB').tobytes()
        assert a == b
        hashes[str(t)] = hashlib.sha256(a).hexdigest()
    command = [sys.executable, '-m', 'kinodraw.engine.render', '--project', str(project),
               '--episode', str(project / 'storyboard.json'), '--lang', 'en',
               '--timeline', str(project / 'build/timeline.json'), '--stills', ','.join(hashes),
               '--preview-dir', str(project / 'worker-stills')]
    worker = subprocess.run(command, capture_output=True, text=True, check=True)
    for time_string, expected in hashes.items():
        t = float(time_string)
        frame = Image.open(project / 'worker-stills' / f'en-{t:07.2f}.png').convert('RGB')
        assert hashlib.sha256(frame.tobytes()).hexdigest() == expected
    (project / 'worker-split-hashes.json').write_text(json.dumps(
        {'worker_exit': worker.returncode, 'hashes': hashes}, indent=2), encoding='utf-8')
    frames = []
    scene_hashes = []
    for span in prod.spans:
        t = span.start + min(1., (span.end - span.start) * .65)
        frame = prod.frame(t).convert('RGB')
        scene_hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
        frame.save(project / f'{span.spec["treatment"]}.png')
        thumb = frame.resize((480, 270))
        ImageDraw.Draw(thumb).text((10, 10), span.spec['treatment'], fill='#ff5555')
        frames.append(thumb)
    assert len(set(scene_hashes)) == len(treatments)
    sheet = Image.new('RGB', (960, 540), 'white')
    for i, frame in enumerate(frames):
        sheet.paste(frame, ((i % 2) * 480, (i // 2) * 270))
    sheet.save(project / 'treatments.jpg')
    renders = {}
    for workers in (1, 2):
        started = time.monotonic()
        path = pipeline.render(project, workers=workers)
        shutil.copyfile(path, project / f'workers-{workers}.mp4')
        renders[str(workers)] = {'seconds': time.monotonic() - started}
    # Decode both movies to hashes: segmentation can change H.264 rounding, so record exact equality too.
    decoded = []
    for workers in (1, 2):
        command = [render.FFMPEG, '-v', 'error', '-i', str(project / f'workers-{workers}.mp4'),
                   '-f', 'framemd5', '-']
        result = subprocess.run(command, capture_output=True, check=True)
        (project / f'workers-{workers}.framemd5').write_bytes(result.stdout)
        decoded.append([line.split(b',')[-1].strip() for line in result.stdout.splitlines() if not line.startswith(b'#')])
    qa = pipeline.finish(project)
    assert qa['ok'], qa
    video = Path(qa['video'])
    score = json.loads((project / 'build/score.json').read_text(encoding='utf-8'))
    assert np.allclose(score['beats'], prod.score_beats)
    measured = probe(video, tl, beat_grid=score['beats']).to_dict()
    (project / 'probe.json').write_text(json.dumps(measured, indent=2), encoding='utf-8')
    pipeline.direct_v3(project, Provider())
    assert len(calls) == 1
    evidence = {'qa': qa, 'probe': measured, 'renders': renders, 'provider_calls': len(calls),
                'source_split_hashes': hashes, 'decoded_identical': decoded[0] == decoded[1],
                'scene_hashes': scene_hashes, 'warnings': prod.warnings,
                'source_spans': [[s.start, s.end] for s in prod.spans],
                'visual_joins': [s.join for s in prod.spans], 'score_beats': score['beats']}
    (project / 'acceptance.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    assert measured['ok'], measured
    print(json.dumps({'movie': str(video), 'duration': tl['duration'], 'calls': len(calls),
                      'package_ok': measured['package_ok'], 'decoded_identical': decoded[0] == decoded[1]}))

if __name__ == '__main__':
    main()
