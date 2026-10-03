"""A 4 x 3 contact sheet of the motion kit (doodlestudio/engine/motion.py), each cell at 1:1 pixel scale, to eyeball
the collage and bold looks: the paper kinds, popping die-cut stickers, torn paper, confetti, an iris and a wipe,
slam frames, and particles assembling inside a ring of text.

  python scripts/motion_contact_sheet.py OUT.png
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from doodlestudio.engine import ink, motion as m  # noqa: E402

W, H = 640, 360
GUTTER = 4
FLUENT = ink.ASSETS / 'doodles' / 'fluent'


def paper(kind, key):
    return m.paper_texture((W, H), kind, key).convert('RGBA')


def emoji(name, box):
    return ink._svg_layers(str(FLUENT / f'fl_{name}.svg'), box, box)[0]


def word(text, size, color=ink.INK):
    f = ink.font('ui', size)
    img = Image.new('RGBA', (int(f.getlength(text)) + 60, size + 60), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((img.width / 2, img.height / 2), text, font=f, fill=color, anchor='mm')
    return img


def label(cell, text):
    f = ink.font('ui', 20)
    chip = Image.new('RGBA', (int(f.getlength(text)) + 20, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(chip)
    d.rounded_rectangle((0, 0, chip.width - 1, 31), 9, fill=(27, 27, 27, 200))
    d.text((10, 4), text, font=f, fill=(255, 255, 255, 255))
    cell.alpha_composite(chip, (10, 10))
    return cell


def stickers():
    """Three stickers at three moments of a pop: rising (shadow lifted), overshooting, settled."""
    cell = paper('kraft', 'stickers')
    poses = (('rocket', 120, 200, .07, -9), ('light_bulb', 320, 190, .17, 4), ('trophy', 520, 205, .6, -3))
    for name, x, y, t, rot in poses:
        sticker = m.die_cut(emoji(name, 170))
        p = m.pop(t, 0)
        lift = p['lift']                                  # the shadow drops further away while it is in the air
        m.Sprite(m.shadow_only(sticker)).draw(cell, x + 4 + 10 * lift, y + 6 + 16 * lift, p['scale'], rot, p['alpha'])
        m.Sprite(sticker).draw(cell, x, y - 12 * lift, p['scale'], rot, p['alpha'])
    return label(cell, 'die_cut + shadow_only + pop: rising, overshoot, settled')


def torn():
    cell = paper('cream', 'torn')
    kraft = m.torn_edge(m.paper_texture((W, H), 'kraft', 'strip').convert('RGBA').crop((0, 0, 540, 130)), 'kraft', 7)
    blue = m.torn_edge(Image.new('RGBA', (430, 110), (59, 110, 190, 255)), 'blue')
    for img, x, y, rot in ((kraft, 330, 150, -4), (blue, 300, 262, 3)):
        m.Sprite(m.drop_shadow(img, (3, 5), 5, .3)).draw(cell, x, y, rotation=rot)
    return label(cell, 'torn_edge: kraft and blue paper')


def confetti():
    """A burst at the bottom of a 1080p frame, 0.5 s in; the cell is the middle of the frame at 1:1."""
    cell = paper('cream', 'confetti')
    layer = Image.new('RGBA', (2 * W, 2 * H), (0, 0, 0, 0))           # drawn at 2x, then smoothed down
    d = ImageDraw.Draw(layer)
    for x, y, a, w, h, color, alpha in m.confetti('sheet', 260, (960, 1080), .5):
        x, y = x - (960 - W / 2), y - 330
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        corners = [(2 * (x + c * dx - s * dy), 2 * (y + s * dx + c * dy))
                   for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]
        d.polygon(corners, fill=color + (round(255 * alpha),))
    cell.alpha_composite(layer.resize((W, H), Image.LANCZOS))
    return label(cell, 'confetti: 260 bits, 0.5 s after the burst')


def iris():
    old, new = paper('kraft', 'iris'), paper('blue_wash', 'iris')
    m.Sprite(m.drop_shadow(m.die_cut(emoji('globe_showing_americas', 190)))).draw(new, W / 2, H / 2 + 8)
    return label(Image.composite(new, old, m.iris_mask((W, H), (W / 2, H / 2 + 8), 150)), 'iris_mask: a match-cut')


def wipe():
    old, new = paper('lined', 'wipe'), paper('kraft', 'wipe')
    return label(Image.composite(new, old, m.wipe_mask((W, H), .5, 25, 40)), 'wipe_mask: 25 degrees, soft 40')


def slam_frames():
    """Frames 1, 2, 3 and 6 of a slam, one per quarter of the cell."""
    cell = paper('cream', 'slam')
    big = word('SLAM!', 96, ink.SECTION_COLORS['red'] + (255,))
    for k, f in enumerate((1, 2, 3, 6)):
        p = m.slam(f / 30, 0)
        img = big.filter(ImageFilter.GaussianBlur(p['blur_px'] / 2)) if p['blur_px'] > .5 else big
        x, y = (k % 2) * W / 2 + W / 4, (k // 2) * H / 2 + H / 4 + 4
        m.Sprite(img).draw(cell, x, y, p['scale'] * .7, alpha=p['alpha'])
        m.Sprite(word(f'frame {f}', 20, (85, 96, 106, 255))).draw(cell, x, y + 52)
    return label(cell, 'slam: scale 1.35 -> 1, blur 28 px -> 0')


def assemble_ring():
    cell = paper('cream', 'ring')
    glyph = Image.new('L', (W, H), 0)
    f = ink.font('ui', 190)
    center = (W / 2, H / 2 + 12)
    ImageDraw.Draw(glyph).text(center, 'Go', font=f, fill=255, anchor='mm')
    dst = m.sample_points(glyph, 900, 'glyph')
    src = m.seeded('scatter').uniform((0, 0), (W, H), (900, 2))
    d = ImageDraw.Draw(cell)
    colors = list(ink.SECTION_COLORS.values())
    for k, (x, y) in enumerate(m.assemble(src, dst, .6, seed_key='glyph')):
        d.ellipse((x - 2.2, y - 2.2, x + 2.2, y + 2.2), fill=colors[k % len(colors)] + (255,))
    for ch, x, y, a in m.ring_layout('MOTION KIT • DOODLE STUDIO • ', center, 145, .8, 25):
        m.Sprite(word(ch, 24)).draw(cell, x, y, rotation=a)
    return label(cell, 'assemble into a glyph + ring_layout')


def main(out):
    kinds = ('cream', 'kraft', 'grid', 'lined', 'blue_wash')
    cells = [label(paper(kind, 0), f'paper_texture: {kind}') for kind in kinds]
    cells += [stickers(), torn(), confetti(), iris(), wipe(), slam_frames(), assemble_ring()]
    sheet = Image.new('RGB', (4 * W + 5 * GUTTER, 3 * H + 4 * GUTTER), (27, 27, 27))
    for k, cell in enumerate(cells):
        sheet.paste(cell.convert('RGB'), (GUTTER + (k % 4) * (W + GUTTER), GUTTER + (k // 4) * (H + GUTTER)))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f'wrote {out}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
