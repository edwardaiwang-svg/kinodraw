"""Story sets: where a picture-book page takes place, drawn behind its cast.

A place read from the story (story.PLACES) becomes a set: library doodles plus a few original pictures drawn here in
the library's flat style (fills with a #1B1B1B outline), laid out for a 16:9 page with the cast's feet on
storybook.GROUND. Strips (a road, a floor, grass, a bus wall) span the page and are drawn at the page's own width.
Furniture records where things rest on it and where a figure sits or lies (SUPPORTS), so the storybook can put an
envelope on a desk against its lamp, a TV on its stand, and a sleeper on a couch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from types import SimpleNamespace

INK = 'stroke="#1B1B1B" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"'
THIN = 'stroke="#1B1B1B" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"'


def _svg(w, h, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{body}</svg>'


def _window(night):
    glass = '#2F3D5C' if night else '#BFE6F8'
    stars = ''.join(f'<path d="M{x} {y - 7}L{x + 2} {y - 2}L{x + 7} {y}L{x + 2} {y + 2}L{x} {y + 7}L{x - 2} {y + 2}'
                    f'L{x - 7} {y}L{x - 2} {y - 2}Z" fill="#FFE27A"/>' for x, y in ((92, 78), (168, 62), (150, 120)))
    return _svg(280, 250, (
        f'<rect x="40" y="20" width="200" height="170" fill="#FFFFFF" {INK}/>'
        f'<rect x="56" y="36" width="168" height="138" fill="{glass}" {THIN}/>' + (stars if night else '') +
        f'<path d="M140 36V174M56 105H224" fill="none" {THIN}/>'
        f'<path d="M30 14Q28 110 62 196L82 196Q58 110 64 14Z" fill="#E57373" {INK}/>'
        f'<path d="M250 14Q252 110 218 196L198 196Q222 110 216 14Z" fill="#E57373" {INK}/>'
        f'<rect x="16" y="6" width="248" height="12" rx="6" fill="#8D6E63" {THIN}/>'
        f'<rect x="28" y="190" width="224" height="16" rx="4" fill="#D7B98E" {INK}/>'))


def _desk():
    return _svg(320, 200, (
        f'<rect x="30" y="40" width="20" height="152" fill="#8D6E63" {INK}/>'
        f'<rect x="270" y="40" width="20" height="152" fill="#8D6E63" {INK}/>'
        f'<rect x="170" y="40" width="100" height="92" fill="#B5895A" {INK}/>'
        f'<path d="M170 86H270" {THIN}/><circle cx="220" cy="63" r="5" fill="#1B1B1B"/>'
        f'<circle cx="220" cy="109" r="5" fill="#1B1B1B"/>'
        f'<rect x="10" y="22" width="300" height="20" rx="4" fill="#C69C6D" {INK}/>'))


def _desk_lamp():
    return _svg(150, 190, (
        f'<ellipse cx="62" cy="176" rx="42" ry="9" fill="#546E7A" {INK}/>'
        f'<path d="M62 172L44 100L96 52" fill="none" stroke="#1B1B1B" stroke-width="16" stroke-linecap="round" '
        'stroke-linejoin="round"/>'
        '<path d="M62 172L44 100L96 52" fill="none" stroke="#78909C" stroke-width="8" stroke-linecap="round" '
        'stroke-linejoin="round"/>'
        f'<circle cx="44" cy="100" r="8" fill="#546E7A" {THIN}/>'
        f'<path d="M80 34L132 20L146 88Q118 98 96 84Z" fill="#F4B400" {INK}/>'
        f'<ellipse cx="121" cy="88" rx="16" ry="7" fill="#FFF3B0" {THIN}/>'))


def _table():
    return _svg(340, 180, (
        f'<rect x="34" y="40" width="18" height="134" fill="#8D6E63" {INK}/>'
        f'<rect x="288" y="40" width="18" height="134" fill="#8D6E63" {INK}/>'
        f'<rect x="40" y="40" width="260" height="22" fill="#9C7350" {INK}/>'
        f'<rect x="12" y="22" width="316" height="20" rx="5" fill="#B9875A" {INK}/>'))


def _armchair():
    return _svg(260, 220, (
        f'<rect x="40" y="18" width="180" height="130" rx="34" fill="#7E57C2" {INK}/>'
        f'<rect x="36" y="118" width="188" height="56" rx="14" fill="#9575CD" {INK}/>'
        f'<rect x="10" y="82" width="52" height="104" rx="24" fill="#7E57C2" {INK}/>'
        f'<rect x="198" y="82" width="52" height="104" rx="24" fill="#7E57C2" {INK}/>'
        f'<rect x="40" y="184" width="16" height="30" fill="#5D4037" {THIN}/>'
        f'<rect x="204" y="184" width="16" height="30" fill="#5D4037" {THIN}/>'))


def _tv_stand():
    return _svg(300, 100, (
        f'<rect x="12" y="14" width="276" height="70" rx="6" fill="#8D6E63" {INK}/>'
        f'<path d="M150 14V84" {THIN}/><circle cx="132" cy="49" r="5" fill="#1B1B1B"/>'
        f'<circle cx="168" cy="49" r="5" fill="#1B1B1B"/>'
        f'<rect x="28" y="84" width="16" height="12" fill="#5D4037" {THIN}/>'
        f'<rect x="256" y="84" width="16" height="12" fill="#5D4037" {THIN}/>'))


def _rug():
    return _svg(520, 70, (
        f'<ellipse cx="260" cy="35" rx="250" ry="28" fill="#E57373" {INK}/>'
        f'<ellipse cx="260" cy="35" rx="200" ry="17" fill="none" stroke="#FFCDD2" stroke-width="6"/>'))


def _counter():
    doors = ''.join(f'<rect x="{x}" y="60" width="86" height="168" rx="4" fill="#BCAAA4" {THIN}/>'
                    f'<rect x="{x + 66}" y="120" width="8" height="36" rx="4" fill="#5D4037"/>' for x in (24, 122, 220, 318))
    return _svg(430, 240, (
        f'<path d="M352 34V8Q352 -2 366 -2Q382 -2 382 14" fill="none" stroke="#1B1B1B" stroke-width="12" '
        'stroke-linecap="round"/>'
        '<path d="M352 34V8Q352 -2 366 -2Q382 -2 382 14" fill="none" stroke="#B0BEC5" stroke-width="6" '
        'stroke-linecap="round"/>'
        f'<rect x="14" y="50" width="402" height="184" fill="#A1887F" {INK}/>' + doors +
        f'<rect x="6" y="32" width="418" height="20" rx="4" fill="#ECEFF1" {INK}/>'
        f'<ellipse cx="366" cy="40" rx="40" ry="6" fill="#90A4AE" {THIN}/>'))


def _stove():
    knobs = ''.join(f'<circle cx="{x}" cy="26" r="8" fill="#ECEFF1" {THIN}/>' for x in (50, 90, 150, 190))
    return _svg(240, 270, (
        f'<rect x="20" y="6" width="200" height="40" rx="6" fill="#B0BEC5" {INK}/>' + knobs +
        f'<rect x="14" y="58" width="212" height="206" rx="6" fill="#ECEFF1" {INK}/>'
        f'<rect x="38" y="100" width="164" height="110" rx="8" fill="#37474F" {INK}/>'
        f'<rect x="54" y="80" width="132" height="10" rx="5" fill="#90A4AE" {THIN}/>'
        f'<rect x="8" y="44" width="224" height="16" rx="4" fill="#455A64" {INK}/>'))


def _fridge():
    return _svg(200, 420, (
        f'<rect x="14" y="10" width="172" height="404" rx="18" fill="#F1F5F7" {INK}/>'
        f'<path d="M14 150H186" {INK}/>'
        f'<rect x="150" y="50" width="14" height="70" rx="7" fill="#90A4AE" {THIN}/>'
        f'<rect x="150" y="180" width="14" height="110" rx="7" fill="#90A4AE" {THIN}/>'
        f'<rect x="40" y="60" width="34" height="26" rx="4" fill="#FFCA28" {THIN}/>'
        f'<circle cx="96" cy="200" r="12" fill="#EF5350" {THIN}/>'))


def _bookshelf():
    colours = ('#E53935', '#1E88E5', '#43A047', '#FDD835', '#8E24AA', '#FB8C00', '#00897B')
    books = []
    for row, y in enumerate((40, 126, 212, 298)):
        x = 30
        for k in range(6):
            w = 18 + (k * 7 + row * 5) % 14
            h = 58 + (k * 11 + row * 3) % 22
            books.append(f'<rect x="{x}" y="{y + 72 - h}" width="{w}" height="{h}" fill="{colours[(k + row * 2) % 7]}" {THIN}/>')
            x += w + 4
            if x > 196:
                break
    shelves = ''.join(f'<rect x="20" y="{y}" width="200" height="12" fill="#A1887F" {THIN}/>' for y in (112, 198, 284))
    return _svg(240, 390, (
        f'<rect x="12" y="16" width="216" height="366" rx="4" fill="#8D6E63" {INK}/>'
        f'<rect x="24" y="30" width="192" height="340" fill="#6D4C41"/>' + ''.join(books) + shelves +
        f'<rect x="12" y="370" width="216" height="14" fill="#8D6E63" {INK}/>'))


def _chalkboard():
    return _svg(460, 270, (
        f'<rect x="10" y="10" width="440" height="230" rx="8" fill="#8D6E63" {INK}/>'
        f'<rect x="30" y="30" width="400" height="190" fill="#2E7D32" {THIN}/>'
        '<path d="M70 90L90 60L110 90M78 78H102M140 60V90H160M196 66Q180 60 176 76Q174 92 196 88" fill="none" '
        'stroke="#F5F5F5" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M70 140H250M70 170H330M270 140H360" fill="none" stroke="#C8E6C9" stroke-width="5" '
        'stroke-linecap="round"/>'
        f'<rect x="60" y="238" width="340" height="14" rx="4" fill="#A1887F" {THIN}/>'))


def _school_desk():
    return _svg(220, 180, (
        f'<path d="M40 50L30 172M180 50L190 172" fill="none" stroke="#1B1B1B" stroke-width="12" stroke-linecap="round"/>'
        '<path d="M40 50L30 172M180 50L190 172" fill="none" stroke="#607D8B" stroke-width="6" stroke-linecap="round"/>'
        f'<rect x="44" y="56" width="132" height="34" fill="#B0BEC5" {THIN}/>'
        f'<rect x="10" y="30" width="200" height="22" rx="4" fill="#C69C6D" {INK}/>'))


def _shop_shelves():
    colours = ('#EF5350', '#42A5F5', '#66BB6A', '#FFCA28', '#AB47BC', '#FF7043')
    goods = []
    for row, y in enumerate((96, 186, 276)):
        for k in range(5):
            x = 34 + k * 74
            if (k + row) % 2:
                goods.append(f'<rect x="{x}" y="{y - 52}" width="52" height="52" rx="4" fill="{colours[(k + row) % 6]}" {THIN}/>')
            else:
                goods.append(f'<rect x="{x + 6}" y="{y - 60}" width="40" height="60" rx="14" '
                             f'fill="{colours[(k + row * 2) % 6]}" {THIN}/>'
                             f'<rect x="{x + 6}" y="{y - 40}" width="40" height="18" fill="#FFFFFF" {THIN}/>')
    shelves = ''.join(f'<rect x="20" y="{y}" width="380" height="14" fill="#CFD8DC" {THIN}/>' for y in (96, 186, 276))
    return _svg(420, 370, (
        f'<rect x="12" y="10" width="396" height="352" rx="6" fill="#90A4AE" {INK}/>'
        f'<rect x="24" y="22" width="372" height="330" fill="#ECEFF1"/>' + ''.join(goods) + shelves))


def _grocery_bag():
    return _svg(190, 240, (
        f'<path d="M58 70Q62 20 74 6Q88 18 84 72Z" fill="#E8C07A" {INK}/>'
        f'<path d="M96 74Q86 36 110 20Q126 40 118 76Z" fill="#66BB6A" {INK}/>'
        f'<path d="M106 74Q118 44 140 40Q146 60 130 78Z" fill="#43A047" {INK}/>'
        f'<circle cx="138" cy="74" r="20" fill="#FF822D" {INK}/>'
        f'<path d="M30 70L160 70L172 230L18 230Z" fill="#C8A26B" {INK}/>'
        f'<path d="M30 70L160 70L158 92L32 92Z" fill="#D9B886" {THIN}/>'
        '<path d="M60 120Q70 170 58 210M128 120Q120 170 132 210" fill="none" stroke="#A9824C" stroke-width="5" '
        'stroke-linecap="round"/>'))


def _streetlight():
    return _svg(130, 480, (
        f'<rect x="30" y="80" width="16" height="384" fill="#455A64" {INK}/>'
        f'<path d="M38 84Q38 30 96 30" fill="none" stroke="#1B1B1B" stroke-width="16" stroke-linecap="round"/>'
        '<path d="M38 84Q38 30 96 30" fill="none" stroke="#455A64" stroke-width="8" stroke-linecap="round"/>'
        f'<path d="M80 26H120L112 50H88Z" fill="#37474F" {INK}/>'
        f'<ellipse cx="100" cy="52" rx="14" ry="6" fill="#FFE082" {THIN}/>'
        f'<rect x="18" y="458" width="40" height="16" rx="4" fill="#37474F" {INK}/>'))


def _swing():
    return _svg(340, 320, (
        f'<path d="M40 310L90 20M150 310L90 20M190 310L250 20M300 310L250 20" fill="none" stroke="#1B1B1B" '
        'stroke-width="14" stroke-linecap="round"/>'
        '<path d="M40 310L90 20M150 310L90 20M190 310L250 20M300 310L250 20" fill="none" stroke="#E53935" '
        'stroke-width="8" stroke-linecap="round"/>'
        f'<rect x="80" y="12" width="180" height="16" rx="6" fill="#E53935" {INK}/>'
        f'<path d="M140 28V220M200 28V220" fill="none" {THIN}/>'
        f'<rect x="126" y="216" width="88" height="14" rx="5" fill="#FDD835" {INK}/>'))


def _church():
    return _svg(320, 470, '<g transform="translate(0,22)">' + (
        f'<rect x="40" y="200" width="240" height="240" fill="#F5E6CA" {INK}/>'
        f'<path d="M24 210L160 120L296 210Z" fill="#8D6E63" {INK}/>'
        f'<rect x="126" y="70" width="68" height="110" fill="#F5E6CA" {INK}/>'
        f'<path d="M116 76L160 10L204 76Z" fill="#8D6E63" {INK}/>'
        f'<path d="M160 10V-14M150 -4H170" fill="none" {INK}/>'
        f'<circle cx="160" cy="250" r="22" fill="#90CAF9" {THIN}/>'
        f'<path d="M134 440V350Q160 318 186 350V440Z" fill="#6D4C41" {INK}/>'
        f'<path d="M66 300V270Q80 252 94 270V300Z" fill="#90CAF9" {THIN}/>'
        f'<path d="M226 300V270Q240 252 254 270V300Z" fill="#90CAF9" {THIN}/>') + '</g>')


def _bush():
    return _svg(220, 130, (
        f'<path d="M14 124Q0 80 40 72Q46 30 92 40Q120 6 156 36Q206 34 200 84Q220 110 204 124Z" fill="#5DAE45" {INK}/>'
        '<path d="M70 92Q86 80 100 94M130 72Q144 62 156 76" fill="none" stroke="#3E8E2F" stroke-width="5" '
        'stroke-linecap="round"/>'))


def _porthole():
    return _svg(220, 220, (
        f'<circle cx="110" cy="110" r="100" fill="#B0BEC5" {INK}/>'
        f'<circle cx="110" cy="110" r="74" fill="#1F2A44" {THIN}/>'
        '<path d="M48 150Q110 110 172 150A74 74 0 0 1 48 150Z" fill="#42A5F5"/>'
        '<path d="M90 140Q104 130 120 138Q110 146 96 146Z" fill="#66BB6A"/>'
        + ''.join(f'<circle cx="{x}" cy="{y}" r="3" fill="#FFF59D"/>' for x, y in ((80, 70), (130, 60), (150, 96), (70, 104)))
        + ''.join(f'<circle cx="{110 + 88 * c}" cy="{110 + 88 * s}" r="6" fill="#78909C" {THIN}/>'
                  for c, s in ((1, 0), (-1, 0), (0, 1), (0, -1)))))


def _wall_clock():
    return _svg(120, 120, (
        f'<circle cx="60" cy="60" r="52" fill="#FFFFFF" {INK}/>'
        + ''.join(f'<path d="M{60 + 40 * c:.1f} {60 + 40 * s:.1f}L{60 + 46 * c:.1f} {60 + 46 * s:.1f}" {THIN}/>'
                  for c, s in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        + f'<path d="M60 60V28M60 60L82 70" fill="none" {INK}/>'))


def _remote():
    buttons = ''.join(f'<circle cx="{x}" cy="{y}" r="6" fill="{c}"/>' for x, y, c in (
        (24, 60, '#90A4AE'), (46, 60, '#90A4AE'), (24, 84, '#90A4AE'), (46, 84, '#90A4AE'), (35, 112, '#42A5F5')))
    return _svg(70, 180, (
        f'<rect x="8" y="8" width="54" height="164" rx="16" fill="#37474F" {INK}/>'
        f'<circle cx="35" cy="32" r="9" fill="#EF5350" {THIN}/>' + buttons))


def _bus_seat(colour):
    return _svg(210, 250, (
        f'<path d="M60 180L52 244M150 180L158 244" fill="none" stroke="#1B1B1B" stroke-width="12" stroke-linecap="round"/>'
        '<path d="M60 180L52 244M150 180L158 244" fill="none" stroke="#90A4AE" stroke-width="6" stroke-linecap="round"/>'
        f'<rect x="20" y="132" width="160" height="44" rx="14" fill="{colour}" {INK}/>'
        f'<rect x="138" y="20" width="50" height="160" rx="18" fill="{colour}" {INK}/>'
        f'<rect x="150" y="6" width="34" height="16" rx="8" fill="#B0BEC5" {THIN}/>'))


def _pole():
    return _svg(40, 600, (
        f'<rect x="12" y="6" width="16" height="588" rx="8" fill="#CFD8DC" {INK}/>'))


SVG = {
    'set_window': _window(False), 'set_window_night': _window(True), 'set_desk': _desk(), 'set_desk_lamp': _desk_lamp(),
    'set_table': _table(), 'set_armchair': _armchair(), 'set_tv_stand': _tv_stand(), 'set_rug': _rug(), 'set_counter': _counter(),
    'set_stove': _stove(), 'set_fridge': _fridge(), 'set_bookshelf': _bookshelf(), 'set_chalkboard': _chalkboard(),
    'set_school_desk': _school_desk(), 'set_shop_shelves': _shop_shelves(), 'set_grocery_bag': _grocery_bag(),
    'set_streetlight': _streetlight(), 'set_swing': _swing(), 'set_church': _church(), 'set_bush': _bush(),
    'set_porthole': _porthole(), 'set_wall_clock': _wall_clock(), 'set_remote': _remote(),
    'set_bus_seat': _bus_seat('#E53935'), 'set_train_seat': _bus_seat('#3F6FB5'), 'set_pole': _pole(),
}


# ------------------------------------------------------------------ strips: drawn at the page's own width
def _tile(width, step, make):
    return ''.join(make(x) for x in range(-step, int(width) + step, step))


@lru_cache(maxsize=64)
def strip(kind, width, height=90):
    """SVG of a page-wide strip ``width`` x ``height`` units (the caller picks a width matching the page)."""
    w, h = int(width), int(height)
    if kind == 'road':
        body = (f'<rect x="-10" y="0" width="{w + 20}" height="{h * .16:.0f}" fill="#D9D4CA" {THIN}/>'
                f'<rect x="-10" y="{h * .16:.0f}" width="{w + 20}" height="{h * .7:.0f}" fill="#8E949B" {INK}/>'
                + _tile(w, 150, lambda x: f'<rect x="{x}" y="{h * .47:.0f}" width="80" height="{h * .08:.0f}" '
                                          f'rx="3" fill="#F5F5F5"/>')
                + f'<rect x="-10" y="{h * .86:.0f}" width="{w + 20}" height="{h * .14:.0f}" fill="#D9D4CA" {THIN}/>')
    elif kind == 'floor':
        body = (f'<rect x="-10" y="{h * .3:.0f}" width="{w + 20}" height="{h * .7 + 10:.0f}" fill="#DDBE93"/>'
                + _tile(w, 230, lambda x: f'<path d="M{x} {h * .3:.0f}L{x - 40} {h}" stroke="#C9A877" stroke-width="4"/>')
                + f'<rect x="-10" y="0" width="{w + 20}" height="{h * .3:.0f}" fill="#F7F3EA" {THIN}/>')
    elif kind == 'busfloor':
        body = (f'<rect x="-10" y="{h * .3:.0f}" width="{w + 20}" height="{h * .7 + 10:.0f}" fill="#9EA7AD"/>'
                + _tile(w, 60, lambda x: f'<path d="M{x} {h * .45:.0f}H{x + 30}" stroke="#7D878E" stroke-width="5"/>')
                + f'<rect x="-10" y="0" width="{w + 20}" height="{h * .3:.0f}" fill="#5D6B73" {THIN}/>')
    elif kind == 'grass':
        body = (f'<path d="M-10 {h * .35:.0f}' + _tile(w, 120, lambda x: f'Q{x + 30} {h * .15:.0f} {x + 60} {h * .32:.0f}'
                                                                      f'T{x + 120} {h * .35:.0f}')
                + f'L{w + 130} {h + 10}L-10 {h + 10}Z" fill="#9CCC65" {INK}/>'
                + _tile(w, 170, lambda x: f'<path d="M{x + 40} {h * .8:.0f}l6 -16l6 16M{x + 110} {h * .65:.0f}l5 -14l5 14" '
                                          'fill="none" stroke="#689F38" stroke-width="4" stroke-linecap="round"/>'))
    elif kind == 'sand':
        body = (f'<path d="M-10 {h * .3:.0f}Q{w * .3:.0f} {h * .1:.0f} {w * .6:.0f} {h * .28:.0f}T{w + 10} {h * .25:.0f}'
                f'L{w + 10} {h + 10}L-10 {h + 10}Z" fill="#F3D98B" {INK}/>'
                + _tile(w, 140, lambda x: f'<circle cx="{x + 50}" cy="{h * .7:.0f}" r="3" fill="#D8B866"/>'))
    elif kind == 'sea':
        body = (f'<path d="M-10 {h * .25:.0f}' + _tile(w, 100, lambda x: f'Q{x + 25} {h * .05:.0f} {x + 50} {h * .25:.0f}'
                                                                      f'T{x + 100} {h * .25:.0f}')
                + f'L{w + 110} {h + 10}L-10 {h + 10}Z" fill="#4FA8DE" {INK}/>'
                + _tile(w, 180, lambda x: f'<path d="M{x + 30} {h * .6:.0f}q20 -10 40 0" fill="none" stroke="#B3E0F7" '
                                          'stroke-width="5" stroke-linecap="round"/>'))
    elif kind == 'hills':
        body = (f'<path d="M-10 {h * .55:.0f}C{w * .12:.0f} {h * .05:.0f} {w * .3:.0f} {h * .1:.0f} {w * .45:.0f} {h * .45:.0f}'
                f'C{w * .6:.0f} {h * .1:.0f} {w * .85:.0f} {h * .0:.0f} {w + 10} {h * .4:.0f}'
                f'L{w + 10} {h + 10}L-10 {h + 10}Z" fill="#AED581" {INK}/>')
    elif kind == 'fence':
        body = (f'<rect x="-10" y="{h * .3:.0f}" width="{w + 20}" height="{h * .12:.0f}" fill="#FFFFFF" {THIN}/>'
                f'<rect x="-10" y="{h * .68:.0f}" width="{w + 20}" height="{h * .12:.0f}" fill="#FFFFFF" {THIN}/>'
                + _tile(w, 60, lambda x: f'<path d="M{x + 10} {h - 2}V{h * .14:.0f}L{x + 24} 2L{x + 38} {h * .14:.0f}'
                                         f'V{h - 2}Z" fill="#FFFFFF" {THIN}/>'))
    elif kind in ('buswall', 'trainwall'):
        panel, stripe = ('#F6D77A', '#E53935') if kind == 'buswall' else ('#DCE6EE', '#3F6FB5')
        body = (f'<rect x="-10" y="{h * .06:.0f}" width="{w + 20}" height="{h:.0f}" fill="{panel}" {INK}/>'
                + _tile(w, 300, lambda x: f'<rect x="{x + 40}" y="{h * .14:.0f}" width="220" height="{h * .42:.0f}" '
                                          f'rx="18" fill="#BFE6F8" {INK}/>')
                + f'<rect x="-10" y="{h * .7:.0f}" width="{w + 20}" height="{h * .06:.0f}" fill="{stripe}" {THIN}/>'
                + f'<rect x="-10" y="0" width="{w + 20}" height="{h * .06:.0f}" fill="#B0BEC5" {INK}/>')
    elif kind == 'spacewall':
        body = (f'<rect x="-10" y="0" width="{w + 20}" height="{h:.0f}" fill="#CFD8DC" {INK}/>'
                + _tile(w, 240, lambda x: f'<rect x="{x + 20}" y="{h * .08:.0f}" width="200" height="{h * .84:.0f}" '
                                          f'rx="14" fill="#B0BEC5" {THIN}/>'))
    else:
        raise KeyError(kind)
    return _svg(w, h, body)


# The unit height each strip is drawn at: its outline then keeps the library's weight on the page.
STRIP_UNITS = {'buswall': 560, 'trainwall': 560, 'spacewall': 640}


def svg(doodle_id):
    """The original SVG of a set picture, or None for a library doodle."""
    return SVG.get(doodle_id)


# ------------------------------------------------------------------ supports
# Where things rest and figures sit or lie on a picture, as shares of its viewBox: (kind, x0, x1, y).
# kind: 'top' (a surface: desk, table, counter, stove, stand), 'seat' (couch, chair, bench), 'bed'.
SUPPORTS = {
    'set_desk': ('top', .05, .95, .11), 'set_table': ('top', .05, .95, .12), 'set_tv_stand': ('top', .06, .94, .14),
    'set_counter': ('top', .03, .74, .14), 'set_stove': ('top', .08, .92, .17), 'set_school_desk': ('top', .06, .94, .17),
    'office_desk': ('top', .06, .5, .45), 'fl_couch_and_lamp': ('seat', .13, .7, .76), 'fl_bed': ('bed', .16, .93, .43),
    'fl_chair': ('seat', .22, .78, .56), 'set_armchair': ('seat', .24, .76, .56), 'empty_bench': ('seat', .1, .86, .56), 'set_bus_seat': ('seat', .12, .62, .54),
    'set_train_seat': ('seat', .12, .62, .54),
}


# ------------------------------------------------------------------ sets per place
# A piece: (doodle, x, ground, height) on the page, or ('strip:<kind>', top, bottom) across it, or
# (doodle, 'on:<support doodle>', height[, share along its surface]) resting on an earlier piece. Wall pieces (windows, boards, clocks) hang
# above the floor line. A window shows the page's sun or moon.
FLOOR, BACKLINE = .785, .7
INTERIOR = {'room', 'living_room', 'bedroom', 'study', 'kitchen', 'dining', 'bathroom', 'office', 'classroom', 'hospital',
            'shop', 'library', 'cafe', 'bus', 'train', 'space'}
# Nature places keep the story's own trees, rivers and hills: their set only fills a page that is otherwise empty.
NATURE = {'forest', 'jungle', 'countryside', 'outdoors'}
_ROOM = ('strip:floor', .725, .805)
SETS = {
    'room': [_ROOM, ('set_window', .5, .42, .24)],          # a room the story does not furnish (a hallway, a stage)
    'town': [('strip:road', .69, .8), ('fl_house', .1, BACKLINE, .27), ('fl_deciduous_tree', .27, BACKLINE, .3),
             ('house', .46, BACKLINE, .3), ('fl_evergreen_tree', .63, BACKLINE, .26),
             ('fl_house_with_garden', .81, BACKLINE, .27), ('set_streetlight', .96, BACKLINE, .34)],
    'street': [('strip:road', .69, .8), ('store_front', .14, BACKLINE, .27), ('fl_house', .4, BACKLINE, .26),
               ('set_streetlight', .58, BACKLINE, .36), ('fl_deciduous_tree', .7, BACKLINE, .28),
               ('fl_house_with_garden', .88, BACKLINE, .26)],
    'city': [('strip:road', .69, .8), ('fl_office_building', .1, BACKLINE, .42), ('fl_department_store', .3, BACKLINE, .34),
             ('set_streetlight', .5, BACKLINE, .36), ('fl_office_building', .72, BACKLINE, .4),
             ('fl_convenience_store', .91, BACKLINE, .26)],
    'house': [('strip:grass', .7, .805), ('fl_deciduous_tree', .12, .76, .36), ('fl_house_with_garden', .72, .76, .44)],
    'living_room': [_ROOM, ('set_window', .64, .42, .24), ('fl_framed_picture', .2, .34, .1),
                    ('fl_couch_and_lamp', .2, FLOOR, .34), ('set_rug', .47, .8, .045),
                    ('set_tv_stand', .82, FLOOR, .1), ('fl_television', 'on:set_tv_stand', .17)],
    'bedroom': [_ROOM, ('set_window', .58, .42, .24), ('fl_bed', .2, FLOOR, .24), ('set_desk', .8, FLOOR, .21),
                ('set_desk_lamp', 'on:set_desk', .14, .8)],
    'study': [_ROOM, ('set_window', .56, .42, .24), ('set_bookshelf', .1, FLOOR, .4), ('set_desk', .76, FLOOR, .21),
              ('set_desk_lamp', 'on:set_desk', .14, .8), ('fl_closed_book', 'on:set_desk', .05, .08)],
    'kitchen': [_ROOM, ('set_fridge', .08, FLOOR, .42), ('set_window', .36, .45, .22), ('set_counter', .36, FLOOR, .21),
                ('set_stove', .66, FLOOR, .22), ('fl_potted_plant', 'on:set_counter', .07, .06),
                ('set_table', .86, FLOOR, .17)],
    'dining': [_ROOM, ('set_window', .24, .46, .26), ('fl_framed_picture', .78, .34, .1), ('fl_chair', .56, FLOOR, .22),
               ('set_table', .72, FLOOR, .18), ('fl_chair', .89, FLOOR, .22),
               ('fl_fork_and_knife_with_plate', 'on:set_table', .05)],
    'bathroom': [_ROOM, ('set_window', .56, .4, .2), ('fl_bathtub', .2, FLOOR, .24), ('fl_toilet', .85, FLOOR, .21)],
    'office': [_ROOM, ('set_window', .3, .46, .26), ('fl_file_cabinet', .08, FLOOR, .24), ('office_desk', .75, FLOOR, .3),
               ('fl_potted_plant', .94, FLOOR, .14)],
    'classroom': [_ROOM, ('set_chalkboard', .5, .5, .26), ('set_wall_clock', .86, .3, .09),
                  ('set_school_desk', .16, FLOOR, .17), ('set_school_desk', .84, FLOOR, .17)],
    'school': [('strip:grass', .7, .805), ('fl_deciduous_tree', .12, .76, .34), ('school_building', .66, .76, .42)],
    'hospital': [_ROOM, ('set_window', .6, .42, .24), ('fl_bed', .2, FLOOR, .24), ('fl_potted_plant', .9, FLOOR, .14)],
    'shop': [_ROOM, ('set_shop_shelves', .13, FLOOR, .38), ('set_counter', .64, FLOOR, .19),
             ('cash_register', 'on:set_counter', .09), ('set_shop_shelves', .92, FLOOR, .38)],
    'market': [('strip:road', .69, .8), ('market_stall', .18, BACKLINE, .32), ('market_stall', .82, BACKLINE, .32)],
    'cafe': [_ROOM, ('set_window', .26, .46, .26), ('fl_potted_plant', .07, FLOOR, .16), ('fl_chair', .58, FLOOR, .22),
             ('set_table', .74, FLOOR, .18), ('fl_chair', .9, FLOOR, .22), ('coffee_cup', 'on:set_table', .06)],
    'library': [_ROOM, ('set_bookshelf', .09, FLOOR, .4), ('set_bookshelf', .27, FLOOR, .4), ('set_table', .76, FLOOR, .18),
                ('fl_books', 'on:set_table', .07)],
    'bus': [('strip:buswall', .14, .74), ('strip:busfloor', .725, .805), ('set_bus_seat', .12, FLOOR, .24),
            ('set_pole', .28, FLOOR, .64), ('set_bus_seat', .74, FLOOR, .24), ('set_bus_seat', .92, FLOOR, .24)],
    'train': [('strip:trainwall', .14, .74), ('strip:busfloor', .725, .805), ('set_train_seat', .12, FLOOR, .24),
              ('set_pole', .28, FLOOR, .64), ('set_train_seat', .74, FLOOR, .24), ('set_train_seat', .92, FLOOR, .24)],
    'car': [('strip:road', .69, .8), ('fl_deciduous_tree', .14, BACKLINE, .3), ('fl_evergreen_tree', .86, BACKLINE, .26),
            ('fl_automobile', .72, .79, .2)],
    'park': [('strip:grass', .7, .805), ('fl_deciduous_tree', .1, .76, .4), ('fl_evergreen_tree', .3, .72, .26),
             ('empty_bench', .76, .79, .17), ('set_bush', .93, .79, .09)],
    'garden': [('strip:grass', .7, .805), ('strip:fence', .58, .73), ('fl_sunflower', .12, .79, .2),
               ('fl_tulip', .22, .79, .12), ('fl_potted_plant', .82, .79, .14), ('fl_deciduous_tree', .94, .76, .38)],
    'beach': [('strip:sea', .58, .7), ('strip:sand', .66, .805), ('fl_palm_tree', .1, .76, .42),
              ('fl_umbrella_on_ground', .8, .79, .24)],
    'farm': [('strip:grass', .7, .805), ('strip:fence', .6, .74), ('farm_barn', .74, .74, .38), ('fl_tractor', .2, .79, .16)],
    'playground': [('strip:grass', .7, .805), ('fl_playground_slide', .18, .79, .3), ('set_swing', .82, .79, .34)],
    'stadium': [('strip:grass', .7, .805), ('fl_stadium', .5, .72, .4)],
    'church': [('strip:grass', .7, .805), ('fl_deciduous_tree', .14, .76, .36), ('set_church', .72, .76, .5)],
    'camp': [('strip:grass', .7, .805), ('fl_evergreen_tree', .1, .74, .34), ('fl_tent', .76, .78, .26),
             ('fl_fire', .5, .79, .08), ('fl_evergreen_tree', .95, .74, .3)],
    'space': [('strip:spacewall', .1, .805), ('set_porthole', .28, .5, .28), ('set_porthole', .74, .5, .28)],
    'night_sky': [('strip:hills', .66, .805), ('fl_star', .45, .16, .05), ('fl_star', .62, .26, .04),
                  ('fl_star', .3, .22, .04)],
    'forest': [('strip:grass', .7, .805), ('fl_evergreen_tree', .08, .76, .38), ('fl_evergreen_tree', .26, .72, .28),
               ('fl_deciduous_tree', .74, .74, .32), ('fl_evergreen_tree', .92, .76, .4)],
    'jungle': [('fl_palm_tree', .12, .78, .5), ('fl_deciduous_tree', .88, .78, .5)],
    'countryside': [('strip:hills', .62, .805), ('fl_deciduous_tree', .14, .78, .34), ('set_bush', .86, .79, .09)],
    'outdoors': [('strip:grass', .7, .805), ('fl_deciduous_tree', .12, .78, .4), ('set_bush', .3, .79, .08),
                 ('fl_evergreen_tree', .88, .78, .34)],
}
# Rooms sky shows through: their window's glass.
WINDOWS = {'set_window', 'set_window_night'}
# Plan pictures that are a place: the page is that set instead of one more picture on it.
PICTURE_PLACES = (
    (r'house|home', 'town'), (r'city|skyline|office_building|department_store', 'city'), (r'^fl_bus$|oncoming_bus', 'bus'),
    (r'bus_stop', 'street'), (r'train|tram|metro', 'train'), (r'school', 'school'), (r'hospital', 'hospital'),
    (r'store|shop(?!ping)|market', 'shop'), (r'barn|farm', 'farm'), (r'stadium', 'stadium'),
    (r'beach', 'beach'), (r'playground', 'playground'), (r'tent|camp', 'camp'), (r'forest', 'forest'),
    (r'church|chapel', 'church'), (r'cafe|restaurant', 'cafe'),
)


def picture_place(doodle_id):
    """The place a plan picture stands for (a house, a bus, a school), or None."""
    return next((place for pattern, place in PICTURE_PLACES if re.search(pattern, doodle_id)), None)


@dataclass
class Piece:
    """One picture of a page's set or one thing in it. x is its centre (frame width share), ground its bottom and
    height its drawn height (frame height shares). Strips span the page between top and ground."""
    doodle: str
    x: float = .5
    ground: float = FLOOR
    height: float = .2
    kind: str = 'set'              # 'strip' | 'wall' | 'set' | 'thing' | 'hand'
    top: float = 0.
    rotate: float = 0.
    mirror: bool = False
    motion: str | None = None      # 'roll' | 'fall' | 'fly' | 'bounce'
    cue: float | None = None       # span-local seconds the motion starts
    to: tuple = (0., 0.)           # (dx, dground) the motion carries it by
    holder: str | None = None      # cast id whose hand holds it
    front: bool = False            # drawn over the cast
    lone: bool = False             # drawn large: the only thing on a page with nobody on it


@dataclass
class Support:
    """Where things rest on a placed picture, or where a figure sits or lies on it (frame shares).
    ``y`` is the surface/seat line; a figure sitting on it puts its seat there, a sleeper lies along it."""
    kind: str                      # 'top' | 'seat' | 'bed'
    doodle: str
    x0: float
    x1: float
    y: float
    piece: Piece


# ------------------------------------------------------------------ staging a page
# Drawn heights (frame height shares) of things a line names; a person is about .42.
HEIGHTS = {
    'fl_couch_and_lamp': .34, 'set_armchair': .26, 'fl_bed': .24, 'set_desk': .21, 'office_desk': .3, 'set_table': .18, 'set_counter': .21,
    'set_stove': .22, 'fl_chair': .22, 'empty_bench': .17, 'fl_television': .17, 'set_fridge': .42,
    'set_bookshelf': .4, 'set_desk_lamp': .14, 'fl_mantelpiece_clock': .09, 'fl_potted_plant': .12,
    'fl_framed_picture': .1, 'fl_bicycle': .2, 'set_grocery_bag': .13, 'fl_tangerine': .06, 'fl_red_apple': .06,
    'fl_egg': .045, 'fl_soccer_ball': .08, 'fl_laptop': .09, 'fl_desktop_computer': .13, 'fl_envelope': .072,
    'fl_page_facing_up': .09, 'fl_closed_book': .065, 'coffee_cup': .065, 'fl_bowl_with_spoon': .075,
    'fl_shallow_pan_of_food': .065, 'fl_fork_and_knife_with_plate': .065, 'fl_pancakes': .08, 'fl_banana': .065,
    'fl_mobile_phone': .08, 'fl_kitchen_knife': .08, 'set_remote': .065, 'fl_backpack': .13, 'fl_package': .1,
    'fl_birthday_cake': .1, 'fl_glass_of_milk': .08, 'fl_newspaper': .09, 'fl_wrapped_gift': .1, 'fl_tulip': .1,
    'fl_balloon': .14, 'fl_kite': .12, 'fl_umbrella': .14, 'fl_guitar': .16, 'fl_teddy_bear': .1,
    'fl_strawberry': .045, 'fl_bread': .065, 'fl_cookie': .045, 'fl_spoon': .08, 'fl_fork_and_knife': .08,
}
ROLE_HEIGHT = {'top': .19, 'seat': .22, 'bed': .24, 'stand': .3, 'screen': .17, 'small': .11, 'hand': .1,
               'round': .065, 'wall': .1}
MAX_THINGS = 5
OWN_SCALE = 1.4
LONE = 1.6
# Where a thing goes when the line does not say: a pan on the stove, plates on the table, a lamp on a desk.
PREFER = {'fl_shallow_pan_of_food': ('set_stove',), 'fl_fork_and_knife_with_plate': ('set_table',),
          'set_desk_lamp': ('set_desk', 'office_desk'), 'fl_laptop': ('set_desk', 'office_desk', 'set_table'),
          'fl_desktop_computer': ('set_desk', 'office_desk'), 'coffee_cup': ('set_table',),
          'fl_birthday_cake': ('set_table',), 'fl_pancakes': ('set_table', 'set_counter')}
OUTDOOR_BUILT = {'town', 'street', 'city', 'house', 'school', 'market', 'car', 'park', 'garden', 'beach', 'farm',
                 'playground', 'stadium', 'church', 'camp', 'night_sky'}
FURNITURE_ROLES = {'top', 'seat', 'bed', 'stand', 'screen', 'wall'}
HOLDING = {'stand', 'walk', 'run', 'look', 'happy', 'sit', 'scared', 'carry'}


class Stager:
    """Where each page of one story takes place and what is in it. The place carries over from line to line until
    the text names a new one; a line with no place cue keeps the place its scene's text named, then the last place,
    then the scene's own (a plan picture of a house, a bus); a thing that does not belong in a place carried over
    from an earlier scene (a page out in the street) brings back the last place it fits; within a scene only a
    place that scene or the next one names can take it (a grocery bag on the bus, when the story goes on to the
    street). A page with no place at all, and nothing else on it, is outdoors."""

    def __init__(self, book):
        self.book = book
        self.place = None
        self.history = []
        self.thing = None              # the last thing a line named: what "his" or "it" on a desk is
        self.previous = (None, [])     # (place, pieces) of the last line: its things stay where they ended up

    # ---------------- reading
    def scene(self, pictures, text='', after=''):
        """A scene's plan pictures, sorted: the place they stand for, the things to stage and the scenery; and the
        first place its text names, for the lines before it when the story has not named one yet; and every place
        it and the scene ``after`` it name, where a thing that does not fit the room can go."""
        from ..director.v3.story import THING_ROLE, places_in
        from ..library import catalog
        from .storybook import _animal, _sky
        named = places_in(text)
        out = {'place': None, 'text': None, 'things': [], 'scenery': [], 'ahead': named[0] if named else None,
               'named': list(dict.fromkeys(named + places_in(after)))}
        for p in pictures:
            if _sky(p) or _animal(p):
                continue
            place = picture_place(p)
            category = (catalog().get(p) or {}).get('category')
            if place:
                out['place'] = out['place'] or place
            elif p in THING_ROLE or p in SUPPORTS or category not in ('Animals & Nature', 'nature', 'Travel & Places',
                                                                       'places', 'transport'):
                role = THING_ROLE.get(p) or ({'top': 'top', 'seat': 'seat', 'bed': 'bed'}[SUPPORTS[p][0]]
                                             if p in SUPPORTS else 'small')
                out['things'].append({'doodle': p, 'role': role, 'homes': (), 'at': None, 'on': None,
                                      'motion': None, 'target': False, 'plan': True})
            else:
                out['scenery'].append(p)
        return out

    def where(self, line, scene):
        """The place of one line (see the class)."""
        place = line.place or scene['text'] or self.place or scene['place'] or scene.get('ahead')
        moved = bool(line.place)
        if not moved:
            for t in line.things:
                if t['homes'] and place not in t['homes']:
                    if scene['text']:   # within a scene the room it named holds (a bowl of popcorn in the den),
                        fit = next((p for p in scene.get('named', ()) if p in t['homes']), None)  # unless it
                    else:               # names one this thing belongs in (the bag, then the street it spilled in)
                        fit = next((p for p in reversed(self.history) if p in t['homes']), t['homes'][0])
                    if fit:
                        place, moved = fit, True
                        break
        if moved:
            scene['text'] = place
        if place:
            self.place = place
            if not self.history or self.history[-1] != place:
                self.history.append(place)
        return place

    def things(self, line, scene, place):
        """The things a page stages: the line's own, the last line's when the set continues, then the plan's."""
        own, named = [], []
        for t in line.things:
            t = dict(t)
            if t['doodle'] is None:
                if self.thing is None:
                    continue
                t['doodle'], t['role'] = self.thing
            elif not t['target'] and t['role'] not in FURNITURE_ROLES:
                named.append(t)
            own.append(t)
        if named:
            self.thing = (named[-1]['doodle'], named[-1]['role'])
        last_place, last = self.previous
        carried = [{'doodle': p.doodle, 'role': SUPPORTS[p.doodle][0] if p.kind == 'set' else 'small',
                    'homes': (), 'at': None, 'on': None,
                    'motion': None, 'target': False, 'piece': p} for p in last] if place == last_place else []
        plan = scene['things'][:2] if len(own) < 3 else []
        out, seen = [], set()
        held = [t for t in carried if t['piece'].kind == 'hand']
        for t in [t for t in carried if t not in held] + own + held + plan:
            if t['doodle'] not in seen:
                seen.add(t['doodle'])
                out.append(t)
        return out

    # ---------------- geometry
    def frame(self, doodle, x, ground, height, mirror=False):
        """(X, Y, box) mapping a point of the doodle's viewBox (shares) to the frame when it stands at (x, ground)
        with this drawn height; box is its drawn (x0, y0, x1, y1)."""
        from .storybook import _bbox, _box, _svg
        left, top, right, bottom = _bbox(doodle, mirror)
        box = _box(doodle, height)
        _, sw, sh = _svg(doodle)
        w, h = self.book.size
        width = box * sw / sh * h / w
        mid = (left + right) / 2
        X = lambda fx: x + ((1 - fx if mirror else fx) - mid) * width
        Y = lambda fy: ground - (bottom - fy) * box
        return X, Y, (x + (left - mid) * width, ground - (bottom - top) * box, x + (right - mid) * width, ground)

    def half(self, doodle, height):
        x0, _, x1, _ = self.frame(doodle, .5, 1., height)[2]
        return (x1 - x0) / 2

    def support_of(self, piece):
        spec = SUPPORTS.get(piece.doodle)
        if not spec:
            return None
        kind, fx0, fx1, fy = spec
        X, Y, _ = self.frame(piece.doodle, piece.x, piece.ground, piece.height, piece.mirror)
        x0, x1 = sorted((X(fx0), X(fx1)))
        return Support(kind, piece.doodle, x0, x1, Y(fy), piece)

    # ---------------- staging
    def stage_explicit(self, shot, place, props, figures, at=lambda s: s, night=False, set_refs=()):
        """Stage a page from explicit ids instead of the text (a plan's shot): the set for ``place`` (a SETS key),
        the furniture in ``set_refs`` and ``props``, each {ref, relation: none|on|against|in|under|beside|behind|
        held_by, to, motion: roll|fall|drop|fly|None, at}, where ``at`` (passed to ``at()``, seconds by default) is
        when the motion starts. Fills shot.set and shot.supports like stage(); returns whether a set was built."""
        things = [explicit_thing(ref) for ref in set_refs] + [explicit_thing(**p) for p in props]
        line = SimpleNamespace(place=place, things=things, text='')
        return self.stage(shot, line, self.scene([]), place, figures, at, not figures, night)

    def stage(self, shot, line, scene, place, figures, at, empty, night=False):
        """Fill shot.set and shot.supports for one line. Returns the sky doodles the page still draws in its sky
        (an interior shows them through its window instead)."""
        built = place in SETS and (place not in NATURE or empty)
        if place is None and empty:
            place, built = 'outdoors', True
        pieces = []
        self._figures = [f for f in figures if not f.crowd]
        self._begin = shot.start
        if built:
            for spec in SETS[place]:
                if spec[0].startswith('strip:'):
                    pieces.append(Piece(spec[0][6:], 0.5, spec[2], spec[2] - spec[1], kind='strip', top=spec[1]))
                elif isinstance(spec[1], str):
                    host = next((p for p in reversed(pieces) if p.doodle == spec[1][3:]), None)
                    s = self.support_of(host) if host is not None else None
                    if s is not None:
                        at_share = spec[3] if len(spec) > 3 else .5
                        self._rest(pieces, host, spec[0], spec[2], kind='set', near=s.x0 + at_share * (s.x1 - s.x0))
                else:
                    doodle, x, ground, height = spec
                    if doodle in WINDOWS and night:
                        doodle = 'set_window_night'
                    pieces.append(Piece(doodle, x, ground, height, kind='wall' if ground < .6 else 'set'))
        things = self.things(line, scene, place)
        base = len(pieces)
        indoor = place in INTERIOR
        placed = 0
        # Furniture first, so the small things have somewhere to rest.
        for t in sorted(things, key=lambda t: t['role'] not in FURNITURE_ROLES):
            if placed >= MAX_THINGS:
                break
            if self._place(pieces, t, place, indoor, at):
                placed += 1
        shot.set = pieces
        shot.supports = [s for s in (self.support_of(p) for p in pieces) if s]
        named = {t['doodle'] for t in line.things if t['doodle']} | ({self.thing[0]} if self.thing else set())
        # What the line set down stays for the next line on the same set, where its motion left it.
        # So does furniture a line brought in (the armchair someone sat in), for as long as the place holds.
        self.previous = (place, [p for p in pieces[base:] if (p.kind in ('thing', 'hand') and p.doodle in named)
                                 or (p.kind == 'set' and p.doodle in SUPPORTS)])
        return built

    def _has(self, pieces, doodle):
        return next((p for p in pieces if p.doodle == doodle), None)

    def _place(self, pieces, t, place, indoor, at):
        doodle, role = t['doodle'], t['role']
        height = HEIGHTS.get(doodle, ROLE_HEIGHT.get(role, .09))
        if t['at'] is not None and role in ('small', 'hand', 'round'):
            height *= OWN_SCALE            # what the line names reads at a glance
        if t.get('piece') is not None:
            return self._keep(pieces, t['piece'])
        if role in FURNITURE_ROLES and t.get('plan') and not indoor:
            return False                       # the plan's desk is not out in the street
        if role in ('top', 'seat', 'bed', 'stand'):
            if self._has(pieces, doodle) or (t.get('plan') and role == 'top' and any(
                    SUPPORTS.get(p.doodle, ('',))[0] == 'top' for p in pieces)):
                return False
            x = self._floor_x(pieces, self.half(doodle, height), prefer=(.8, .2, .64, .92, .08))
            pieces.append(Piece(doodle, x, FLOOR, height, kind='set'))
            return True
        if role == 'screen':
            if self._has(pieces, doodle):
                return False
            stand = self._has(pieces, 'set_tv_stand')
            if stand is None:
                x = self._floor_x(pieces, self.half('set_tv_stand', .1), prefer=(.82, .18, .65))
                stand = Piece('set_tv_stand', x, FLOOR, .1, kind='set')
                pieces.append(stand)
            return self._rest(pieces, stand, doodle, height, kind='thing') is not None
        if role == 'wall':
            if self._has(pieces, doodle):
                return False
            x = self._floor_x(pieces, self.half(doodle, height), prefer=(.3, .7, .5), wall=True)
            pieces.append(Piece(doodle, x, .36, height, kind='wall'))
            return True
        if self._has(pieces, doodle) and not t['motion'] and t['on'] is None:
            return False                       # the set already shows it (the study's lamp)
        piece = None
        relation = t['on']
        if relation:
            kind, target = relation
            host = self._has(pieces, target)
            if host is None and target in SUPPORTS:
                host = Piece(target, self._floor_x(pieces, self.half(target, HEIGHTS.get(target, .19)),
                                                   prefer=(.75, .25)), FLOOR, HEIGHTS.get(target, .19), kind='set')
                pieces.append(host)
            elif host is None:
                desk = next((p for p in pieces if SUPPORTS.get(p.doodle, ('',))[0] == 'top'), None)
                if desk is not None:
                    host = self._rest(pieces, desk, target, HEIGHTS.get(target, .09), kind='thing')
            if host is not None:
                if kind == 'on' and host.doodle in SUPPORTS:
                    piece = self._rest(pieces, host, doodle, height)
                elif kind in ('against', 'beside'):
                    piece = self._beside(pieces, host, doodle, height, lean=kind == 'against')
                elif kind == 'under':
                    piece = Piece(doodle, host.x, FLOOR + .01, height, kind='thing')
                    pieces.append(piece)
        if piece is None and role in ('hand', 'round') and not t['motion']:
            piece = self._hand(pieces, doodle, height)
        if piece is None and not t['motion']:
            desk = [p for p in pieces if SUPPORTS.get(p.doodle, ('',))[0] == 'top']
            desk.sort(key=lambda p: p.doodle not in PREFER.get(doodle, ()))
            for host in desk:
                piece = self._rest(pieces, host, doodle, height)
                if piece:
                    break
        if piece is None and not indoor and t['homes'] and set(t['homes']) <= INTERIOR:
            return False                       # a remote or a lamp is not left out on the lawn
        if piece is None:
            lone = not self._figures and not indoor and role != 'stand'
            height *= LONE if lone else 1.
            ground = FLOOR + .015
            near = next((p for p in reversed(pieces) if p.kind == 'thing' and abs(p.ground - ground) < .02), None)
            half = self.half(doodle, height)
            if near is not None and t['motion']:
                x = near.x + self.half(near.doodle, near.height) + half + .01
            else:
                x = self._floor_x(pieces, half, prefer=(.42, .3, .56, .2, .7), things=True)
            piece = Piece(doodle, x, ground, height, kind='thing', front=True, lone=lone)
            pieces.append(piece)
        if t['motion']:
            self._move(pieces, piece, t['motion'], at)
        return True

    def _keep(self, pieces, old):
        """A thing from the last line, where it ended up: in the same hand if its holder is still on the page."""
        if self._has(pieces, old.doodle):
            return False
        if old.kind == 'hand':
            if old.holder not in [f.key for f in self._figures]:
                return False
            pieces.append(Piece(old.doodle, old.x, old.ground, old.height, kind='hand', holder=old.holder, front=True))
            return True
        x, ground, rotate, height = old.x, old.ground, old.rotate, old.height
        if old.motion in ('roll', 'fly'):
            x, ground = x + old.to[0], ground + old.to[1]
        elif old.motion == 'fall':
            rotate = 10.
        lone = old.lone and not self._figures
        if old.lone and not lone:
            # The cast walks onto the page: the thing shown large on its own shrinks back and steps aside.
            height /= LONE
            x = self._floor_x(pieces, self.half(old.doodle, height), prefer=(x, .3, .7, .2, .8), things=True)
        pieces.append(Piece(old.doodle, x, ground, height, kind='set' if old.kind == 'set' else 'thing', rotate=rotate,
                            front=old.front, lone=lone))
        return True

    def _on(self, pieces, s):
        """(x0, x1) of everything already standing on support s."""
        return [(x0, x1) for p in pieces if p is not s.piece and p.kind in ('set', 'thing')
                and abs(p.ground - s.y - .004) < .006 and s.x0 - .02 <= p.x <= s.x1 + .02
                for x0, _, x1, _ in [self.frame(p.doodle, p.x, p.ground, p.height, p.mirror)[2]]]

    def _rest(self, pieces, host, doodle, height, kind='thing', near=None):
        """A thing standing on the host's surface, beside the others already on it; None when it is full."""
        s = self.support_of(host)
        if s is None:
            return None
        half = self.half(doodle, height)
        busy = self._on(pieces, s)
        lo, hi = s.x0 + half, s.x1 - half
        if lo > hi:
            return None
        centre = (s.x0 + s.x1) / 2 if near is None else near
        for x in sorted((lo + (hi - lo) * i / 30 for i in range(31)), key=lambda x: abs(x - centre)):
            if all(x + half <= a - .004 or x - half >= b + .004 for a, b in busy):
                piece = Piece(doodle, x, s.y + .004, height, kind=kind)
                pieces.append(piece)
                return piece
        return None

    def _beside(self, pieces, host, doodle, height, lean=False):
        """A thing set down touching the host (an envelope propped against a lamp), on the same surface."""
        half = self.half(doodle, height)
        hx0, _, hx1, _ = self.frame(host.doodle, host.x, host.ground, host.height, host.mirror)[2]
        under = next((s for s in (self.support_of(p) for p in pieces) if s and abs(host.ground - s.y - .004) < .006
                      and s.x0 - .02 <= host.x <= s.x1 + .02), None)
        busy = [b for b in self._on(pieces, under) if not b[0] <= host.x <= b[1]] if under else []
        for side in (-1, 1):
            x = (hx0 - half + .006) if side < 0 else (hx1 + half - .006)
            inside = under is None or under.x0 <= x - half and x + half <= under.x1
            if inside and all(x + half <= a or x - half >= b for a, b in busy):
                piece = Piece(doodle, x, host.ground, height, kind='thing', rotate=side * -8. if lean else 0.)
                pieces.append(piece)
                return piece
        return None

    def _hand(self, pieces, doodle, height):
        """A thing in a cast member's hand: the first figure free to hold one."""
        held = {p.holder for p in pieces if p.kind == 'hand'}
        f = next((f for f in self._figures if f.key not in held and f.pose in HOLDING and f.carried is None), None)
        if f is None:
            return None
        piece = Piece(doodle, f.x, f.ground, height, kind='hand', holder=f.key, front=True)
        pieces.append(piece)
        return piece

    def _floor_x(self, pieces, half, prefer, wall=False, things=False):
        """A free spot on the floor (or wall) for something half as wide as ``half``: clear of the cast and of
        other furniture, nearest the preferred spots in order."""
        boxes = []
        for p in pieces:
            if p.kind == 'strip' or (p.kind == 'wall') != wall or p.doodle == 'set_rug':     # a rug is walked on
                continue
            x0, _, x1, _ = self.frame(p.doodle, p.x, p.ground, p.height, p.mirror)[2]
            boxes.append((x0, x1))
        if not wall:
            for f in self._figures:
                if f.pose in ('sit', 'lie', 'sleep'):
                    continue                   # they will sit or lie on the furniture, not stand in its way
                w = self.book._half(f)
                boxes.append((f.x - w * .8, f.x + w * .8 + f.travel))

        def cost(x, rank):
            covered = sum(max(0., min(x + half, b) - max(x - half, a)) for a, b in boxes)
            return round(covered, 3), rank
        spots = [(x, i) for i, x in enumerate(prefer)] + [(.04 + .92 * k / 46, len(prefer) + abs(k - 23) / 46)
                                                            for k in range(47)]
        spots = [(min(1 - half - .01, max(half + .01, x)), rank) for x, rank in spots]
        return min(spots, key=lambda s: cost(*s))[0]

    def _move(self, pieces, piece, motion, at):
        """A thing that rolls, falls, flies or bounces when its verb is spoken: an orange rolls into the road."""
        kind, offset = motion
        piece.motion, piece.cue = kind, at(offset)
        if kind == 'fall':
            piece.cue = min(piece.cue, self._begin + .25)     # the line is about the fallen thing: it lands first
        if kind == 'roll':
            road = next((p for p in pieces if p.kind == 'strip' and p.doodle == 'road'), None)
            # Away from the cast, toward the open side of the page.
            cast = [f.x for f in self._figures]
            right = (sum(cast) / len(cast) < piece.x) if cast else piece.x < .55
            dx = min(.3, .94 - piece.x) if right else -min(.3, piece.x - .06)
            dg = ((road.top + road.ground) / 2 + piece.height / 2 - piece.ground) if road else 0.
            piece.to = (dx, dg)
        elif kind == 'fly':
            piece.to = (.22 if piece.x < .55 else -.22, -.4)
        elif kind == 'fall':
            piece.to = (0., 0.)


def explicit_thing(ref, relation=None, to=None, motion=None, at=0., **_):
    """A thing to stage from explicit ids (see Stager.stage_explicit), in the form story.py reads from text."""
    from ..director.v3.story import THING_ROLE
    role = THING_ROLE.get(ref) or (SUPPORTS[ref][0] if ref in SUPPORTS else 'small')
    kind = {'on': 'on', 'in': 'on', 'against': 'against', 'beside': 'beside', 'behind': 'beside',
            'under': 'under'}.get(relation or '')
    if relation == 'held_by':
        role = 'hand'
    motion = {'drop': 'fall', 'falls': 'fall', 'rolls': 'roll', 'flies': 'fly'}.get(motion, motion)
    return {'doodle': ref, 'role': role, 'homes': (), 'at': None, 'on': (kind, to) if kind and to else None,
            'motion': (motion, at) if motion in ('roll', 'fall', 'fly') else None, 'target': False}


SETTLE = re.compile(r"\b(?:(?P<lie>sprawl\w*|stretch\w*\s+out|curl\w*\s+up|lies|lay|lying|flops?|flopped|collaps\w*)|"
                    r"(?P<sit>sits?|sat|sitting|squeez\w*|plops?|plopped|settl\w*|sinks?|sank|slump\w*|perch\w*|"
                    r"climb\w*|curls?|curled|snuggl\w*|cuddl\w*))\b[^.;!?]{0,25}?\b(?:on|onto|in|into)\s+"
                    r"(?:the|a|an|his|her|their|our|my|its)\s+(?:\w+\s+)?(?P<what>couch|sofa|settee|armchair|chair|"
                    r"stool|bench|bed|seat|hammock)", re.I)


def settles(text):
    """('sit' or 'lie', char offset of the verb) when a line puts someone onto a seat or bed ("squeezes onto the
    couch", "sprawled on the bed", "sinks into the armchair"); None otherwise."""
    m = SETTLE.search(text or '')
    if not m:
        return None
    return ('lie' if m.group('lie') else 'sit'), m.start()


def seat_for(supports, pose, prefer=()):
    """The support a figure in this pose can use: a bed or couch to lie or sleep on, a seat (couch, chair, bench,
    bus seat) or a bed's edge to sit on; None when the page has none. The cast's layout calls this; sit the figure
    with its seat on support.y between support.x0 and x1, or lay it along support.y. ``prefer``: doodles the line
    names ("sits in the armchair") or the figure rested on before, used first."""
    order = {'sit': ('seat', 'bed'), 'sleep': ('bed', 'seat'), 'lie': ('bed', 'seat')}.get(pose, ())
    usable = [s for s in supports if s.kind in order]
    for doodle in prefer:
        chosen = next((s for s in usable if s.doodle == doodle), None)
        if chosen:
            return chosen
    for kind in order:
        found = [s for s in usable if s.kind == kind]
        if found:
            return found[0]
    return None
