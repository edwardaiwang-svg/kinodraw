"""The cast: species priors and variants (family -> body plan -> genes), with names for search.

Every entry is a prior (typical genes); ``genes.individual`` samples the shipped individual around it,
so proportions vary a little between species variants without leaving the species' silhouette.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import colors as C
from .faces import Face
from . import frog as _frog
from . import insect as _insect
from .primate import Ape
from .primate import POSES as APE_POSES
from .quad import Quad

QUAD_POSES = ('stand', 'walk1', 'walk2', 'run', 'sit', 'lie', 'sleep', 'roar', 'look_up', 'scared', 'carry')


@dataclass
class Variant:
    species: str
    sex: str = 'any'
    age: str = 'adult'
    variant: str = ''
    plan: str = 'quad'
    genes: object = None
    face: object = None
    family: str = ''
    names: tuple = ()          # English search names, most specific first
    zh: tuple = ()
    marks: tuple = ()
    poses: tuple = QUAD_POSES
    noun: str = ''             # description noun phrase
    category: str = 'animals'
    jitter: float = 1.0

    @property
    def key(self):
        return '_'.join(x for x in (self.species, self.sex, self.age, self.variant) if x)


LION = Quad(L=.92, hip_h=.7, sh_h=.74, head_r=.3, snout=.85, snout_r=.44, eye_r=.15, eye_at=(.36, .24),
            neck_len=.2, neck_ang=50, leg_r=.13, thigh_r=.22, knee_r=.095, foot_r=.075, paw_r=.095,
            tail_len=.62, tail_rest=245, tail_curl=-14, ears='round', ear_size=.36, tail_tip='tuft',
            coat='#E0A54B', under='#F7DDB0', tip='#5A3A22', mane=1.0, mane_c='#9A5A25')
LIONESS = replace(LION, mane=0, head_r=.27, neck_len=.24, neck_r=.15, chest_r=.3, hip_r=.27, L=.95,
                  coat='#DBA65E', under='#F6E1BC', ear_size=.38, tip='#5A3A22')
CUB = replace(LION, mane=0, L=.62, hip_h=.46, sh_h=.48, chest_r=.27, hip_r=.25, head_r=.34, snout=.62, snout_r=.42,
              neck_len=.12, neck_r=.15, leg_r=.11, thigh_r=.17, knee_r=.09, foot_r=.085, paw_r=.13, eye_r=.17,
              tail_len=.42, tail_r=.04, coat='#E3B26A', under='#F8E4C2', ear_size=.46, cub=True,
              pattern='spots', mark_c='#D19A55')

MANES = {  # variant -> (mane colour, tuft colour, en words, zh words, marks)
    '': ('#9A5A25', '#5A3A22', ('golden mane',), ('金色鬃毛',), ('mane_gold',)),
    'darkmane': ('#5E3A20', '#3E2A1C', ('dark mane', 'brown mane'), ('深色鬃毛',), ('mane_dark',)),
    'blackmane': ('#3B2B24', '#2E2420', ('black mane', 'black-maned'), ('黑色鬃毛', '黑鬃'), ('mane_black',)),
}


def _lions():
    out = []
    for key, (mane_c, tip, en, zh, marks) in MANES.items():
        for scar in (False, True):
            variant = '_'.join(x for x in (key, 'scar' if scar else '') if x)
            words = en + (('scar', 'scarred', 'nose scar') if scar else ())
            out.append(Variant('lion', 'male', 'adult', variant, genes=replace(LION, mane_c=mane_c, tip=tip, scar=scar),
                               face=Face('bigcat', LION.coat, LION.under, '#C98B6B', ears='round', ear_size=.85,
                                         mane=1.0, mane_c=mane_c, scar=scar, iris='#C98A2E'),
                               family='big_cat', names=('lion', 'male lion', 'king of the jungle') + words,
                               zh=('狮子', '雄狮') + zh + (('伤疤',) if scar else ()),
                               marks=marks + (('scar_nose',) if scar else ()),
                               noun='male lion' + (f' with a {en[0]}' if key else '') + (' and a scar across the nose' if scar else '')))
    out.append(Variant('lion', 'female', 'adult', genes=LIONESS,
                       face=Face('bigcat', LIONESS.coat, LIONESS.under, '#C98B6B', ears='round', ear_size=.95,
                                 iris='#C98A2E'),
                       family='big_cat', names=('lioness', 'lion', 'female lion', 'mother lion'),
                       zh=('母狮', '狮子'), noun='lioness'))
    out.append(Variant('lion', 'any', 'young', genes=CUB,
                       face=Face('bigcat', CUB.coat, CUB.under, '#D9A07A', ears='round', ear_size=1.1, young=True,
                                 pattern='spots', mark_c='#D19A55', iris='#B5852E'),
                       family='big_cat', names=('lion cub', 'cub', 'baby lion', 'young lion'),
                       zh=('小狮子', '狮子幼崽', '幼狮'), noun='lion cub with oversized paws', jitter=.5))
    out += _primates()
    out += _small()
    return out


def _small():
    tree = _frog.Frog()
    return [
        Variant('frog', variant='tree', genes=tree, plan='frog', poses=_frog.POSES, family='amphibian',
                face=Face('frog', tree.coat, tree.belly, iris=tree.eye_c),
                names=('tree frog', 'frog', 'red-eyed tree frog'), zh=('树蛙', '青蛙'), noun='red-eyed tree frog'),
        Variant('ant', variant='black', genes=_insect.Bug('ant', '#4A403C'), plan='insect',
                poses=_insect.POSES['ant'], family='insect', face=Face('ant', '#4A403C'),
                names=('ant', 'black ant', 'worker ant'), zh=('蚂蚁', '黑蚂蚁'), noun='black ant'),
        Variant('ant', variant='red', genes=_insect.Bug('ant', '#C0482E'), plan='insect',
                poses=_insect.POSES['ant'], family='insect', face=Face('ant', '#C0482E'),
                names=('red ant', 'ant', 'fire ant'), zh=('红蚂蚁', '蚂蚁'), noun='red ant'),
    ]


GORILLA = Ape(L=.52, chest_r=.34, hip_r=.22, head_r=.25, muzzle=.5, crest=1.0, arm=.82, arm_r=.12, leg=.46,
              leg_r=.11, hand_r=.09, foot=.17, coat='#62656C', face_c='#3A3B40', under='#4E5157', hand_c='#3A3B40',
              ear_r=.18, back_c='#9A9EA6', eye_r=.14)
CHIMP = Ape(L=.44, chest_r=.25, hip_r=.19, head_r=.2, muzzle=.75, arm=.72, arm_r=.085, leg=.44, leg_r=.085,
            hand_r=.07, foot=.15, coat='#3B2E27', face_c='#D8B08A', under='#4A3A31', hand_c='#C9A07C', ear_r=.27)
MONKEY = Ape(L=.36, chest_r=.18, hip_r=.16, head_r=.19, muzzle=.4, arm=.5, arm_r=.06, leg=.42, leg_r=.07,
             hand_r=.055, foot=.13, tail_len=.85, tail_r=.03, coat='#8A5A3C', face_c='#F2CCA4', under='#B98A63',
             hand_c='#E6B992', ear_r=.24, eye_r=.14)


def _primates():
    return [
        Variant('gorilla', genes=GORILLA, plan='primate', poses=APE_POSES, family='primate',
                face=Face('ape', GORILLA.coat, GORILLA.face_c, GORILLA.face_c, ears='side', ear_size=.8,
                          face_c='#3A3B40', nose_c='#1B1B1B'),
                names=('gorilla', 'silverback', 'ape'), zh=('大猩猩', '猩猩'), noun='gorilla'),
        Variant('chimpanzee', genes=CHIMP, plan='primate', poses=APE_POSES, family='primate',
                face=Face('monkey', CHIMP.coat, CHIMP.face_c, CHIMP.face_c, ears='side', ear_size=1.2,
                          face_c=CHIMP.face_c),
                names=('chimpanzee', 'chimp', 'ape'), zh=('黑猩猩',), noun='chimpanzee'),
        Variant('monkey', genes=MONKEY, plan='primate', poses=APE_POSES, family='primate',
                face=Face('monkey', MONKEY.coat, MONKEY.face_c, MONKEY.face_c, ears='side', ear_size=1.0,
                          face_c=MONKEY.face_c),
                names=('monkey', 'little monkey'), zh=('猴子', '小猴子'), noun='monkey with a long tail'),
    ]


HYENA = Quad(L=.86, hip_h=.56, sh_h=.78, chest_r=.31, hip_r=.24, head_r=.27, snout=.95, snout_r=.42, snout_drop=.3,
             jaw_r=.3, neck_len=.24, neck_r=.17, neck_ang=40, ears='round', ear_size=.36, eye_r=.13,
             leg_r=.12, thigh_r=.17, knee_r=.085, foot_r=.07, paw_r=.09, tail_len=.36, tail_r=.05, tail_tip='tuft',
             tail_rest=235, tail_curl=-6, tip='#3C2E24', coat='#C9A774', under='#E6D2A8', muzzle='#5E4A38',
             pattern='spots', mark_c='#6A5038', mane=1.0, mane_kind='ridge', mane_c='#5E4A38', nose='dog')

PORCUPINE = Quad(L=.52, hip_h=.3, sh_h=.28, chest_r=.21, hip_r=.24, head_r=.18, snout=.7, snout_r=.42, neck_len=.06,
                 neck_r=.14, neck_ang=25, ears='round', ear_size=.3, eye_r=.16, leg_r=.07, thigh_r=.1, knee_r=.06,
                 foot_r=.05, paw_r=.06, stance='plant', tail_len=.0, tail_tip='none', coat='#7A6250',
                 under='#9C8470', muzzle='#9C8470', quills=.33, quill_c='#4E3B2C', nose='pad', nose_c='#3A2A26')

ELEPHANT = Quad(L=1.0, hip_h=.98, sh_h=1.04, chest_r=.47, hip_r=.44, belly=.06, back=.1, neck_len=.12, neck_r=.32,
                neck_ang=32, head_r=.4, head_ry=.95, snout=.15, snout_r=.4, jaw_r=.22, ears='none', big_ears=1.0,
                eye_r=.08, eye_at=(.3, .15), leg_r=.18, thigh_r=.22, knee_r=.16, foot_r=.16, paw_r=.17, stance='plant',
                tail_len=.45, tail_r=.03, tail_tip='tuft', tail_rest=255, tail_curl=-4, tip='#4A4F55',
                coat='#A3A9B0', under='#A3A9B0', muzzle='#A3A9B0', ear_in='#D9A8A8', trunk=1.0, tusks=1.0,
                nose='none', head_pitch=-8)
CALF = replace(ELEPHANT, L=.74, hip_h=.66, sh_h=.7, chest_r=.38, hip_r=.36, head_r=.37, leg_r=.15, thigh_r=.18,
               knee_r=.14, foot_r=.14, paw_r=.16, tusks=0, trunk=.75, big_ears=.95, eye_r=.11, cub=True,
               coat='#B0B5BB', under='#B0B5BB', muzzle='#B0B5BB', tail_len=.3)


def catalogue():
    out = _lions()
    out.append(Variant('hyena', genes=HYENA, family='hyena',
                       face=Face('hyena', HYENA.coat, '#6A5442', '#8A6A50', ears='round', ear_size=1.0,
                                 pattern='spots', mark_c='#6A5038', nose_c=C.NOSE),
                       names=('hyena', 'spotted hyena', 'laughing hyena', 'scavenger'), zh=('鬣狗', '斑鬣狗'), noun='spotted hyena'))
    out.append(Variant('porcupine', genes=PORCUPINE, family='rodent',
                       face=Face('porcupine', PORCUPINE.coat, PORCUPINE.under, '#9C8470', ears='round', ear_size=.6,
                                 quills=True, nose_c=C.NOSE),
                       names=('porcupine', 'quills', 'prickly'), zh=('豪猪', '箭猪'), noun='porcupine with raised quills'))
    out.append(Variant('elephant', 'any', 'adult', genes=ELEPHANT, family='elephant',
                       face=Face('elephant', ELEPHANT.coat, ELEPHANT.under, '#D9A8A8', ears='elephant', tusks=True),
                       names=('elephant', 'african elephant', 'tusker'), zh=('大象', '象'), noun='elephant with tusks'))
    out.append(Variant('elephant', 'any', 'young', genes=CALF, family='elephant',
                       face=Face('elephant', CALF.coat, CALF.under, '#E3B5B5', ears='elephant', young=True),
                       names=('baby elephant', 'elephant calf', 'calf', 'elephant'), zh=('小象', '象宝宝'),
                       noun='baby elephant', jitter=.5))
    return out
