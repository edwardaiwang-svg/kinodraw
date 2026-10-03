"""Manually chosen pictures stay local and use the existing storyboard and drawing flow."""
import base64
import http.client
import io
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kinodraw import cli, library, pipeline
from kinodraw.director.validate import validate
from kinodraw.engine import ink, render as renderer, skin, timeline
from kinodraw.engine.collage.stickers import sticker
from kinodraw.studio import server

FIX = Path(__file__).parent / 'fixtures'
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><path d="M10 15 H190 V85 H10 Z" fill="none" stroke="black" stroke-width="8"/></svg>'


def picture_bytes(fmt='PNG', color=(240, 30, 80), size=(200, 100)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, fmt)
    return buf.getvalue()


@pytest.fixture
def project(tmp_path):
    path = tmp_path / 'Honey'
    board = pipeline.new_project(FIX / 'tiny.md', path)
    folder = path / library.PICTURES
    folder.mkdir()
    (folder / 'logo.png').write_bytes(picture_bytes())
    (folder / 'lines.svg').write_text(SVG, encoding='utf-8')
    beat = next(b for b in board['beats'] if b['kind'] == 'narration')
    beat['visuals'] = [{'id': 'pictures', 'type': 'cluster', 'items': [
        {'doodle': 'own:logo.png'}, {'doodle': 'own:lines.svg'}]}]
    (path / 'storyboard.json').write_text(json.dumps(board), encoding='utf-8')
    return path, board, beat


@pytest.mark.parametrize('did', ['own:', 'own:.', 'own:..', 'own:../x.png', 'own:/etc/hosts',
                                 'own:sub/x.png', 'own:..\\x.png', 'own:.hidden.png', 'own:x.gif'])
def test_own_path_rejects_bad_names(project, did):
    path, _, _ = project
    with pytest.raises(ValueError, match='pictures folder'):
        library.own_path(did, path)
    assert library.resolve(did, path) is None


def test_resolve_and_symlink_containment(project, tmp_path):
    path, _, _ = project
    assert library.resolve('own:logo.png', path) == path / 'pictures/logo.png'
    assert library.resolve('own:logo.png') is None
    outside = tmp_path / 'outside.png'
    outside.write_bytes(picture_bytes())
    (path / 'pictures/link.png').symlink_to(outside)
    with pytest.raises(ValueError, match='pictures folder'):
        library.own_path('own:link.png', path)
    assert library.resolve('own:link.png', path) is None


def test_validate_own_pictures_and_plain_messages(project):
    path, board, beat = project
    assert validate(board, path)['ok']
    assert 'project folder' in ' '.join(validate(board)['errors'])
    beat['visuals'][0]['items'][0]['doodle'] = 'own:../../x.png'
    assert 'pictures folder' in ' '.join(validate(board, path)['errors'])
    beat['visuals'][0]['items'][0]['doodle'] = 'own:cat.png'
    errors = validate(board, path)['errors']
    assert any('cat.png' in e and 'missing' in e for e in errors)
    assert all('Traceback' not in e and 'Error:' not in e for e in errors)
    beat['visuals'][0]['items'].append({'doodle': 'own:cat.png'})
    assert len(library.missing_pictures(board, path)) == 1


def test_missing_picture_stops_render_cli_and_still(project, monkeypatch):
    path, board, _ = project
    (path / 'pictures/logo.png').unlink()
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    (path / 'build').mkdir()
    (path / 'build/timeline.json').write_text(json.dumps(tl), encoding='utf-8')
    monkeypatch.setattr(renderer, 'make_production', lambda *a, **kw: pytest.fail('frame work started'))
    with pytest.raises(ValueError, match='logo.png') as error:
        pipeline.render(path)
    assert 'Traceback' not in str(error.value) and 'Error:' not in str(error.value)
    for args in (['render', str(path)], ['render', str(path), '--stills', '1']):
        with pytest.raises(SystemExit) as error:
            cli.main(args)
        assert 'logo.png' in str(error.value) and 'Traceback' not in str(error.value)
    monkeypatch.setattr(server, 'projects_root', lambda: path.parent)
    with pytest.raises(ValueError, match='logo.png'):
        server.still(path.name, None)


def test_reveal_wipe_pen_fit_cache_and_final_picture(project):
    path, _, _ = project
    drawing = ink.picture_drawing(path / 'pictures/logo.png', (600, 400))
    assert isinstance(drawing, ink.RevealDrawing) and drawing.own
    assert drawing.size == (400, 200)  # no more than 2x upscaling
    assert drawing.duration == drawing.draw_time + .05
    assert drawing.state(-1) == (None, None, False)
    elapsed = drawing.draw_time / 2
    image, pen, down = drawing.state(elapsed)
    alpha = np.asarray(image.getchannel('A'))
    assert alpha[:, :180].min() == 255 and alpha[:, 230:].max() == 0
    assert abs(pen[0] - (drawing.size[0] - 24) / 2) < 1 and down
    assert drawing.size[1] * .12 <= pen[1] <= drawing.size[1] * .88
    assert drawing.state(elapsed)[0] is image
    full, pen, down = drawing.state(drawing.duration)
    assert full.tobytes() == drawing.image.tobytes() and pen is None and not down
    again = ink.picture_drawing(path / 'pictures/logo.png', (600, 400))
    assert again.image.tobytes() == full.tobytes()
    assert ink.picture_drawing(path / 'pictures/logo.png', (100, 100)).size == (100, 50)
    assert ink.RevealDrawing(Image.new('RGBA', (600, 100))).draw_time == 1.6
    (path / 'pictures/logo.png').write_bytes(picture_bytes(color=(10, 20, 30)))
    assert ink.picture_drawing(path / 'pictures/logo.png', (600, 400)).image.tobytes() != full.tobytes()


def test_phone_jpeg_is_upright_and_rasters_keep_colours(project):
    path, _, _ = project
    phone = path / 'pictures/phone.jpg'
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (80, 40), (20, 180, 70)).save(phone, exif=exif)
    drawing = ink.picture_drawing(phone, (80, 80))
    assert drawing.size == (40, 80)
    for look in ('whiteboard', 'chalkboard', 'notebook', 'collage'):
        assert skin.for_look(look).dress(drawing) is drawing
        assert drawing.state(drawing.duration)[0].tobytes() == drawing.image.tobytes()
    assert sticker('own:phone.jpg', 80, str(path)) is not None


def test_svg_traces_or_falls_back_to_reveal_and_unreadable_is_plain(project):
    path, _, _ = project
    assert isinstance(ink.picture_drawing(path / 'pictures/lines.svg', (200, 100)), ink.PathDrawing)
    embedded = base64.b64encode(picture_bytes()).decode()
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="200" height="100"><image width="200" height="100" xlink:href="data:image/png;base64,{embedded}"/></svg>'
    file = path / 'pictures/image.svg'
    file.write_text(svg, encoding='utf-8')
    drawing = ink.picture_drawing(file, (200, 100))
    assert isinstance(drawing, ink.RevealDrawing) and drawing.image.getbbox()
    broken = path / 'pictures/broken.png'
    broken.write_text('not a picture')
    with pytest.raises(ValueError, match='KinoDraw couldn’t open the picture “broken.png”'):
        ink.picture_drawing(broken, (200, 100))


@pytest.mark.parametrize('look', ['whiteboard', 'chalkboard', 'notebook'])
def test_production_reveals_own_cluster_pictures(project, look):
    path, board, _ = project
    board['look'] = look
    tl = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    prod = renderer.make_production(board, tl, 'en', path)
    own = [e for e in prod.ctx.elements if getattr(e.drawing, 'own', False)]
    assert len(own) == 2 and not any('pictures' in w or 'own:' in w for w in prod.warnings)
    for element in own:
        assert element.start is not None and not element.skipped
        left = int(element.x) - 20
        region = (20, int(element.y), 20 + element.w, int(element.y) + element.h)
        paper = np.asarray(prod.skin.background().crop(region))
        marks = []
        for fraction in (.25, .6, 1.1):
            frame = prod.view(element.start + element.duration * fraction, left, hand=False)
            marks.append(np.any(np.asarray(frame.crop(region)) != paper, axis=2).sum())
        assert 0 < marks[0] < marks[1] < marks[2], (look, marks)
        assert np.asarray(element.state(element.end + .01)[0]).tobytes() == np.asarray(
            element.drawing.state(element.drawing.duration)[0]).tobytes()


@pytest.fixture
def studio(project, monkeypatch):
    path, _, _ = project
    monkeypatch.setattr(server, 'projects_root', lambda: path.parent)
    httpd, url = server.serve(0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(route, data=None, method=None, binary=False):
        if data is not None and len(data) > library.PICTURE_MAX:
            # A server must reject the declared size before it reads the body. Wait for that response
            # instead of having urllib turn the early rejection into a connection-reset exception.
            conn = http.client.HTTPConnection('127.0.0.1', httpd.server_address[1], timeout=10)
            conn.putrequest('POST', route)
            conn.putheader('X-Studio-Token', server.Handler.token)
            conn.putheader('Content-Length', str(len(data)))
            conn.putheader('Expect', '100-continue')
            conn.endheaders()
            reply = conn.getresponse()
            result = reply.status, json.loads(reply.read()), reply.headers.get_content_type()
            conn.close()
            return result
        req = urllib.request.Request(url + route.lstrip('/'), data=data, method=method,
                                     headers={'X-Studio-Token': server.Handler.token})
        try:
            with opener.open(req, timeout=10) as reply:
                body = reply.read()
                return reply.status, body if binary else json.loads(body), reply.headers.get_content_type()
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read()), error.headers.get_content_type()
    yield call
    httpd.shutdown()
    httpd.server_close()


def test_studio_upload_list_collision_types_and_doodle_route(studio, project):
    path, _, _ = project
    for filename, data, expected, content_type in [
        ('My%20Logo.PNG', picture_bytes(), 'My-Logo.png', 'image/png'),
        ('photo.jpg', picture_bytes('JPEG'), 'photo.jpg', 'image/jpeg'),
        ('photo.jpeg', picture_bytes('JPEG'), 'photo.jpeg', 'image/jpeg'),
        ('lines.svg', SVG.encode(), 'lines.svg', 'image/svg+xml'),
    ]:
        code, result, _ = studio(f'/api/projects/Honey/pictures?filename={filename}', data)
        assert code == 200 and result['id'] == 'own:' + expected
        assert (path / 'pictures' / expected).read_bytes() == data
        assert studio(f'/api/projects/Honey/pictures?filename={filename}', data)[1]['id'] == result['id']
        code, body, ctype = studio(f'/doodle/own%3A{expected}.svg?project=Honey&token={server.Handler.token}', binary=True)
        assert code == 200 and body == data and ctype == content_type
    different = studio('/api/projects/Honey/pictures?filename=My%20Logo.PNG', picture_bytes(color=(20, 30, 40)))
    assert different[1]['id'] == 'own:My-Logo-2.png'
    listed = studio('/api/projects/Honey/pictures')[1]
    assert {'id': 'own:My-Logo-2.png', 'name': 'My-Logo-2.png'} in listed
    assert [p['name'] for p in listed] == sorted(p['name'] for p in listed)
    assert all(p['id'].startswith('own:') for p in listed)
    assert not list((path / 'pictures').glob('.upload-*'))


@pytest.mark.parametrize('filename,data,phrase', [
    ('big.png', b'x' * (library.PICTURE_MAX + 1), 'too big (over 10 MB)'),
    ('notes.png', b'notes', 'isn’t a picture KinoDraw can open'),
    ('notes.gif', b'notes', 'Choose a PNG, JPG or SVG picture.'),
    ('empty.png', b'', 'is empty'),
    ('wrong.jpg', picture_bytes(), 'isn’t a picture KinoDraw can open'),
    ('bad.svg', b'<svg nope', 'isn’t a picture KinoDraw can open'),
], ids=['large', 'text', 'gif', 'empty', 'wrong-type', 'broken-svg'])
def test_studio_rejects_bad_uploads_plainly(studio, filename, data, phrase):
    code, result, _ = studio(f'/api/projects/Honey/pictures?filename={filename}', data)
    assert code == 400 and phrase in result['error']
    assert 'Traceback' not in result['error'] and 'Error:' not in result['error']


def test_upload_rejects_large_body_before_read_and_stays_offline(project, studio, monkeypatch):
    path, _, _ = project
    monkeypatch.setattr(server, 'projects_root', lambda: path.parent)

    class Unreadable:
        def read(self, *args):
            pytest.fail('oversized body was read')

    with pytest.raises(ValueError, match='too big'):
        server.save_picture('Honey', 'big.png', Unreadable(), library.PICTURE_MAX + 1)
    connect = socket.socket.connect

    def local_only(sock, address):
        assert address[0] == '127.0.0.1', 'outbound socket opened'
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', local_only)
    data = picture_bytes()
    for filename, data in [('offline.png', data), ('offline.jpg', picture_bytes('JPEG')), ('offline.svg', SVG.encode())]:
        code, result, _ = studio(f'/api/projects/Honey/pictures?filename={filename}', data)
        assert code == 200 and result['id'] == 'own:' + filename


def test_studio_storyboard_rejects_escape_and_still_missing_is_plain(studio, project):
    path, board, beat = project
    beat['visuals'][0]['items'][0]['doodle'] = 'own:../../x.png'
    code, result, _ = studio('/api/projects/Honey/storyboard', json.dumps(board).encode(), 'PUT')
    assert code == 200 and result['ok'] is False and 'pictures folder' in ' '.join(result['errors'])
    (path / 'pictures/logo.png').unlink()
    code, result, _ = studio('/api/projects/Honey/still')
    assert code == 400 and 'logo.png' in result['error'] and 'Error:' not in result['error']


def test_catalog_never_offers_own_pictures():
    assert not any(did.startswith('own:') for did in library.catalog())


def test_search_never_offers_own_pictures():
    from kinodraw.director import match
    repo, files = match.EMBED_FILES['en']
    folder = match.CACHE / f"{repo.split('/')[1]}-{repo.split('/')[3][:8]}"
    if not all((folder / name).is_file() for name in files):
        pytest.skip('doodle-search model is not installed')
    assert not any(item['id'].startswith('own:') for item in server.search_doodles('cat', 'en'))


def test_svg_sized_unlike_its_viewbox_traces_inside_the_picture(project):
    path, _, _ = project
    file = path / 'pictures/scaled.svg'
    file.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 100 50">'
                    '<path d="M5 5 H95 V45 H5 Z" fill="none" stroke="black" stroke-width="4"/></svg>', encoding='utf-8')
    drawing = ink.picture_drawing(file, (200, 100))
    points = np.concatenate(drawing.polys)
    assert drawing.color.size == (200, 100)
    assert points[:, 0].max() <= 200 and points[:, 1].max() <= 100
    assert points[:, 0].max() > 150 and points[:, 1].max() > 75


@pytest.mark.parametrize('name', ['wide.png', 'wide.svg'])
def test_wide_own_picture_sticker_fits_its_spot(project, name):
    path, _, _ = project
    file = path / 'pictures' / name
    if name.endswith('.png'):
        file.write_bytes(picture_bytes(size=(1000, 100)))
    else:
        file.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="100">'
                        '<rect width="1000" height="100" fill="#3a7"/></svg>', encoding='utf-8')
    img = sticker('own:' + name, 230, str(path))
    border = max(8, round(230 * .06)) + 2      # die_cut grows the canvas by border + 2 on every side
    assert img.width <= 230 + 2 * border and img.height <= 230 + 2 * border
