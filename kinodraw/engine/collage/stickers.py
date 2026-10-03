"""Paper stickers: any doodle in full colour with a white die-cut border, found by the words that name it."""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

import resvg_py
from PIL import Image, ImageOps

from ... import library
from .. import motion

TAP_HAND, CLOCK, HEART, SPARKLE = 'fl_backhand_index_pointing_up', 'fl_alarm_clock', 'fl_red_heart', 'fl_sparkles'


@lru_cache(maxsize=256)
def _svg(path: str, height: int) -> Image.Image:
    png = resvg_py.svg_to_bytes(svg_path=path, height=height)
    return Image.open(io.BytesIO(png)).convert('RGBA')


@lru_cache(maxsize=256)
def sticker(doodle_id: str, height: int = 220, project_dir: str | None = None) -> Image.Image | None:
    """The doodle ``height`` px tall with a paper border (about 6% of its height), or None if it doesn't exist."""
    path = library.resolve(doodle_id, Path(project_dir) if project_dir else None)
    if path is None:
        return None
    if path.suffix.lower() != '.svg':
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert('RGBA')
        image = image.resize((max(1, round(image.width * height / image.height)), height), Image.Resampling.LANCZOS)
        return motion.die_cut(image, border=max(8, round(height * .06)))
    return motion.die_cut(_svg(str(path), height), border=max(8, round(height * .06)))


_MATCHERS: dict = {}

# Words that products and promos use all the time, with the sticker a designer would pick (checked first).
CURATED = {
    'drink': 'fl_cup_with_straw', 'drinks': 'fl_cup_with_straw', 'coffee': 'fl_hot_beverage', 'tea': 'fl_teacup_without_handle',
    'bubble tea': 'fl_bubble_tea', 'movie': 'fl_popcorn', 'movies': 'fl_popcorn', 'movie night': 'fl_popcorn',
    'film': 'fl_clapper_board', 'cinema': 'fl_film_projector', 'werewolf': 'fl_wolf', 'werewolves': 'fl_wolf',
    'padel': 'fl_tennis', 'tennis': 'fl_tennis', 'ping pong': 'fl_ping_pong', 'pizza': 'fl_pizza', 'burger': 'fl_hamburger',
    'game night': 'fl_game_die', 'board games': 'fl_game_die', 'games': 'fl_video_game', 'gaming': 'fl_joystick',
    'app': 'fl_mobile_phone', 'phone': 'fl_mobile_phone', 'account': 'fl_bust_in_silhouette', 'email': 'fl_envelope',
    'e-mail': 'fl_envelope', 'mail': 'fl_envelope', 'link': 'fl_link', 'chat': 'fl_speech_balloon',
    'group chat': 'fl_speech_balloon', 'message': 'fl_speech_balloon', 'messages': 'fl_speech_balloon',
    'event': 'fl_spiral_calendar', 'events': 'fl_spiral_calendar', 'calendar': 'fl_calendar', 'party': 'fl_party_popper',
    'birthday': 'fl_birthday_cake', 'music': 'fl_musical_note', 'concert': 'fl_guitar', 'gym': 'fl_person_lifting_weights',
    'workout': 'fl_person_lifting_weights', 'study': 'fl_books', 'books': 'fl_books', 'hike': 'fl_mountain',
    'hiking': 'fl_mountain', 'camping': 'fl_camping', 'football': 'fl_soccer_ball', 'soccer': 'fl_soccer_ball',
    'basketball': 'fl_basketball', 'ticket': 'fl_ticket', 'tickets': 'fl_ticket', 'shop': 'fl_shopping_cart',
    'shopping': 'fl_shopping_cart', 'payment': 'fl_credit_card', 'pay': 'fl_credit_card', 'money': 'fl_money_bag',
    'launch': 'fl_rocket', 'idea': 'fl_light_bulb', 'ideas': 'fl_light_bulb', 'laptop': 'fl_laptop', 'computer': 'fl_laptop',
    'home': 'fl_house', 'dog': 'fl_dog_face', 'cat': 'fl_cat_face', 'soup': 'fl_bowl_with_spoon', 'call': 'fl_telephone_receiver',
    'reminder': 'fl_bell', 'reminders': 'fl_bell', 'done': 'fl_check_mark_button', 'wait': 'fl_hourglass_done',
    'seconds': 'fl_stopwatch', 'minutes': 'fl_stopwatch', 'travel': 'fl_airplane', 'trip': 'fl_world_map',
    'school': 'fl_school', 'class': 'fl_graduation_cap', 'podcast': 'fl_microphone', 'photo': 'fl_camera',
    'photos': 'fl_camera', 'design': 'fl_artist_palette', 'fast': 'fl_high_voltage', 'key': 'fl_key',
    'deal': 'fl_handshake', 'team': 'fl_handshake', 'hello': 'fl_waving_hand', 'thanks': 'fl_thumbs_up',
    'win': 'fl_trophy', 'growth': 'fl_chart_increasing', 'data': 'fl_bar_chart', 'settings': 'fl_gear',
    'search': 'fl_magnifying_glass_tilted_left', 'notes': 'fl_memo', 'write': 'fl_pencil',
    'drawing': 'fl_pencil', 'recording': 'fl_studio_microphone', 'editing': 'fl_scissors', 'video': 'fl_clapper_board',
    'videos': 'fl_clapper_board', 'script': 'fl_page_facing_up', 'voice': 'fl_speaker_high_volume',
    'captions': 'fl_speech_balloon', 'subtitles': 'fl_speech_balloon', 'chapters': 'fl_bookmark_tabs',
    'thumbnail': 'fl_framed_picture', 'story': 'fl_open_book', 'stories': 'fl_open_book', 'history': 'fl_classical_building',
    'science': 'fl_microscope',
    '喝酒': 'fl_cup_with_straw', '饮料': 'fl_cup_with_straw', '咖啡': 'fl_hot_beverage', '电影': 'fl_popcorn',
    '电影之夜': 'fl_popcorn', '狼人杀': 'fl_wolf', '网球': 'fl_tennis', '披萨': 'fl_pizza', '聚会': 'fl_party_popper',
    '邮件': 'fl_envelope', '电子邮件': 'fl_envelope', '群聊': 'fl_speech_balloon', '链接': 'fl_link', '活动': 'fl_spiral_calendar',
}


def curated(text: str, lang: str) -> str | None:
    """A designer's pick for a short phrase: the whole phrase, its last two words, then each word in order."""
    words = [w.strip('.,!?;:"\'') for w in text.lower().split()]
    phrases = [' '.join(words), ' '.join(words[-2:])] + words if lang == 'en' else [text.strip(' 。，！？')]
    for candidate in phrases:                       # the whole phrase, its ending, then each word (head noun first)
        if candidate in CURATED and library.resolve(CURATED[candidate]):
            return CURATED[candidate]
    return None


def find(text: str, lang: str, k: int = 1) -> list[str]:
    """The best doodles for a short phrase (a list item, a channel, a use): a designer's pick, then words, then
    meaning."""
    from ...director.match import Matcher
    pick = curated(text, lang)
    if pick and k == 1:
        return [pick]
    m = _MATCHERS.get(lang) or _MATCHERS.setdefault(lang, Matcher(lang))
    hits = m.lexical(text)
    if len(hits) < k:
        seen = {h.id for h in hits}
        hits += [h for h in m.semantic(text, k + 3) if h.id not in seen]
    return [h.id for h in sorted(hits, key=lambda h: -h.score)[:k]]
