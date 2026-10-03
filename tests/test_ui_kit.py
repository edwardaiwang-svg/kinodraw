"""Promo interface pieces render with the bundled fonts only, in English and Chinese."""
import numpy as np

from kinodraw.engine.collage import ui_kit as ui


def _ink(img):
    rgb = np.asarray(img.convert('RGB'), np.int16)
    alpha = np.asarray(img.getchannel('A')) > 0
    return int((alpha & (rgb.sum(axis=2) < 200)).sum())              # dark text/outline pixels


def test_every_piece_renders():
    docs = [ui.chat_bubble('who else is coming?', name='Max'), ui.badge(40), ui.phone('Friends', 'Max, Lara'),
            ui.form_card('What do you want to do?', [('Event title', 'Werewolf night', True)]),
            ui.button("I'm in!"), ui.button("Can't make it", style='secondary'), ui.link_chip('friendr.nl'),
            ui.label('no app needed'), ui.stamp("IT'S ON!"), ui.traffic_light('green'), ui.slots(8, 5, 6), ui.mark(True)]
    for doc in docs:
        img = ui.raster(doc)
        assert img.mode == 'RGBA' and img.width > 40 and img.height > 40


def test_chinese_text_is_drawn_not_blank():
    assert _ink(ui.raster(ui.label('电影之夜', lang='zh'))) > 400           # the handwriting face (Doodle Kai)
    assert _ink(ui.raster(ui.chat_bubble('周六？还有谁来？', lang='zh'))) > 400


def test_text_sets_the_width_and_the_chatter_bank_is_fixed():
    short, long = ui.raster(ui.button('Go')), ui.raster(ui.button('Create your first event'))
    assert long.width > short.width + 200
    assert ui.chatter('en', 3, 4) == ui.chatter('en', 3, 4) and all(line in ui.CHATTER['en'] for line in ui.chatter('en', 9, 6))
