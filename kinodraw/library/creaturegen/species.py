"""The cast: species priors and variants (family -> body plan -> genes), with names for search.

Every entry is a prior (typical genes); ``genes.individual`` samples the shipped individual around it,
so proportions vary a little between species variants without leaving the species' silhouette.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import colors as C
from .faces import Face
from . import bird as _bird
from . import fish as _fish
from . import frog as _frog
from . import human as _human
from . import reptile as _reptile
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
    'blackmane': ('#3B2B24', '#2E2420', ('black mane', 'black-maned lion'), ('黑色鬃毛', '黑鬃'), ('mane_black',)),
}


def _lions():
    out = []
    for key, (mane_c, tip, en, zh, marks) in MANES.items():
        for scar in (False, True):
            variant = '_'.join(x for x in (key, 'scar' if scar else '') if x)
            words = en + (('scar', 'scarred lion', 'nose scar') if scar else ())
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
    out += _quads()
    out += _birds()
    out += _reptiles_and_fish()
    out += _people()
    return out


def Q(species, genes, face, names, zh, noun, family, sex='any', age='adult', variant='', marks=(), jitter=1.0):
    return Variant(species, sex, age, variant, genes=genes, face=face, family=family, names=names, zh=zh, marks=marks,
                   noun=noun, jitter=jitter)


FELINE = replace(LIONESS, tail_tip='plain', tail_len=.7, tail_curl=-20, tail_rest=255)
TIGER = replace(FELINE, L=1.0, chest_r=.31, hip_r=.29, head_r=.28, ear_size=.33, coat='#F08A2C', under='#FFF4E2',
                muzzle='#FFF4E2', pattern='stripes', mark_c='#2A2420', ear_in='#2A2420', whiskers=True)
LEOPARD = replace(FELINE, L=.95, sh_h=.64, hip_h=.63, chest_r=.27, hip_r=.25, head_r=.25, ear_size=.33, coat='#EDB252',
                  under='#FBEFD2', muzzle='#FBEFD2', pattern='rosettes', mark_c='#3A2A1E', tail_len=.85, tail_r=.05)
CHEETAH = replace(FELINE, L=.9, sh_h=.76, hip_h=.74, chest_r=.26, hip_r=.22, head_r=.24, snout=.65, ear_size=.32,
                  leg_r=.1, thigh_r=.17, knee_r=.075, foot_r=.065, paw_r=.08, coat='#EEC273', under='#FCF3DF',
                  muzzle='#FCF3DF', pattern='spots', mark_c='#2A2420', tail_len=.8, tail_r=.04, tail_tip_c='#2A2420')
CAT = Quad(L=.62, hip_h=.42, sh_h=.42, chest_r=.21, hip_r=.2, head_r=.25, snout=.42, snout_r=.4, snout_drop=.3,
           jaw_r=.24, eye_r=.16, eye_at=(.35, .2), neck_len=.12, neck_r=.12, neck_ang=55, ears='pointed', ear_size=.5,
           ear_ang=105, leg_r=.08, thigh_r=.13, knee_r=.06, foot_r=.05, paw_r=.065, tail_len=.68, tail_r=.04,
           tail_tip='plain', tail_rest=110, tail_curl=-14, whiskers=True, coat='#F2A65A', under='#FFF1DE',
           muzzle='#FFF1DE', pattern='stripes', mark_c='#D9772B', ear_in='#F2A0A0', nose_c='#E07A80')
DOG = Quad(L=.78, hip_h=.56, sh_h=.6, chest_r=.27, hip_r=.23, head_r=.24, snout=.95, snout_r=.4, snout_drop=.22,
           jaw_r=.26, eye_r=.14, eye_at=(.32, .22), neck_len=.2, neck_r=.14, neck_ang=55, ears='floppy', ear_size=.62,
           ear_ang=95, leg_r=.1, thigh_r=.16, knee_r=.075, foot_r=.06, paw_r=.08, tail_len=.5, tail_r=.05,
           tail_tip='plain', tail_rest=135, tail_curl=-10, nose='dog', coat='#E2A85C', under='#F6DDB4', muzzle='',
           ear_in='#C88A48')
WOLF = replace(DOG, L=.92, hip_h=.7, sh_h=.74, chest_r=.27, hip_r=.22, head_r=.25, snout=1.05, ears='pointed', ear_size=.45,
               ear_ang=110, tail_tip='fluffy', tail_len=.62, tail_r=.06, tail_rest=225, tail_curl=-6, coat='#8E9196',
               under='#ECE8E0', muzzle='#ECE8E0', ear_in='#5E6166', leg_r=.1)
FOX = replace(WOLF, L=.7, hip_h=.52, sh_h=.54, chest_r=.21, hip_r=.19, head_r=.22, snout=1.0, ear_size=.55,
              tail_len=.72, tail_r=.07, tail_rest=200, tail_curl=-4, coat='#E8762E', under='#FFF6EC', muzzle='#FFF6EC',
              leg_c='#4A3428', ear_in='#4A3428', tail_tip_c='#FFF6EC')
BEAR = Quad(L=.9, hip_h=.66, sh_h=.72, chest_r=.36, hip_r=.34, belly=.05, back=.12, head_r=.28, snout=.75, snout_r=.42,
            snout_drop=.18, jaw_r=.26, eye_r=.11, eye_at=(.32, .25), neck_len=.14, neck_r=.22, neck_ang=40,
            ears='round', ear_size=.3, leg_r=.15, thigh_r=.2, knee_r=.13, foot_r=.12, paw_r=.13, stance='plant',
            tail_len=.12, tail_r=.06, tail_tip='plain', tail_rest=180, tail_curl=0, nose='dog', coat='#8A5A3A',
            under='#8A5A3A', muzzle='#C99E76', ear_in='#5E3C26')
GIRAFFE = Quad(L=.62, hip_h=.95, sh_h=1.08, chest_r=.27, hip_r=.24, head_r=.17, snout=1.0, snout_r=.42, snout_drop=.15,
               jaw_r=.24, eye_r=.15, eye_at=(.25, .22), neck_len=1.05, neck_r=.11, neck_ang=72, ears='small',
               ear_size=.38, ear_ang=150, leg_r=.08, thigh_r=.12, knee_r=.06, foot_r=.05, paw_r=.065, stance='hoof',
               meta=.38, tail_len=.45, tail_r=.025, tail_tip='tuft', tail_rest=250, tail_curl=-2, tip='#6B3A1E',
               nose='hoof', coat='#F2C16B', under='#F8DFA6', muzzle='#F8DFA6', pattern='giraffe', mark_c='#B5652D',
               mane=1.0, mane_kind='ridge', mane_c='#B5652D', horns='ossicones', head_pitch=-10, hooves_c='#5A3A28')
HORSE = Quad(L=.85, hip_h=.82, sh_h=.86, chest_r=.3, hip_r=.29, head_r=.24, snout=1.1, snout_r=.5, snout_drop=.18,
             jaw_r=.28, eye_r=.15, eye_at=(.22, .24), neck_len=.4, neck_r=.18, neck_ang=58, ears='pointed', ear_size=.36,
             ear_ang=125, leg_r=.1, thigh_r=.17, knee_r=.07, foot_r=.06, paw_r=.07, stance='hoof', meta=.36,
             tail_len=.55, tail_r=.065, tail_tip='flow', tail_rest=252, tail_curl=3, tail_hang=True, tail_c='#2E2624',
             nose='hoof', coat='#8B5A3C', under='#8B5A3C', muzzle='#6A4430', mane=1.0, mane_kind='horse',
             mane_c='#2E2624', head_pitch=-25)
ZEBRA = replace(HORSE, coat='#FAFAF7', under='#FAFAF7', muzzle='#3A3536', pattern='zebra', mark_c='#2A2627',
                mane_c='#2A2627', tail_r=.03, tail_tip='tuft', tip='#2A2627', tail_c='', L=.8)
DEER = Quad(L=.72, hip_h=.72, sh_h=.74, chest_r=.24, hip_r=.23, head_r=.19, snout=.9, snout_r=.42, snout_drop=.2,
            jaw_r=.24, eye_r=.17, eye_at=(.25, .22), neck_len=.36, neck_r=.11, neck_ang=62, ears='pointed', ear_size=.45,
            ear_ang=150, leg_r=.08, thigh_r=.14, knee_r=.055, foot_r=.045, paw_r=.055, stance='hoof', meta=.38,
            tail_len=.1, tail_r=.05, tail_tip='bob', nose='pad', coat='#B87A48', under='#F3E6D2', muzzle='#F3E6D2',
            ear_in='#F3E6D2', head_pitch=-12, horn_c='#E9D6B0')
ANTELOPE = replace(DEER, coat='#D9A066', under='#FBF4EA', muzzle='#FBF4EA', horns='antelope', horn_c='#4A3A30',
                   pattern='none', ear_size=.38, L=.7)
RABBIT = Quad(L=.36, hip_h=.32, sh_h=.24, chest_r=.18, hip_r=.24, head_r=.19, snout=.45, snout_r=.42, snout_drop=.25,
              jaw_r=.22, eye_r=.18, eye_at=(.32, .22), neck_len=.06, neck_r=.11, neck_ang=55, ears='long', ear_size=.62,
              ear_ang=120, leg_r=.06, thigh_r=.18, knee_r=.06, foot_r=.05, paw_r=.07, stance='plant',
              tail_len=.05, tail_r=.09, tail_tip='bob', nose='pad', nose_c='#E07A80', coat='#B9AFA4', under='#F3EEE8',
              muzzle='#F3EEE8', ear_in='#F2A0A0', whiskers=True)
MOUSE = Quad(L=.34, hip_h=.18, sh_h=.17, chest_r=.13, hip_r=.15, head_r=.15, snout=.75, snout_r=.36, snout_drop=.18,
             jaw_r=.2, eye_r=.16, eye_at=(.32, .22), neck_len=.04, neck_r=.09, neck_ang=30, ears='round', ear_size=.55,
             leg_r=.035, thigh_r=.08, knee_r=.03, foot_r=.025, paw_r=.035, stance='plant', tail_len=.5, tail_r=.016,
             tail_tip='plain', tail_rest=200, tail_curl=10, nose='pad', nose_c='#E07A80', coat='#A9A9AE',
             under='#E8E6EA', muzzle='#E8E6EA', ear_in='#F2A0A0', whiskers=True)
COW = Quad(L=.95, hip_h=.68, sh_h=.7, chest_r=.36, hip_r=.34, belly=.06, head_r=.27, head_ry=.9, snout=.8, snout_r=.56,
           snout_drop=.2, jaw_r=.3, eye_r=.14, eye_at=(.18, .22), neck_len=.18, neck_r=.2, neck_ang=35, ears='small',
           ear_size=.42, ear_ang=160, leg_r=.11, thigh_r=.19, knee_r=.08, foot_r=.07, paw_r=.08, stance='hoof',
           meta=.3, tail_len=.6, tail_r=.025, tail_tip='tuft', tail_rest=262, tail_curl=1, tail_hang=True, tip='#2A2627',
           nose='hoof', coat='#FAFAF7', under='#FAFAF7', muzzle='#F4B5B0', pattern='patches', mark_c='#2E2A2B',
           horns='cow', horn_c='#EFE6D2', head_pitch=-15)
PIG = Quad(L=.62, hip_h=.38, sh_h=.38, chest_r=.27, hip_r=.27, belly=.04, head_r=.24, snout=.55, snout_r=.44,
           snout_drop=.12, jaw_r=.26, eye_r=.12, eye_at=(.3, .25), neck_len=.06, neck_r=.18, neck_ang=25,
           ears='pointed', ear_size=.42, ear_ang=115, leg_r=.08, thigh_r=.13, knee_r=.06, foot_r=.055, paw_r=.06,
           stance='hoof', meta=.2, tail_len=.22, tail_r=.025, tail_tip='plain', tail_rest=160, tail_curl=-75,
           tail_seg=6, nose='pig', coat='#F4ABA9', under='#F4ABA9', muzzle='#F4ABA9', ear_in='#E58A8A')
SHEEP = Quad(L=.66, hip_h=.5, sh_h=.52, chest_r=.27, hip_r=.27, head_r=.19, snout=.7, snout_r=.42, snout_drop=.2,
             jaw_r=.24, eye_r=.15, eye_at=(.25, .2), neck_len=.12, neck_r=.14, neck_ang=40, ears='small', ear_size=.42,
             ear_ang=175, leg_r=.06, thigh_r=.1, knee_r=.05, foot_r=.045, paw_r=.055, stance='hoof', meta=.3,
             tail_len=.1, tail_r=.06, tail_tip='bob', nose='hoof', coat='#3A3536', under='#FFFFFF', muzzle='#3A3536',
             fluffy=1.0, head_pitch=-12)
GOAT = Quad(L=.66, hip_h=.56, sh_h=.58, chest_r=.24, hip_r=.23, head_r=.19, snout=.85, snout_r=.4, snout_drop=.2,
            jaw_r=.24, eye_r=.15, eye_at=(.24, .22), neck_len=.2, neck_r=.12, neck_ang=55, ears='small', ear_size=.45,
            ear_ang=170, leg_r=.07, thigh_r=.12, knee_r=.055, foot_r=.045, paw_r=.055, stance='hoof', meta=.32,
            tail_len=.12, tail_r=.04, tail_tip='plain', tail_rest=120, tail_curl=-10, nose='hoof', coat='#F1ECE4',
            under='#F1ECE4', muzzle='#E6DCCD', horns='goat', horn_c='#8A7A68', chin_tuft=.35, head_pitch=-8)


def _f(kind, g, **kw):
    return Face(kind, g.coat, kw.pop('under', g.muzzle or g.under), kw.pop('ear_in', g.ear_in), **kw)


def _quads():
    out = []
    add = out.append
    add(Q('tiger', TIGER, _f('bigcat', TIGER, pattern='stripes', mark_c='#2A2420', ears='round', ear_size=.85,
                            iris='#C98A2E'), ('tiger', 'bengal tiger', 'big cat'), ('老虎', '虎'), 'tiger', 'big_cat'))
    add(Q('tiger', replace(TIGER, coat='#F4F1EA', under='#FFFFFF', muzzle='#FFFFFF', mark_c='#3A3536'),
          _f('bigcat', replace(TIGER, coat='#F4F1EA'), under='#FFFFFF', pattern='stripes', mark_c='#3A3536',
             ears='round', ear_size=.85, iris='#6FA8DC'),
          ('white tiger', 'tiger'), ('白虎', '老虎'), 'white tiger', 'big_cat', variant='white'))
    add(Q('leopard', LEOPARD, _f('bigcat', LEOPARD, pattern='rosettes', mark_c='#3A2A1E', ears='round', ear_size=.8,
                                iris='#8DB04A'), ('leopard', 'spotted cat', 'big cat'), ('豹', '花豹', '金钱豹'),
          'leopard', 'big_cat'))
    add(Q('leopard', replace(LEOPARD, coat='#34303A', under='#34303A', muzzle='#4A4550', pattern='none'),
          _f('bigcat', replace(LEOPARD, coat='#34303A'), under='#4A4550', ears='round', ear_size=.8, iris='#9BD14A'),
          ('black panther', 'panther', 'black leopard'), ('黑豹',), 'black panther', 'big_cat', variant='black'))
    add(Q('cheetah', CHEETAH, _f('bigcat', CHEETAH, pattern='tears', mark_c='#2A2420', ears='round', ear_size=.7,
                                iris='#C98A2E'), ('cheetah', 'fastest cat', 'big cat'), ('猎豹',), 'cheetah', 'big_cat'))
    cats = (('', CAT, 'ginger tabby cat', ('cat', 'ginger cat', 'tabby cat'), ('猫', '橘猫')),
            ('grey', replace(CAT, coat='#A5ABB2', under='#EEF0F2', muzzle='#EEF0F2', mark_c='#70767E'), 'grey tabby cat',
             ('cat', 'grey cat', 'tabby'), ('猫', '灰猫')),
            ('black', replace(CAT, coat='#3A3536', under='#3A3536', muzzle='#55504F', pattern='none', ear_in='#8A6A6A'),
             'black cat', ('black cat', 'cat'), ('黑猫', '猫')),
            ('white', replace(CAT, coat='#F6F3EE', under='#F6F3EE', muzzle='#FFFFFF', pattern='none'), 'white cat',
             ('white cat', 'cat'), ('白猫', '猫')))
    for variant, g, noun, names, zh in cats:
        iris = '#E8B630' if variant == 'black' else '#7FB3D5' if variant == 'white' else '#8DB04A'
        add(Q('cat', g, _f('cat', g, ears='pointed', ear_size=1.05, pattern='stripes' if g.pattern == 'stripes' else 'none',
                           mark_c=g.mark_c, iris=iris, nose_c='#E07A80'), names, zh, noun, 'big_cat', variant=variant))
    kitten = replace(CAT, L=.48, hip_h=.32, sh_h=.32, head_r=.27, paw_r=.075, eye_r=.18, ear_size=.55, tail_len=.45, cub=True)
    add(Q('cat', kitten, _f('cat', kitten, ears='pointed', ear_size=1.15, young=True, pattern='stripes', mark_c=CAT.mark_c,
                          iris='#8DB04A', nose_c='#E07A80'), ('kitten', 'baby cat', 'cat'), ('小猫', '猫咪'), 'kitten',
          'big_cat', age='young', jitter=.5))
    dogs = (('retriever', DOG, 'golden retriever dog', ('dog', 'golden retriever', 'pet dog'), ('狗', '金毛'), 'floppy'),
            ('dalmatian', replace(DOG, coat='#F7F5F0', under='#F7F5F0', pattern='dalmatian', mark_c='#2A2627',
                                  ear_in='#2A2627'), 'dalmatian dog', ('dalmatian', 'spotted dog', 'dog'), ('斑点狗', '狗'),
             'floppy'),
            ('black', replace(DOG, coat='#3B3533', under='#3B3533', ear_in='#2A2627'), 'black labrador dog',
             ('black dog', 'labrador', 'dog'), ('黑狗', '狗'), 'floppy'),
            ('beagle', replace(DOG, coat='#C98A4B', under='#FBF6EE', muzzle='#FBF6EE', pattern='saddle', mark_c='#3B3533',
                               L=.7, hip_h=.46, sh_h=.48, ear_size=.7, tail_tip_c='#FBF6EE'), 'beagle dog',
             ('beagle', 'hound', 'dog'), ('小猎犬', '狗'), 'floppy'),
            ('husky', replace(DOG, coat='#8E9AA6', under='#FBFBFB', muzzle='#FBFBFB', ears='pointed', ear_size=.46,
                              ear_ang=110, tail_tip='fluffy', tail_rest=120, tail_curl=-22, ear_in='#5E6A76',
                              blaze='#FBFBFB'), 'husky dog', ('husky', 'sled dog', 'dog'), ('哈士奇', '狗'), 'pointed'))
    for variant, g, noun, names, zh, ears in dogs:
        add(Q('dog', g, _f('dog', g, ears=ears, ear_size=.95, pattern='spots' if variant == 'dalmatian' else 'none',
                           mark_c='#2A2627', ear_in=g.ear_in), names, zh, noun, 'canine', variant=variant))
    puppy = replace(DOG, L=.52, hip_h=.36, sh_h=.38, head_r=.27, snout=.65, paw_r=.09, eye_r=.17, ear_size=.66,
                    tail_len=.32, cub=True)
    add(Q('dog', puppy, _f('dog', puppy, ears='floppy', ear_size=1.0, young=True), ('puppy', 'baby dog', 'dog'),
          ('小狗', '狗狗'), 'puppy', 'canine', age='young', jitter=.5))
    add(Q('wolf', WOLF, _f('wolf', WOLF, ears='pointed', ear_size=1.0, iris='#E3B23C'), ('wolf', 'grey wolf'),
          ('狼', '灰狼'), 'grey wolf', 'canine'))
    add(Q('fox', FOX, _f('fox', FOX, ears='pointed', ear_size=1.05, ear_in='#4A3428'), ('fox', 'red fox'),
          ('狐狸', '红狐'), 'red fox', 'canine'))
    bears = (('', BEAR, 'brown bear', ('bear', 'brown bear', 'grizzly'), ('熊', '棕熊')),
             ('polar', replace(BEAR, coat='#F4F1EA', under='#F4F1EA', muzzle='#F4F1EA', ear_in='#D9D2C6', L=.95,
                               neck_len=.24, head_r=.24, snout=.95), 'polar bear', ('polar bear', 'white bear', 'bear'),
              ('北极熊', '熊')),
             ('black', replace(BEAR, coat='#3A3536', under='#3A3536', muzzle='#B89A7A', ear_in='#2A2627'), 'black bear',
              ('black bear', 'bear'), ('黑熊', '熊')),
             ('panda', replace(BEAR, coat='#F6F4F0', under='#F6F4F0', muzzle='#F6F4F0', leg_c='#2E2A2B', ear_c='#2E2A2B',
                               eye_patch='#2E2A2B', pattern='band', mark_c='#2E2A2B', snout=.6), 'giant panda',
              ('panda', 'giant panda', 'panda bear'), ('熊猫', '大熊猫')))
    for variant, g, noun, names, zh in bears:
        add(Q('bear', g, _f('bear', g, ears='round', ear_size=.85,
                            pattern='mask' if variant == 'panda' else 'none', mark_c='#2E2A2B'),
              names, zh, noun, 'bear', variant=variant))
    giraffe = Q('giraffe', GIRAFFE, _f('giraffe', GIRAFFE, ears='small', horns='ossicones', pattern='giraffe',
                                       mark_c='#B5652D'), ('giraffe', 'tall giraffe'), ('长颈鹿',), 'giraffe', 'hoofed')
    giraffe.poses = tuple(p for p in QUAD_POSES if p != 'sit')
    add(giraffe)
    add(Q('zebra', ZEBRA, _f('horse', ZEBRA, ears='pointed', ear_size=.8, pattern='zebra', mark_c='#2A2627',
                            under='#3A3536'), ('zebra', 'striped horse'), ('斑马',), 'zebra', 'hoofed'))
    horses = (('', HORSE, 'bay horse', ('horse', 'brown horse'), ('马', '骏马')),
              ('chestnut', replace(HORSE, coat='#B5653A', under='#B5653A', muzzle='#8E4A2A', mane_c='#8E4A2A',
                                   blaze='#FBF6EE'), 'chestnut horse', ('horse', 'chestnut horse'), ('马', '栗色马')),
              ('white', replace(HORSE, coat='#F1EFEA', under='#F1EFEA', muzzle='#D8D2CA', mane_c='#D8D2CA'), 'white horse',
               ('white horse', 'horse'), ('白马', '马')),
              ('black', replace(HORSE, coat='#3A3536', under='#3A3536', muzzle='#55504F', mane_c='#1F1C1D'), 'black horse',
               ('black horse', 'horse'), ('黑马', '马')))
    for variant, g, noun, names, zh in horses:
        add(Q('horse', g, _f('horse', g, ears='pointed', ear_size=.8), names, zh, noun, 'hoofed', variant=variant))
    foal = replace(HORSE, L=.62, hip_h=.66, sh_h=.7, head_r=.21, snout=.95, neck_len=.3, eye_r=.18, mane=.6, cub=True)
    add(Q('horse', foal, _f('horse', foal, ears='pointed', ear_size=.85, young=True), ('foal', 'pony', 'baby horse'),
          ('小马', '马驹'), 'foal', 'hoofed', age='young', jitter=.5))
    add(Q('deer', replace(DEER, horns='antlers'), _f('deer', DEER, ears='small', ear_size=1.1, horns='antlers'),
          ('deer', 'stag'), ('鹿', '雄鹿'), 'stag with antlers', 'hoofed', sex='male'))
    add(Q('deer', DEER, _f('deer', DEER, ears='small', ear_size=1.1), ('deer', 'doe'), ('鹿', '母鹿'), 'doe', 'hoofed',
          sex='female'))
    fawn = replace(DEER, L=.55, hip_h=.56, sh_h=.58, head_r=.2, eye_r=.2, pattern='spots', mark_c='#FBF4EA', cub=True)
    add(Q('deer', fawn, _f('deer', fawn, ears='small', ear_size=1.2, young=True, pattern='spots', mark_c='#FBF4EA'),
          ('fawn', 'baby deer', 'deer'), ('小鹿',), 'spotted fawn', 'hoofed', age='young', jitter=.5))
    add(Q('antelope', ANTELOPE, _f('antelope', ANTELOPE, ears='small', ear_size=1.0, horns='antelope', horn_c='#4A3A30'),
          ('antelope', 'gazelle', 'impala'), ('羚羊', '瞪羚'), 'antelope with long horns', 'hoofed'))
    rabbits = (('', RABBIT, 'grey rabbit', ('rabbit', 'bunny', 'hare'), ('兔子', '小兔')),
               ('brown', replace(RABBIT, coat='#A57A57', under='#F2E6D8', muzzle='#F2E6D8'), 'brown rabbit',
                ('brown rabbit', 'rabbit', 'bunny'), ('棕兔', '兔子')),
               ('white', replace(RABBIT, coat='#FAF8F5', under='#FAF8F5', muzzle='#FFFFFF'), 'white rabbit',
                ('white rabbit', 'rabbit', 'bunny'), ('白兔', '兔子')))
    for variant, g, noun, names, zh in rabbits:
        add(Q('rabbit', g, _f('rabbit', g, ears='long', ear_size=1.0, nose_c='#E07A80'), names, zh, noun, 'rodent',
              variant=variant))
    add(Q('mouse', MOUSE, _f('mouse', MOUSE, ears='round', ear_size=1.6, nose_c='#E07A80'), ('mouse', 'little mouse',
                                                                                           'rat'), ('老鼠', '小老鼠'),
          'grey mouse', 'rodent'))
    add(Q('cow', COW, _f('cow', COW, ears='small', ear_size=1.0, horns='cow', under='#F4B5B0', ear_in='#F4B5B0'),
          ('cow', 'dairy cow', 'cattle'), ('奶牛', '牛'), 'black-and-white cow', 'hoofed'))
    brown_cow = replace(COW, coat='#9A5B34', under='#9A5B34', pattern='none', muzzle='#F0C9B8', blaze='#FAFAF7')
    add(Q('cow', brown_cow, _f('cow', brown_cow, ears='small', horns='cow', under='#F0C9B8', ear_in='#F0C9B8'),
          ('cow', 'brown cow', 'cattle', 'ox'), ('黄牛', '牛'), 'brown cow', 'hoofed', variant='brown'))
    calf = replace(COW, L=.66, hip_h=.52, sh_h=.54, head_r=.23, horns='none', eye_r=.17, cub=True)
    add(Q('cow', calf, _f('cow', calf, ears='small', young=True, under='#F4B5B0', ear_in='#F4B5B0'),
          ('calf', 'baby cow', 'cow'), ('小牛', '牛犊'), 'calf', 'hoofed', age='young', jitter=.5))
    add(Q('pig', PIG, _f('pig', PIG, ears='pointed', ear_size=.8, ear_in='#E58A8A'), ('pig', 'piggy'),
          ('猪', '小猪'), 'pink pig', 'hoofed'))
    add(Q('sheep', SHEEP, _f('sheep', SHEEP, ears='small', wool=True, under='#55504F', ear_in='#55504F'),
          ('sheep', 'ewe', 'woolly sheep'), ('羊', '绵羊'), 'woolly sheep', 'hoofed'))
    lamb = replace(SHEEP, L=.5, hip_h=.4, sh_h=.42, head_r=.21, eye_r=.18, coat='#F2E6DA', muzzle='#F2E6DA', cub=True)
    add(Q('sheep', lamb, _f('sheep', lamb, ears='small', wool=True, young=True, under='#F2E6DA', ear_in='#E8B8B0'),
          ('lamb', 'baby sheep', 'sheep'), ('小羊', '羔羊'), 'lamb', 'hoofed', age='young', jitter=.5))
    add(Q('goat', GOAT, _f('goat', GOAT, ears='small', ear_size=1.0, horns='goat', horn_c='#8A7A68'),
          ('goat', 'billy goat', 'mountain goat'), ('山羊',), 'goat with a beard', 'hoofed'))
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
        Variant('bee', variant='honey', genes=_insect.Bug('bee', '#2E2A27', '#F2C230'), plan='insect',
                poses=_insect.POSES['bee'], family='insect', face=Face('bee', '#F2C230'),
                names=('bee', 'honey bee', 'bumblebee'), zh=('蜜蜂', '小蜜蜂'), noun='honey bee'),
        Variant('beetle', variant='ladybug', genes=_insect.Bug('beetle', '#E53935'), plan='insect',
                poses=_insect.POSES['beetle'], family='insect', face=Face('beetle', '#E53935'),
                names=('ladybug', 'beetle'), zh=('瓢虫', '甲虫'), noun='red ladybug'),
        Variant('beetle', variant='green', genes=_insect.Bug('beetle', '#3E9B5A', spots='#2C6E40'), plan='insect',
                poses=_insect.POSES['beetle'], family='insect', face=Face('beetle', '#3E9B5A'),
                names=('beetle', 'green beetle', 'bug'), zh=('甲虫', '绿甲虫'), noun='green beetle'),
        Variant('butterfly', variant='monarch', genes=_insect.Bug('butterfly', '#F28C28', '#FFF4D6', spots='#2E2A27'),
                plan='insect', poses=_insect.POSES['butterfly'], family='insect', face=None,
                names=('butterfly', 'monarch butterfly'), zh=('蝴蝶',), noun='orange monarch butterfly'),
        Variant('butterfly', variant='blue', genes=_insect.Bug('butterfly', '#4A90E2', '#BFE3FF', spots='#1F3A68'),
                plan='insect', poses=_insect.POSES['butterfly'], family='insect', face=None,
                names=('blue butterfly', 'butterfly'), zh=('蓝蝴蝶', '蝴蝶'), noun='blue butterfly'),
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
                names=('chimpanzee', 'ape'), zh=('黑猩猩',), noun='chimpanzee'),
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
                       names=('hyena', 'spotted hyena', 'laughing hyena'), zh=('鬣狗', '斑鬣狗'), noun='spotted hyena'))
    out.append(Variant('porcupine', genes=PORCUPINE, family='rodent',
                       face=Face('porcupine', PORCUPINE.coat, PORCUPINE.under, '#9C8470', ears='round', ear_size=.6,
                                 quills=True, nose_c=C.NOSE),
                       names=('porcupine', 'quills'), zh=('豪猪', '箭猪'), noun='porcupine with raised quills'))
    out.append(Variant('elephant', 'any', 'adult', genes=ELEPHANT, family='elephant',
                       face=Face('elephant', ELEPHANT.coat, ELEPHANT.under, '#D9A8A8', ears='elephant', tusks=True),
                       names=('elephant', 'african elephant'), zh=('大象', '象'), noun='elephant with tusks'))
    out.append(Variant('elephant', 'any', 'young', genes=CALF, family='elephant',
                       face=Face('elephant', CALF.coat, CALF.under, '#E3B5B5', ears='elephant', young=True),
                       names=('baby elephant', 'elephant calf', 'calf', 'elephant'), zh=('小象', '象宝宝'),
                       noun='baby elephant', jitter=.5))
    return out


Bird = _bird.Bird
ROBIN = Bird('songbird', coat='#8B6B4E', belly='#F07A3A', wing_c='#76583F', beak_c='#E8B13A', leg_c='#B07A4A')
OWL = Bird('owl', body_rx=.26, body_ry=.3, tilt=72, head_r=.24, head_at=(.36, .02), beak='hook', beak_len=.05,
           beak_c='#E8B13A', coat='#9C7350', belly='#E8D2AE', wing_c='#86603F', disc='#F1E1C6', tufts=True,
           tail='short', tail_len=.1, tail_up=-10, leg_len=.08, leg_c='#E8B13A', feet='talons', iris='#F6C343',
           span=1.25)
EAGLE = Bird('eagle', body_rx=.38, body_ry=.22, tilt=38, head_r=.15, head_at=(.36, .14), beak='hook', beak_len=.13,
             beak_c='#F6C343', coat='#5A3D2B', head_c='#FAFAF7', tail_c='#FAFAF7', tail='fan', tail_len=.24,
             tail_up=-6, leg_len=.15, leg_c='#F6C343', feet='talons', brow=True, iris='#F6C343', span=1.5)
MACAW = Bird('parrot', body_rx=.27, body_ry=.2, tilt=58, head_r=.17, head_at=(.33, .06), beak='hook', beak_len=.13,
             beak_c='#F4F1EA', beak_lo='#3A3536', coat='#E53935', wing_c='#E53935', cheek='#FAFAF7',
             bands=('#F6C343', '#2F7FD6'), tail='long', tail_len=.55, tail_c='#E53935', tail_up=0, leg_len=.1,
             leg_c='#8A8A8A', span=1.3)
HEN = Bird('chicken', body_rx=.3, body_ry=.24, tilt=14, head_r=.13, head_at=(.33, .3), neck=.1, beak_len=.08,
           beak_c='#F2B33D', coat='#C8743A', wing_c='#A85E2E', comb='#E53935', tail='wedge', tail_len=.2, tail_up=55,
           leg_len=.18, leg_c='#F2B33D', span=.9)
DUCK = Bird('duck', body_rx=.36, body_ry=.2, tilt=6, head_r=.14, head_at=(.36, .3), neck=.1, beak='flat',
            beak_len=.15, beak_c='#F2B33D', coat='#B9B4AC', head_c='#2E7D4F', belly='#8A5A3C', wing_c='#9C968D',
            tail='short', tail_len=.12, tail_up=30, leg_len=.08, leg_c='#F28C28', feet='webbed', span=1.2)
PENGUIN = Bird('penguin', body_rx=.36, body_ry=.22, tilt=84, head_r=.15, head_at=(.4, -.02), beak_len=.1,
               beak_c='#F28C28', coat='#2E2A2B', belly='#FAFAF7', eye_ring='#FAFAF7', flippers=True, tail='short',
               tail_len=.08, tail_up=-30, leg_len=.04, leg_c='#F28C28', feet='webbed')
FLAMINGO = Bird('flamingo', body_rx=.28, body_ry=.15, tilt=12, head_r=.075, head_at=(.3, .3), neck=.55, beak='bent',
                beak_len=.13, beak_c='#F8C8D6', beak_tip='#2E2A2B', coat='#F48FB1', wing_c='#EF6F9A', tail='short',
                tail_len=.1, tail_up=10, leg_len=.62, leg_c='#F48FB1', span=1.2)


def _bf(g, **kw):
    """Front face for a bird variant."""
    return Face('bird', kw.pop('coat', g.head_c or g.coat), kw.pop('under', ''), beak=g.beak if g.beak != 'bent' else 'cone',
                beak_c=g.beak_c, comb=g.comb, crest=g.crest, disc=g.disc, ears='tufts' if g.tufts else 'none',
                iris=g.iris if g.kind in ('owl', 'eagle') else '', **kw)


def B(species, g, names, zh, noun, sex='any', age='adult', variant='', face=None, poses=_bird.POSES, jitter=1.0):
    return Variant(species, sex, age, variant, genes=g, face=face if face is not None else _bf(g), family='bird',
                   names=names, zh=zh, noun=noun, plan='bird', poses=poses, jitter=jitter)


def _birds():
    out = []
    add = out.append
    add(B('songbird', ROBIN, ('robin', 'bird', 'little bird', 'songbird'), ('知更鸟', '小鸟', '鸟'), 'robin',
          variant='robin'))
    blue = replace(ROBIN, coat='#3F7FD0', wing_c='#2F67B5', belly='#F2B27A', beak_c='#3A3536', leg_c='#6A6A6A')
    add(B('songbird', blue, ('bluebird', 'bird', 'little bird'), ('蓝鸲', '小鸟', '鸟'), 'bluebird', variant='blue'))
    cardinal = replace(ROBIN, coat='#D93A2F', wing_c='#B92F27', belly='', crest='#D93A2F', mask='#2E2A2B',
                       beak_c='#F28C28', leg_c='#B07A4A')
    add(B('songbird', cardinal, ('cardinal', 'red bird', 'bird'), ('红雀', '红鸟', '鸟'), 'red cardinal',
          variant='cardinal'))
    sparrow = replace(ROBIN, coat='#A57A57', wing_c='#7E5A3E', belly='#EADFCF', beak_c='#5A4A3A')
    add(B('songbird', sparrow, ('sparrow', 'bird', 'little brown bird'), ('麻雀', '小鸟', '鸟'), 'sparrow',
          variant='sparrow'))
    add(B('owl', OWL, ('owl', 'brown owl', 'night bird'), ('猫头鹰', '鸮'), 'brown owl'))
    snowy = replace(OWL, coat='#F4F1EA', belly='#FFFFFF', wing_c='#E6E0D4', disc='#FFFFFF', tufts=False)
    add(B('owl', snowy, ('snowy owl', 'white owl', 'owl'), ('雪鸮', '白猫头鹰'), 'snowy owl', variant='snowy'))
    add(B('eagle', EAGLE, ('eagle', 'bald eagle', 'bird of prey', 'hawk'), ('老鹰', '白头鹰', '鹰'), 'bald eagle'))
    add(B('parrot', MACAW, ('parrot', 'macaw', 'scarlet macaw'), ('鹦鹉', '金刚鹦鹉'), 'red macaw parrot',
          variant='macaw'))
    green = replace(MACAW, coat='#43A047', wing_c='#2E7D32', tail_c='#43A047', bands=('#2F7FD6',), cheek='',
                    head_c='#7CC576', beak_c='#3A3536', beak_lo='#3A3536')
    add(B('parrot', green, ('green parrot', 'parrot', 'parakeet'), ('绿鹦鹉', '鹦鹉'), 'green parrot', variant='green'))
    add(B('chicken', HEN, ('hen', 'chicken', 'farm bird'), ('母鸡', '鸡'), 'brown hen', sex='female'))
    white_hen = replace(HEN, coat='#FAFAF7', wing_c='#E8E3DA')
    add(B('chicken', white_hen, ('white hen', 'chicken', 'hen'), ('白母鸡', '鸡'), 'white hen', sex='female',
          variant='white'))
    rooster = replace(HEN, coat='#C0502E', wing_c='#8E3A22', head_c='#E6A03C', tail='rooster', tail_c='#2E5E4A',
                      tail_len=.42, comb='#E53935', body_ry=.25, leg_len=.2)
    add(B('chicken', rooster, ('rooster', 'cockerel', 'chicken'), ('公鸡', '鸡'), 'rooster', sex='male'))
    chick = replace(HEN, body_rx=.17, body_ry=.15, head_r=.13, head_at=(.16, .18), neck=0.0, coat='#F8D84A',
                    wing_c='#EBC63A', comb='', tail='short', tail_len=.05, leg_len=.08, beak_len=.05, young=True,
                    eye_r=.03)
    add(B('chicken', chick, ('chick', 'baby chick', 'little chick'), ('小鸡', '鸡仔'), 'yellow chick', age='young',
          jitter=.5))
    add(B('duck', DUCK, ('duck', 'mallard'), ('鸭子', '绿头鸭'), 'mallard duck', sex='male'))
    white_duck = replace(DUCK, coat='#FAFAF7', head_c='', belly='', wing_c='#E8E3DA', beak_c='#F28C28')
    add(B('duck', white_duck, ('white duck', 'duck', 'farm duck'), ('白鸭', '鸭子'), 'white duck', variant='white'))
    duckling = replace(DUCK, body_rx=.2, body_ry=.14, head_r=.12, head_at=(.2, .2), neck=0.0, coat='#F8D84A',
                       head_c='', belly='', wing_c='#EBC63A', beak_len=.09, leg_len=.06, young=True)
    add(B('duck', duckling, ('duckling', 'baby duck', 'duck'), ('小鸭', '鸭子'), 'yellow duckling', age='young',
          jitter=.5))
    add(B('penguin', PENGUIN, ('penguin', 'emperor penguin', 'bird'), ('企鹅',), 'penguin',
          face=_bf(PENGUIN, under='#FAFAF7'), poses=_bird.FLIGHTLESS_POSES))
    p_chick = replace(PENGUIN, body_rx=.24, body_ry=.17, head_r=.13, head_at=(.26, -.02), coat='#8E9196',
                      belly='#D9DCE0', eye_ring='#FAFAF7', beak_len=.06, young=True)
    add(B('penguin', p_chick, ('penguin chick', 'baby penguin', 'penguin'), ('小企鹅', '企鹅'), 'fluffy penguin chick',
          age='young', face=_bf(p_chick, under='#D9DCE0'), poses=_bird.FLIGHTLESS_POSES, jitter=.5))
    add(B('flamingo', FLAMINGO, ('flamingo', 'pink flamingo', 'wading bird'), ('火烈鸟',), 'pink flamingo'))
    return out


Reptile = _reptile.Reptile
Fish = _fish.Fish


def R(species, g, names, zh, noun, face, variant='', family='reptile', plan='reptile', poses=None, age='adult'):
    return Variant(species, 'any', age, variant, genes=g, face=face, family=family, names=names, zh=zh, noun=noun,
                   plan=plan, poses=poses or _reptile.POSES[g.kind], jitter=0)


def _reptiles_and_fish():
    out = []
    add = out.append
    turtle = Reptile('turtle')
    add(R('turtle', turtle, ('turtle', 'tortoise', 'green turtle'), ('乌龟', '龟'), 'turtle',
          Face('turtle', turtle.coat, '#D8E3A0')))
    snake = Reptile('snake', coat='#5DAA4A', mark='#3E7E35')
    add(R('snake', snake, ('snake', 'green snake'), ('蛇', '青蛇'), 'green snake',
          Face('snake', snake.coat, '#D8E3A0'), variant='green'))
    python = Reptile('snake', coat='#C9A15A', mark='#6B4A2E')
    add(R('snake', python, ('python', 'brown snake', 'snake'), ('蟒蛇', '蛇'), 'striped python',
          Face('snake', python.coat, '#EADBB0'), variant='python'))
    croc = Reptile('crocodile', coat='#5E8A3E', belly='#C9C98A')
    add(R('crocodile', croc, ('crocodile', 'alligator'), ('鳄鱼',), 'crocodile',
          Face('crocodile', croc.coat, '')))
    fish = (('goldfish', Fish('goldfish', '#F28C28', belly='#FBC36B', fin='#F6A44A'), ('goldfish', 'fish', 'orange fish'),
             ('金鱼', '鱼'), 'goldfish'),
            ('clown', Fish('clownfish', '#F27A1A', fin='#F28C28', bands='#2E2A27', tail='fan', body_ry=.23),
             ('clownfish', 'clown fish', 'fish'), ('小丑鱼', '鱼'), 'clownfish'),
            ('tang', Fish('tang', '#2F6FD6', fin='#2A4FA0', tail_c='#F6C343', tail='fork', dorsal='tall', body_ry=.28),
             ('blue fish', 'tang', 'fish'), ('蓝鱼', '鱼'), 'blue tang fish'))
    for variant, g, names, zh, noun in fish:
        add(R('fish', g, names, zh, noun, Face('fish', g.coat, g.belly, iris='',
                                              pattern='bands' if g.bands else 'none'),
              variant=variant, family='fish', plan='fish', poses=_fish.POSES))
    shark = Fish('shark', '#8A97A6', belly='#F1F3F5', fin='#7A8796', tail='moon', dorsal='shark', body_rx=.62,
                 body_ry=.2)
    add(R('shark', shark, ('shark', 'great white shark'), ('鲨鱼',), 'shark',
          Face('fish', shark.coat, shark.belly, horns='shark'), family='fish', plan='fish', poses=_fish.POSES))
    return out


Person = _human.Person
SKIN = (('light', '#F6D5BE'), ('tan', '#D9A07A'), ('brown', '#8D5A3B'))
ROLE_ZH = {'king': '国王', 'queen': '王后', 'villager': '村民', 'teacher': '老师', 'explorer': '探险家',
           'casual': '孩子', 'princess': '公主'}


def _people():
    """Role x age x sex looks, each in three skin tones; category "characters" (not stick-figure "people")."""
    looks = [
        # role, sex, age, noun, names, zh, genes
        ('king', 'male', 'adult', 'king with a crown and red cape', ('king', 'monarch'), ('国王',),
         Person('adult', 'male', hair='#3B2B24', hair_style='short', outfit='king', top='#7B3FA0', bottom='#4A2E6A',
                accent='#C62828', beard=True)),
        ('queen', 'female', 'adult', 'queen with a crown and gown', ('queen', 'monarch'), ('王后', '女王'),
         Person('adult', 'female', hair='#5A3A26', hair_style='long', outfit='queen', top='#8E44AD', bottom='#8E44AD',
                dress=True)),
        ('king', 'male', 'elder', 'old king with a white beard', ('old king', 'king'), ('老国王', '国王'),
         Person('elder', 'male', hair='#E6E2DA', hair_style='bald', outfit='king', top='#1F5FA8', bottom='#173F70',
                accent='#C62828', beard=True)),
        ('villager', 'male', 'adult', 'villager man in a tunic', ('villager', 'farmer', 'man'), ('村民', '农夫'),
         Person('adult', 'male', hair='#3B2B24', hair_style='short', outfit='villager', top='#6E9E4A',
                bottom='#6B5440', accent='#7A5230')),
        ('villager', 'female', 'adult', 'villager woman in a dress', ('villager', 'farmer', 'woman'), ('村妇', '村民'),
         Person('adult', 'female', hair='#2E2420', hair_style='bun', outfit='villager', top='#D9822B', bottom='#B5562E',
                dress=True)),
        ('teacher', 'male', 'adult', 'teacher in a shirt and tie', ('teacher', 'man', 'professor'), ('老师', '男老师'),
         Person('adult', 'male', hair='#2E2420', hair_style='short', outfit='teacher', top='#F1EEE6',
                bottom='#3D4A5C', accent='#C62828', glasses=True)),
        ('teacher', 'female', 'adult', 'teacher with glasses', ('teacher', 'woman'), ('老师', '女老师'),
         Person('adult', 'female', hair='#5A3A26', hair_style='ponytail', outfit='teacher', top='#3F7FD0',
                bottom='#2E3B55', accent='#F2C230', glasses=True, dress=True)),
        ('explorer', 'male', 'adult', 'explorer in a safari hat', ('explorer', 'adventurer', 'ranger'),
         ('探险家',), Person('adult', 'male', hair='#7A4A26', hair_style='short', outfit='explorer', top='#C2A36B',
                             bottom='#8E7A52', accent='#D8BE8A', shoes='#5A3A26')),
        ('explorer', 'female', 'adult', 'explorer woman in a safari hat', ('explorer', 'adventurer', 'ranger'),
         ('女探险家', '探险家'), Person('adult', 'female', hair='#2E2420', hair_style='ponytail', outfit='explorer',
                                     top='#C2A36B', bottom='#8E7A52', accent='#D8BE8A', shoes='#5A3A26')),
        ('casual', 'male', 'child', 'boy in a t-shirt and shorts', ('boy', 'child', 'kid'), ('男孩', '孩子'),
         Person('child', 'male', hair='#3B2B24', hair_style='short', outfit='casual', top='#E53935', bottom='#2F5FA8',
                shoes='#3A3536')),
        ('casual', 'female', 'child', 'girl in a dress', ('girl', 'child', 'kid'), ('女孩', '孩子'),
         Person('child', 'female', hair='#5A3A26', hair_style='ponytail', outfit='casual', top='#F48FB1',
                bottom='#F48FB1', shoes='#C2185B', dress=True)),
        ('princess', 'female', 'child', 'little princess with a tiara', ('princess', 'girl'), ('公主', '小公主'),
         Person('child', 'female', hair='#C98A3A', hair_style='long', outfit='princess', top='#F48FB1',
                bottom='#F48FB1', shoes='#C2185B', dress=True)),
        ('explorer', 'male', 'child', 'young explorer boy', ('boy explorer', 'boy', 'kid'), ('小探险家', '男孩'),
         Person('child', 'male', hair='#2E2420', hair_style='curly', outfit='explorer', top='#C2A36B',
                bottom='#8E7A52', accent='#D8BE8A', shoes='#5A3A26')),
        ('villager', 'male', 'elder', 'grandfather with a cane', ('grandfather', 'old man', 'grandpa'),
         ('爷爷', '老人'), Person('elder', 'male', hair='#D9D6D0', hair_style='bald', outfit='villager', top='#8A6A4A',
                                 bottom='#4A4A55', accent='#5A3A26', glasses=True, cane=True)),
        ('villager', 'female', 'elder', 'grandmother with a bun and shawl', ('grandmother', 'old woman', 'grandma'),
         ('奶奶', '老人'), Person('elder', 'female', hair='#E6E2DA', hair_style='bun', outfit='villager', top='#7B5EA7',
                                 bottom='#6A5090', accent='#C9B6E4', glasses=True, dress=True)),
    ]
    out = []
    for role, sex, age, noun, names, zh, g in looks:
        for tone, skin in SKIN:
            variant = f'{role}_{tone}'
            gg = replace(g, skin=skin)
            hat = 'crown' if role in ('king', 'queen') else 'tiara' if role == 'princess' else \
                'helmet' if role == 'explorer' else ''
            face = Face('human', skin, '', mane_c=g.hair, hair_style=g.hair_style, hat=hat, glasses=g.glasses,
                        beard=g.beard, mark_c=g.accent or '#C9A66B')
            out.append(Variant('human', sex, age, variant, genes=gg, face=face, family='human',
                               names=names, zh=zh, noun=f'{noun} ({tone} skin)', marks=(role,), plan='human',
                               poses=_human.POSES, category='characters', jitter=0))
    return out
