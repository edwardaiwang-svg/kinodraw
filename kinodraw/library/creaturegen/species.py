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
    out += _quads()
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
    cats = (('', CAT, 'ginger tabby cat', ('cat', 'ginger cat', 'tabby cat', 'kitty'), ('猫', '橘猫')),
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
    horses = (('', HORSE, 'bay horse', ('horse', 'brown horse', 'steed'), ('马', '骏马')),
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
          ('deer', 'stag', 'buck'), ('鹿', '雄鹿'), 'stag with antlers', 'hoofed', sex='male'))
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
    add(Q('pig', PIG, _f('pig', PIG, ears='pointed', ear_size=.8, ear_in='#E58A8A'), ('pig', 'piggy', 'hog'),
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
