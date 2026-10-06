"""Source geometry, bounded models, and the real project/CLI-compatible ingest path."""
import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from kinodraw import pipeline, scientific, project_zip, package
from kinodraw.engine import timeline, render
from kinodraw.mcp_server import Developer
from kinodraw.project_store import ProjectStore

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples/scientific'


def example(name='noaa-co2'):
    return json.loads((EXAMPLES / (name + '.json')).read_text())


def project(tmp_path, name='noaa-co2'):
    service = Developer(tmp_path)
    service.create_project('demo', '# Science\n\nThe supplied source shows a scientific trajectory without invented observations.', lang='en')
    saved = ProjectStore(tmp_path / 'demo').load()
    beat = saved['storyboard']['beats'][1]['id']
    (tmp_path / 'source.json').write_text(json.dumps(example(name)))
    added = service.chart_add('demo', beat, 'source.json')
    saved = ProjectStore(tmp_path / 'demo').load()
    board = saved['storyboard']
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'), credit=False)
    prod = render.make_production(board, tl, 'en', tmp_path / 'demo')
    span = next(s for s in prod.spans if beat in s.spec['beat_ids'])
    return service, saved, added, prod, span


def test_observed_coordinates_and_source_rows_unchanged():
    data = example()
    plot = scientific.ScientificPlot(data)
    box = (100, 80, 900, 480)
    geometry = plot.geometry(box)[0]
    (xmin, xmax), (ymin, ymax) = plot.domains
    # Independent inverse of the documented linear transform recovers exact supplied measurements.
    recovered = np.column_stack((xmin + (geometry[:, 0] - 100) / 800 * (xmax - xmin),
                                 ymin + (480 - geometry[:, 1]) / 400 * (ymax - ymin)))
    np.testing.assert_allclose(recovered, data['tracks'][0]['points'], atol=1e-10, rtol=0)
    raw = (EXAMPLES / 'noaa-co2-annmean-2026-10-06.txt').read_text()
    source = {int(parts[0]):float(parts[1]) for line in raw.splitlines()
              if not line.startswith('#') and (parts := line.split())}
    assert len(data['tracks'][0]['points']) == 47
    assert all(source[year] == mean for year, mean in data['tracks'][0]['points'])


def test_analytical_phase_points_and_initial_conditions():
    data = example('oscillator')
    plot = scientific.ScientificPlot(data)
    points = plot.tracks[0]['points']
    assert points[0].tolist() == [1., 0.]
    t = np.linspace(0, math.pi, 512)
    np.testing.assert_allclose(points[:, 0], np.cos(2*t), atol=1e-14)
    np.testing.assert_allclose(points[:, 1], -2*np.sin(2*t), atol=1e-14)
    np.testing.assert_allclose(points[:,0]**2+(points[:,1]/2)**2,1,atol=1e-14)


@pytest.mark.parametrize('encoding', ['series', 'path', 'scatter'])
def test_generic_observed_encodings(encoding):
    data = example()
    data['tracks'][0].update(encoding=encoding, points=[[-1, -2], [0, 3], [2, 0]])
    data['axes']['x']['unit'] = 'm'
    assert scientific.ScientificPlot(data).frame(2, 2, (640,360)).getbbox()


@pytest.mark.parametrize('name', ['noaa-co2', 'oscillator'])
def test_full_pipeline_random_access_exact_black_and_caption_margin(tmp_path, name):
    _, saved, added, prod, span = project(tmp_path, name)
    assert span.scientific and span.motion is None and span.atmos is None
    times = [span.start+.6, span.start+1.2, span.start+.6]
    frames = [np.asarray(prod.frame(t)) for t in times]
    assert np.array_equal(frames[0],frames[2])
    assert not np.array_equal(frames[0],frames[1])
    direct = np.asarray(scientific.render_plots(span.scientific, 2, 2, (640,360)))
    assert not direct[round(.76*360):].any(), 'plot marks must leave the caption region clear'
    assert not direct[:10].any() and not direct[:,:10].any(), 'exact-black outer canvas'
    assert (direct.max(axis=2)==0).mean() > .85
    source_path = tmp_path/'demo'/added['source_file']
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == added['source_sha256']
    assert saved['storyboard']['beats'][1]['visuals'][-1]['plot'] == example(name)


@pytest.mark.parametrize('change', [
    lambda d: d.pop('provenance'),
    lambda d: d['axes']['x'].pop('unit'),
    lambda d: d['tracks'][0].update(points=[]),
    lambda d: d['tracks'][0].update(points=[[0, None]]),
    lambda d: d['tracks'][0].update(points=[[0, float('nan')]]),
    lambda d: d['tracks'][0].update(points=[[0, float('inf')]]),
    lambda d: d['tracks'][0].update(points=[[0, 1e30]]),
    lambda d: d['tracks'][0].update(points=[[1, 2],[0, 3]]),
    lambda d: d['tracks'][0].update(points=[[0, 1]]*8193),
    lambda d: d['axes']['x'].update(domain=[2000, 2010]),
    lambda d: d.update(code='open("secret")'),
    lambda d: d['provenance'].update(url='file:///private/secret'),
])
def test_invalid_source_data_are_errors(change):
    data = example()
    change(data)
    with pytest.raises(ValueError): scientific.validate(data)


@pytest.mark.parametrize('change', [
    lambda d: d['model'].update(kind='exec'),
    lambda d: d['model'].update(samples=100000000),
    lambda d: d['model']['parameters'].update(omega_rad_s=10000),
    lambda d: d['model']['parameters'].update(amplitude_m=-1),
    lambda d: d['axes']['y'].update(unit='ppm'),
    lambda d: d['model'].update(seed=1),
])
def test_model_limits(change):
    data = example('oscillator')
    change(data)
    with pytest.raises(ValueError): scientific.validate(data)


def test_bad_ingest_does_not_mutate_project_or_create_asset(tmp_path):
    service = Developer(tmp_path)
    service.create_project('demo', '# Data\n\nNo missing measurements may be fabricated.', lang='en')
    store = ProjectStore(tmp_path/'demo')
    before = store.load()
    data = example(); data['tracks'][0]['points'] = []
    (tmp_path/'bad.json').write_text(json.dumps(data))
    with pytest.raises(ValueError): service.chart_add('demo', before['storyboard']['beats'][1]['id'], 'bad.json')
    assert before == store.load()
    assert not (tmp_path/'demo/assets/scientific').exists()


def test_archive_and_publish_attribution(tmp_path, monkeypatch):
    _, saved, added, prod, span = project(tmp_path, 'oscillator')
    archive = tmp_path/'science.zip'
    project_zip.export_project(tmp_path/'demo', archive)
    project_zip.import_project(archive, tmp_path/'imported')
    assert (tmp_path/'imported'/added['source_file']).read_bytes() == (tmp_path/'source.json').read_bytes()
    imported = ProjectStore(tmp_path/'imported').load()
    tl = timeline.layout(imported['storyboard'], 'en', timeline.synthetic_clips(imported['storyboard'],'en'),credit=False)
    other = render.make_production(imported['storyboard'],tl,'en',tmp_path/'imported')
    assert other.frame(span.start+1).tobytes() == prod.frame(span.start+1).tobytes()
    build=tmp_path/'build'; build.mkdir()
    for ext in ('srt','vtt'): (build/f'captions.{ext}').write_text('captions')
    folder=tmp_path/'delivery';folder.mkdir()
    monkeypatch.setattr(package,'thumbnail',lambda *a,**k:None)
    package.publish(saved['storyboard'],tl,'en',build,folder,'science',tmp_path/'demo')
    sources=json.loads((folder/'science-sources.json').read_text())['scientific_plots']
    assert sources[0]['source_sha256']==added['source_sha256']
    assert sources[0]['model']['equation']==scientific.EQUATION
    assert 'OpenStax' in (folder/'science-description.txt').read_text()


def test_luna_payload_offers_source_summary_without_raw_array(tmp_path):
    _, saved, _, _, _ = project(tmp_path)
    from kinodraw.director.v3.llm import plan_v3
    from kinodraw.director.v3.rules import from_rules
    class Provider:
        def direct_plan(self,payload,usage):
            beat=next(b for b in payload['beats'] if b.get('scientific_plots'))
            assert beat['scientific_plots'][0]['mode']=='observed'
            assert 'points' not in json.dumps(beat['scientific_plots'])
            return from_rules(saved['storyboard'])
    plan, report=plan_v3(saved['storyboard'],Provider())
    assert not report['fallback'], report
    assert plan['scenes'][1]['treatment']=='chart'


def test_multiple_plots_keep_separate_domains_and_caption_margin():
    plots=[scientific.ScientificPlot(example(n)) for n in ('noaa-co2','oscillator','noaa-co2','oscillator')]
    frame=np.asarray(scientific.render_plots(plots,2,2,(640,360)))
    assert not frame[round(.76*360):].any()
    assert frame[:180,:320].any() and frame[:180,320:].any()
    assert frame[180:260,:320].any() and frame[180:260,320:].any()
    with pytest.raises(ValueError): scientific.render_plots(plots+[plots[0]],2,2,(640,360))


def test_whiteboard_selection_falls_back_to_source_narration(tmp_path):
    _,saved,_,_,_=project(tmp_path)
    cfg=saved['settings'];cfg['plan_v3']['style']['mode']='whiteboard'
    for scene in cfg['plan_v3']['scenes']:scene['treatment']='whiteboard'
    ProjectStore(tmp_path/'demo').save(saved['storyboard'],cfg,saved['revision'])
    board=saved['storyboard']
    tl=timeline.layout(board,'en',timeline.synthetic_clips(board,'en'),credit=False)
    prod=render.make_production(board,tl,'en',tmp_path/'demo')
    assert type(prod).__name__=='Production'
    assert any('scientific plot withheld' in w for w in prod.warnings)
    expected=' '.join(board['beats'][1]['spoken']['en'].split())
    assert any(e.beat==board['beats'][1]['id'] and
               ' '.join(' '.join(getattr(e.drawing,'lines',[])).split())==expected for e in prod.els)


def test_analytical_time_projection():
    data=example('oscillator');data['model']['projection']='time'
    data['axes']={'x':{'label':'Time','unit':'s'},'y':{'label':'Displacement','unit':'m'}}
    plot=scientific.ScientificPlot(data)
    assert plot.tracks[0]['encoding']=='series'
    assert plot.tracks[0]['points'][0].tolist()==[0.,1.]
    assert plot.tracks[0]['points'][-1,0]==math.pi


def test_scientific_source_appendix_promoted_from_render_stage(tmp_path, monkeypatch):
    _,saved,_,_,_=project(tmp_path)
    stage=tmp_path/'stage'
    pipeline._copy_project(tmp_path/'demo',stage)
    stem=pipeline._output_stem(saved['storyboard'],saved['settings'])
    appendix=stage/(stem+'-sources.json')
    appendix.write_text('{"scientific_plots":[]}')
    pairs=[]
    monkeypatch.setattr(pipeline,'_publish_outputs',lambda outputs,*a:pairs.extend(outputs))
    pipeline._commit_outputs(stage,tmp_path/'demo',None)
    assert (appendix,tmp_path/'demo'/appendix.name) in pairs
