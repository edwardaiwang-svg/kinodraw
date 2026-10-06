"""Explicit source comparisons must reach literal native chart geometry."""
import hashlib
import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from kinodraw import ingest, script
from kinodraw.director.rules import RulesDirector
from kinodraw.director.v3.adapter import adapt
from kinodraw.director.v3.rules import from_rules
from kinodraw.engine import render, timeline
from kinodraw.engine.bold.charts import chart_svg

SOURCE = ('# Transport report\n\nThe latest survey reported that 30 percent of local trips use bicycles.'
          '\n\nThe report shows that bus trips rose from 20 percent to 25 percent this quarter.')


def board_for(source):
    board = script.build(ingest.read(source), story='showcase')
    original = [(b['display'].copy(), b['spoken'].copy()) for b in board['beats']]
    RulesDirector('en').direct(board)
    assert [(b['display'], b['spoken']) for b in board['beats']] == original
    return board


@pytest.mark.parametrize('before,after,verb,unit', [(20, 25, 'rose', 'percent'),
    (25, 20, 'fell', '%'), (2.5, 4.75, 'changed', 'percent'), (0, 100, 'increased', '%')])
def test_explicit_percentage_change_keeps_both_endpoints(before, after, verb, unit):
    board = board_for(f'# Report\n\nBus trips {verb} from {before} {unit} to {after} {unit}.')
    visual = next(v for v in board['beats'][0]['visuals'] if v['type'] == 'bars')
    assert [r['value'] for r in visual['rows']] == [before, after]
    assert [r['label']['en'] for r in visual['rows']] == ['Before', 'After']
    assert visual['unit']['en'] == unit


@pytest.mark.parametrize('source', [
    'The survey covered 20 routes and 25 buses.',
    'Bus trips were 20 percent. Bicycle trips were 25 percent.',
    'Bus trips rose from 20 percent to 15 percent.',
    'Bus trips fell from 20 percent to 25 percent.',
    'Bus trips did not rise from 20 percent to 25 percent.',
    'Bus trips never rose from 20 percent to 25 percent.',
    'Bus trips rose from 20 percent to 125 percent.',
    'Bus trips rose from 20 miles to 25 percent.',
    'Bus trips rose from 20 percent to 25 buses.',
])
def test_unrelated_invalid_or_negated_numbers_do_not_become_comparison(source):
    board = board_for('# Report\n\n' + source)
    assert not any(v['type'] == 'bars' for b in board['beats'] for v in b['visuals'])


def test_public_rules_adapter_native_chart_has_source_values_geometry_and_labels(tmp_path):
    source_hash = hashlib.sha256(SOURCE.encode()).hexdigest()
    board = board_for(SOURCE)
    first, second = board['beats']
    stat = next(v for v in first['visuals'] if v['type'] == 'stat')
    assert stat['value']['en'] == '30 percent'
    plan = from_rules(board)
    assert all(s['treatment'] == 'chart' for s in plan['scenes'])
    plan['style']['mode'] = 'hybrid'
    plan['style']['palette'].update(background='#FFFFFF', ink='#20242A', accent='#087E8B')
    board, _ = adapt(plan, board)
    saved = json.dumps({'director_v3': True, 'plan_v3': plan})
    (tmp_path / 'project.json').write_text(saved)
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
    prod = render.make_production(board, tl, 'en', tmp_path, size=(1920, 1080))
    span = prod.spans[1]
    assert not span.source_chart, 'incidental source pictures must not erase numeric chart'
    chart = next(e for e in span.motion.elements if e.kind == 'chart')
    assert chart.values == (20, 25) and chart.labels == ('Before', 'After')
    assert chart.suffix == ' percent'
    assert not any(e.preset == 'counter' for e in span.motion.elements)
    art, labels = chart_svg(chart, 2, '#087E8B', '#20242A')
    root = ET.fromstring('<svg>' + art + labels + '</svg>')
    bars = root.findall('rect')
    assert len(bars) == 2
    assert float(bars[0].get('height')) / float(bars[1].get('height')) == pytest.approx(20 / 25)
    assert [e.text for e in root.findall('text')] == ['20 percent', 'Before', '25 percent', 'After']
    image = prod.frame(span.start + 2)
    assert image.size == (1920, 1080)
    pixels = np.asarray(image).astype(int)
    # Measure the solid bar cores, excluding the renderer's faint glow halo.
    teal = (pixels[:, :, 1] > pixels[:, :, 0] + 55) & (pixels[:, :, 2] > pixels[:, :, 0] + 55)
    from scipy.ndimage import label, find_objects
    regions = find_objects(label(teal)[0])
    rectangles = sorted([r for r in regions if r and (r[0].stop-r[0].start) > 150
                         and (r[1].stop-r[1].start) > 150], key=lambda r: r[1].start)
    assert len(rectangles) == 2, 'actual native frame must contain both distinct bars'
    heights = [r[0].stop-r[0].start for r in rectangles]
    assert heights[0] / heights[1] == pytest.approx(20 / 25, abs=.015)
    assert hashlib.sha256(SOURCE.encode()).hexdigest() == source_hash
    assert (tmp_path / 'project.json').read_text() == saved
