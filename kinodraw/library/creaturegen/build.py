"""Enumerate every preset (variant x pose x facing, plus face close-ups), render SVGs and tag entries."""
from __future__ import annotations

from . import faces, genes
from .figure import Canvas, Rendered

POSE_EN = {
    'stand': ('standing', ('standing', 'side view')),
    'walk1': ('walking (stride A)', ('walking', 'walk')),
    'walk2': ('walking (stride B)', ('walking', 'walk')),
    'run': ('running', ('running', 'run', 'chase')),
    'sit': ('sitting', ('sitting', 'sit')),
    'lie': ('lying down', ('lying down', 'resting')),
    'sleep': ('sleeping', ('sleeping', 'asleep')),
    'roar': ('roaring with its mouth open', ('roaring', 'roar', 'calling')),
    'shout': ('shouting with mouth open', ('shouting', 'shout', 'calling')),
    'look_up': ('looking up', ('looking up',)),
    'scared': ('crouching, scared', ('scared', 'afraid', 'crouching', 'frightened')),
    'carry': ('carrying something', ('carrying', 'carry')),
    'fly': ('flying with wings spread', ('flying', 'fly')),
    'fly2': ('flying, wings swept back', ('flying', 'fly')),
    'swim1': ('swimming', ('swimming', 'swim')),
    'swim2': ('swimming (tail sweep)', ('swimming', 'swim')),
    'swim': ('swimming', ('swimming', 'swim')),
    'jump': ('jumping', ('jumping', 'jump', 'leaping')),
    'wave': ('waving', ('waving', 'wave', 'hello')),
}
POSE_ZH = {'stand': '站立', 'walk1': '行走', 'walk2': '行走', 'run': '奔跑', 'sit': '坐着', 'lie': '趴着',
           'sleep': '睡觉', 'roar': '吼叫', 'shout': '喊叫', 'look_up': '抬头看', 'scared': '害怕', 'carry': '叼着东西',
           'fly': '飞翔', 'fly2': '飞翔', 'swim': '游泳', 'swim1': '游泳', 'swim2': '游泳', 'jump': '跳跃', 'wave': '挥手'}
EXPR_EN = {'neutral': 'calm', 'scared': 'wide-eyed and scared', 'determined': 'determined, brows lowered',
           'sad': 'sad, with a tear', 'happy': 'happy, smiling'}
EXPR_ZH = {'neutral': '平静', 'scared': '害怕', 'determined': '坚定', 'sad': '难过', 'happy': '开心'}
FACING_EN = {'r': 'facing right', 'l': 'facing left', 'f': 'front view'}


def builders():
    from . import quad
    out = {'quad': lambda g, pose: quad.build(g, quad.POSES[pose])}
    try:
        from . import primate
        out['primate'] = primate.build
    except ImportError:
        pass
    for name in ('frog', 'insect', 'bird', 'fish', 'reptile', 'human', 'hedgehog', 'snail'):
        try:
            mod = __import__(f'{__package__}.{name}', fromlist=['build'])
            out[name] = mod.build
        except ImportError:
            pass
    return out


def _canvas(fig, long_side=300.0):
    b = fig.bounds()
    w, h = b[2] - b[0], b[3] - min(0.0, b[1])
    if w > 2.2 * h:         # long, low animals: widen the picture so the 200 px minimum height is not mostly empty
        long_side = min(600.0, 176.0 * w / h + 24.0)
    return Canvas((b[0], min(0.0, b[1]), b[2], b[3]), long_side=long_side)


def render_variant(v):
    """Yield (id, svg text, meta) for every preset of one variant."""
    plan = builders()[v.plan]
    g = genes.individual(v.genes, v.key, amount=v.jitter) if v.genes is not None else None
    for pose in v.poses:
        fig = plan(g, pose)
        canvas = _canvas(fig)
        rendered = Rendered(fig, canvas)
        for facing in ('r', 'l'):
            pid = f'cr_{v.key}_{pose}_{facing}'
            meta = {'pose': pose, 'facing': facing, 'size': [canvas.W, canvas.H],
                    'ground_y': round(canvas.oy, 1), 'px_per_unit': round(canvas.s, 2),
                    'anchors': {k: list(rendered.anchor(k, facing)) for k in rendered.anchors if k != 'ground'}}
            yield pid, rendered.svg(facing), meta
    if v.face is not None:
        for expr in faces.EXPRESSIONS:
            fig = faces.build(v.face, expr)
            canvas = Canvas(fig.bounds(), long_side=300.0, ground=False)
            rendered = Rendered(fig, canvas)
            pid = f'cr_{v.key}_face_{expr}_f'
            meta = {'pose': f'face_{expr}', 'facing': 'f', 'size': [canvas.W, canvas.H],
                    'anchors': {k: list(rendered.anchor(k)) for k in rendered.anchors}}
            yield pid, rendered.svg('r'), meta


def tag_entry(v, meta):
    pose, facing = meta['pose'], meta['facing']
    if pose.startswith('face_'):
        expr = pose[5:]
        desc = f'{v.noun}, head close-up, front view, {EXPR_EN[expr]}'
        en = [f'{v.names[0]} face', *v.names[:3], 'face', 'close-up', EXPR_EN[expr].split(',')[0]]
        zh = [*(f'{z}脸' for z in v.zh[:1]), *v.zh[:3], '特写', EXPR_ZH[expr]]
    else:
        words = POSE_EN.get(pose, (pose,))[0]
        desc = f'{v.noun}, {words}, {FACING_EN[facing]} (full body)'
        en = list(v.names)          # keywords name the creature; the pose is in the description and the id
        zh = list(v.zh)
    search = pose == v.poses[0] and facing == 'r'      # one searchable picture per look: its resting pose
    entry = {'category': v.category, 'desc': desc, 'en': list(dict.fromkeys(en)), 'zh': list(dict.fromkeys(zh))}
    if not search:
        entry['search'] = False
    entry['creature'] = {'species': v.species, 'family': v.family, 'sex': v.sex, 'age': v.age,
                         'variant': v.variant, 'marks': list(v.marks), **meta}
    return entry
