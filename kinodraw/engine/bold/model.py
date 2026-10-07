"""Small, serializable scenes for the motion, kinetic_type and chart treatments.

Positions are fractions of the stage; sizes are pixels at 1920 x 1080. Scene times are local seconds.
Matching ``motif`` names let a shape carry its identity across a transition.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TEXT_ENTER, PANEL_ENTER = .4, .65
HOLD_MIN, HOLD_MAX = .5, 1.1
TYPE_CPS = 30
PARTICLE_STAGGER = .25
COMPOSITIONS = {'center', 'left_third', 'right_third', 'split', 'grid', 'full_bleed'}
CAMERAS = {'static', 'slow_push', 'pull_back', 'pan', 'shake'}
TRANSITIONS = {'cut', 'wipe', 'iris', 'match', 'zoom_through', 'morph', 'page'}
PRESETS = {'type_on', 'word_pop', 'slam', 'cascade', 'counter', 'corner_caption', 'clauses'}
CLAUSE_STAGGER = .05                # seconds between the words of one clause
KINDS = {'text', 'picture', 'dot', 'line', 'ring', 'particle_field', 'chart'}


@dataclass(frozen=True)
class Palette:
    background: str = '#0c0c0c'
    foreground: str = '#d7d6d2'
    accent: str = '#ffb454'


@dataclass
class MotionElement:
    kind: str = 'text'
    text: str = ''
    preset: str = 'type_on'
    x: float | None = None
    y: float | None = None
    size: float = 96
    width: float = 640
    height: float = 320
    start: float = 0.
    duration: float | None = None
    end: float | None = None
    accent: bool = False
    svg_id: str | None = None
    svg: str | None = None
    motif: str | None = None
    values: tuple[float, ...] = ()
    labels: tuple[str, ...] = ()
    chart: str = 'bar'
    value_from: float = 0.
    value_to: float = 100.
    decimals: int | None = None
    suffix: str = ''
    count: int = 48
    emissive: bool = False
    font: str = 'rounded'
    kick: float = 0.                  # initial px/frame, with .7 decay at 30 fps
    preserve_svg_palette: bool = False  # generated artwork already follows the authored palette
    cues: tuple[float, ...] = ()      # clauses: each clause's local start (its spoken time)

    @staticmethod
    def word_starts(text, cues):
        """Start of each word: its clause's cue, a short stagger inside the clause. A clause ends at , ; : . ! ? or …."""
        out, clause, within = [], 0, 0
        for word in text.split():
            out.append(cues[min(clause, len(cues) - 1)] + min(.4, within * CLAUSE_STAGGER))
            within += 1
            if word[-1] in ',;:.!?…':
                clause, within = clause + 1, 0
        return out

    def __post_init__(self):
        if self.kind not in KINDS or self.preset not in PRESETS:
            raise ValueError('Unknown motion element kind or text preset')
        if self.chart not in {'bar', 'line', 'number'}:
            raise ValueError('Unknown chart kind')
        if self.size <= 0 or self.width <= 0 or self.height <= 0 or not 0 <= self.count <= 512:
            raise ValueError('Element sizes must be positive; particle count must be 0..512')
        if self.duration is not None and self.duration <= 0:
            raise ValueError('Element duration must be positive')
        if self.decimals is not None and not 0 <= self.decimals <= 6:
            raise ValueError('Counter decimals must be 0..6')
        if self.kind == 'picture' and not (self.svg_id or self.svg):
            raise ValueError('A picture needs a library SVG id or raw SVG')
        self.cues = tuple(float(c) for c in self.cues)
        if self.preset == 'clauses' and self.kind == 'text' and not self.cues:
            raise ValueError('A clauses reveal needs the start of each clause')

    @property
    def entrance(self):
        return TEXT_ENTER if self.kind == 'text' else PANEL_ENTER


@dataclass
class MotionScene:
    elements: list[MotionElement] = field(default_factory=list)
    duration: float | None = None
    treatment: str = 'motion'
    composition: str = 'center'
    camera: str = 'static'
    transition_in: str = 'morph'
    palette: Palette = field(default_factory=Palette)
    energy: int = 3
    motion_floor: float = 1.
    hold: float = .8
    seed: int = 0
    foreground_drift: float = 5.    # reference pixels; hybrid maps its configured motion floor
    grain: float = 0.                 # optional, applied below the sharp text layer
    glow: float = .7
    blur_samples: int = 3
    continuous_drift: bool = False  # hybrid requests a foreground arc without simultaneous turning points

    def __post_init__(self):
        self.elements = [MotionElement(**e) if isinstance(e, dict) else e for e in self.elements]
        if isinstance(self.palette, dict):
            self.palette = Palette(**self.palette)
        if self.duration is None:
            finishes = []
            for e in self.elements:
                animation = e.duration or e.entrance
                if e.preset == 'counter' or e.kind == 'chart' and e.chart == 'number':
                    animation = e.duration or 1.8
                elif e.kind == 'text' and e.preset == 'type_on':
                    animation = max(TEXT_ENTER, len(e.text) / TYPE_CPS)
                elif e.kind == 'text' and e.preset == 'clauses':
                    animation = max(e.word_starts(e.text, e.cues), default=e.start) - e.start + TEXT_ENTER
                elif e.kind == 'text' and e.preset in {'word_pop', 'cascade'}:
                    n = len(e.text.split()) if e.preset == 'word_pop' else len(e.text)
                    animation = TEXT_ENTER + max(0, n - 1) * (.1 if e.preset == 'word_pop' else .035)
                elif e.kind == 'chart':
                    animation += min(.3, max(0, len(e.values) - 1) * .09)
                elif e.kind == 'particle_field' and e.count:
                    animation += PARTICLE_STAGGER
                finishes.append(e.start + animation)
            self.duration = max(finishes, default=0.) + self.hold
        if self.composition not in COMPOSITIONS or self.camera not in CAMERAS:
            raise ValueError('Unknown motion composition or camera')
        if self.transition_in not in TRANSITIONS or self.treatment not in {'motion', 'kinetic_type', 'chart'}:
            raise ValueError('Unknown motion treatment or transition')
        if self.duration <= 0 or not 1 <= self.energy <= 5 or not 0 <= self.motion_floor <= 1:
            raise ValueError('Scene duration must be positive, energy 1..5 and motion_floor 0..1')
        if not HOLD_MIN <= self.hold <= HOLD_MAX or not 1 <= self.blur_samples <= 8:
            raise ValueError('Hold must be .5..1.1 seconds and blur_samples 1..8')
        if self.glow < 0 or self.grain < 0:
            raise ValueError('Glow and grain must be nonnegative')
