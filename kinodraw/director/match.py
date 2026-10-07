"""Find doodles for a piece of text: literal keyword hits first, then meaning (small local embeddings)."""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .. import paths
from ..library import ASSETS, catalog

EMBED_MODELS = {'en': 'BAAI/bge-small-en-v1.5', 'zh': 'BAAI/bge-small-zh-v1.5', 'es': 'BAAI/bge-small-en-v1.5'}
CACHE = (Path(paths.getenv('KINODRAW_MODELS')).expanduser() / 'embed' if paths.getenv('KINODRAW_MODELS')
         else paths.cache_dir() / 'embed')
HF = 'https://huggingface.co/'
EMBED_FILES = {   # lang: (Hugging Face repo at a fixed revision, {file: (sha256, bytes)}), what fastembed loads
    'en': ('Qdrant/bge-small-en-v1.5-onnx-Q/resolve/aa8f8b060edb00e03bfdd08813a2949946c8ba55/', {
        'model_optimized.onnx': ('51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431', 66_465_124),
        'tokenizer.json': ('d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66', 711_396),
        'config.json': ('13582bcf2effc85b7bf3d3f5532e686bc1c9ce86bb009d10f0ec33cbe92299dd', 706),
        'tokenizer_config.json': ('0b29c7bfc889e53b36d9dd3e686dd4300f6525110eaa98c76a5dafceb2029f53', 1_242),
        'special_tokens_map.json': ('5d5b662e421ea9fac075174bb0688ee0d9431699900b90662acd44b2a350503a', 695)}),
    'zh': ('Qdrant/bge-small-zh-v1.5/resolve/46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59/', {
        'model_optimized.onnx': ('1294ea4b6331115a353d81f96b85e8c8d7fdcc284453d5b2fab5b016230aad38', 94_781_076),
        'tokenizer.json': ('48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26', 439_125),
        'config.json': ('9088751d39abbf86ec3d19ffca92ad62ad19075f7e59712e6c71217fa125d1d3', 739),
        'tokenizer_config.json': ('e6f3b96db926a37d4039995fbf5ad17de158dfb8f6343d607e4dbaad18d75f5a', 367),
        'special_tokens_map.json': ('b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3', 125)}),
}
_LOCK = threading.Lock()
EN_STOP = set('''a an the and or but if then so of to in on at by for with from as is are was were be been being it its
this that these those there here they them their we our you your he she his her i me my mine us not no yes do does did
done can could will would should may might must shall have has had just also very really more most much many few less
least some any all each every other another such same own than too only even still again ever never always often
sometimes first second third last next new old good bad big small great little long short high low one two three four
five six seven eight nine ten hundred thousand million billion way thing things time times day days year years people
make makes made take takes took get gets got go goes went come comes came see sees saw look looks know knows knew
think thinks thought say says said tell told use uses used want wants like likes need needs place part point case
number kind lot lots back up down out over under into onto about after before between during while where when why how
what which who whom whose because though although until since per via today now then once full turn
turns check step steps end side form set sort white black red blue green yellow orange pink purple brown gray grey
colour color colours colors'''.split())
ZH_STOP = set('时间 问题 方法 东西 事情 人们 一些 这个 那个 自己 今天 明天 现在 以后 以前 很多 非常 可以 需要 固定 工作 '
              '白色 黑色 红色 蓝色 绿色 黄色 橙色 粉色 紫色 棕色 灰色 颜色'.split())
ES_STOP = set('''el la los las un una unos unas de del al a ante bajo con contra desde durante en entre hacia
hasta para por según sin sobre tras y e o u pero que como cuando donde quien quienes cuyo cuya sus su mi mis
tu tus nuestro nuestra nuestros nuestras este esta estos estas ese esa esos esas aquel aquella aquellos aquellas
yo tú usted ustedes él ella ellos ellas nosotros nos me te se lo le les sí no ni es son era eran ser estar está
están fue fueron ha han hay había muy más menos mucho mucha muchos muchas poco poca pocos pocas todo toda todos
todas cada algún alguna algunos algunas otro otra otros otras también ya aún ahora entonces porque hacer hace
hacen hizo tener tiene tienen puede pueden uno dos tres'''.split())
ES_FOLD = str.maketrans('áéíóúü', 'aeiouu')


@lru_cache(maxsize=1)
def es_lexicon():
    return json.loads((ASSETS / 'es_en.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _es_folded():
    return {k.translate(ES_FOLD): v for k, v in es_lexicon().items()}


def _es_key(word: str) -> str:
    word = word.lower()
    lex = es_lexicon()
    folded = _es_folded()
    candidates = [word]
    if word.endswith('ces'):
        candidates.append(word[:-3] + 'z')
    if word.endswith('es'):
        candidates.append(word[:-2])
    if word.endswith('s'):
        candidates.append(word[:-1])
    if word.endswith('as'):
        candidates.append(word[:-2] + 'o')
    elif word.endswith('a'):
        candidates.append(word[:-1] + 'o')
    for candidate in candidates:
        gloss = lex.get(candidate) or folded.get(candidate.translate(ES_FOLD))
        if gloss:
            return _en_key(gloss)
    return ''


def _es_spans(text: str):
    """English glosses with their original Spanish spans; fixed phrases take precedence."""
    words = list(re.finditer(r'[^\W\d_]+', text))
    longest = max(len(k.split()) for k in es_lexicon())
    i = 0
    while i < len(words):
        for n in range(min(longest, len(words) - i), 1, -1):
            chunk = words[i:i + n]
            phrase = text[chunk[0].start():chunk[-1].end()]
            key = ' '.join(m.group().lower() for m in chunk)
            gloss = (es_lexicon().get(key) or _es_folded().get(key.translate(ES_FOLD))) \
                if re.fullmatch(r'[^\W\d_]+(?:\s+[^\W\d_]+)*', phrase) else None
            if gloss:
                yield _en_key(gloss), chunk[0].start(), chunk[-1].end()
                i += n
                break
        else:
            word = words[i]
            gloss = '' if word.group().lower() in ES_STOP else _es_key(word.group())
            if gloss:
                yield gloss, word.start(), word.end()
            i += 1


def es_gloss(text: str) -> str:
    return ' '.join(key for key, _, _ in _es_spans(text))


@dataclass
class Hit:
    id: str
    score: float
    phrase: str | None = None      # the text that matched (label and trigger), None for meaning-only matches
    start: int = -1                # where the phrase starts in the text


def singular(word: str) -> str:
    if len(word) > 4 and word.endswith('ies'):
        return word[:-3] + 'y'
    if len(word) > 4 and word.endswith(('ches', 'shes', 'sses', 'xes')):
        return word[:-2]
    if len(word) > 3 and word.endswith('s') and not word.endswith(('ss', 'us', 'is')):
        return word[:-1]
    return word


def _en_key(text: str) -> str:
    return ' '.join(singular(w) for w in re.findall(r"[a-z0-9']+", text.lower()))


class Matcher:
    def __init__(self, lang: str, include_fluent: bool = True, exclude_categories=('narrator',)):
        self.lang = lang
        self.entries = {i: e for i, e in searchable().items()
                        if e.get('category') not in exclude_categories and (include_fluent or e['set'] != 'fluent')}
        self.index: dict[str, list[tuple[str, float]]] = {}
        for did, e in self.entries.items():
            keywords = e.get('en' if lang == 'es' else lang) or []
            if e['set'] == 'fluent':
                keywords = keywords[:6]
            for rank, kw in enumerate(keywords):
                key = _en_key(kw) if lang in ('en', 'es') else kw.strip()
                if not key or (lang in ('en', 'es') and (key in EN_STOP or len(key) < 3 or key.isdigit())) or \
                        (lang == 'zh' and (len(key) < 2 or key in ZH_STOP)):
                    continue
                weight = (1.0 - .04 * min(rank, 5)) * (1.08 if e['set'] == 'bespoke' else .8)
                self.index.setdefault(key, []).append((did, weight))
        # keywords shared by many doodles say little about any one of them
        self.rarity = {k: 1 / (1 + math.log(len(v))) for k, v in self.index.items()}
        self._ids, self._vecs = None, None

    # ------------------------------------------------------------ literal hits
    def lexical(self, text: str, every_phrase: bool = False) -> list[Hit]:
        """Keyword hits, best first: one per doodle, or (``every_phrase``) one per doodle and phrase, so
        every picture a word could mean competes for that word."""
        hits: dict = {}
        if self.lang == 'en':
            words = [(m.group(0), m.start()) for m in re.finditer(r"[A-Za-z0-9']+", text)]
            for n in (3, 2, 1):
                for i in range(len(words) - n + 1):
                    chunk = words[i:i + n]
                    key = ' '.join(singular(w.lower()) for w, _ in chunk)
                    for did, weight in self.index.get(key, []):
                        score = weight * self.rarity[key] + .15 * (n - 1)
                        start = chunk[0][1]
                        phrase = text[start:chunk[-1][1] + len(chunk[-1][0])]
                        k = (did, start) if every_phrase else did
                        if k not in hits or hits[k].score < score:
                            hits[k] = Hit(did, score, phrase, start)
        elif self.lang == 'es':
            words = [(w, a, b) for gloss, a, b in _es_spans(text) for w in gloss.split()]
            for n in (3, 2, 1):
                for i in range(len(words) - n + 1):
                    chunk = words[i:i + n]
                    key = ' '.join(w for w, _, _ in chunk)
                    start, end = chunk[0][1], chunk[-1][2]
                    if re.search(r'[,;:.!?¿¡]', text[start:end]):
                        continue
                    for did, weight in self.index.get(key, []):
                        score = weight * self.rarity[key] + .15 * (n - 1)
                        k = (did, start) if every_phrase else did
                        if k not in hits or hits[k].score < score:
                            hits[k] = Hit(did, score, text[start:end], start)
        else:
            for key, owners in self.index.items():
                start = text.find(key)
                if start < 0:
                    continue
                for did, weight in owners:
                    score = weight * self.rarity[key] + .06 * (len(key) - 2)
                    k = (did, key) if every_phrase else did
                    if k not in hits or hits[k].score < score:
                        hits[k] = Hit(did, score, key, start)
        return sorted(hits.values(), key=lambda h: -h.score)

    # --------------------------------------------------------------- meaning
    def _catalog_vectors(self):
        """(ids, vectors) of the doodles this matcher may return, cut from the shared per-language table."""
        if self._vecs is None:
            ids, vecs = catalog_vectors(self.lang)
            keep = [k for k, i in enumerate(ids) if i in self.entries]
            self._ids, self._vecs = [ids[k] for k in keep], vecs[keep]
        return self._ids, self._vecs

    def semantic(self, text: str, k: int = 5) -> list[Hit]:
        if self.lang == 'es':
            text = es_gloss(text)
            if not text:
                return []
        ids, vecs = self._catalog_vectors()
        query = _normalize(np.array(list(_model(self.lang).embed([text])), np.float32))[0]
        sims = vecs @ query
        top = np.argsort(-sims)[:k]
        return [Hit(ids[i], float(sims[i]) + (.02 if self.entries[ids[i]]['set'] == 'bespoke' else 0)) for i in top]


def _entry_text(e: dict, lang: str) -> str:
    lang = 'en' if lang == 'es' else lang
    words = e.get(lang) or []
    return (f"{e.get('desc', '')}. {', '.join(words[:8])}" if lang == 'en'
            else f"{'，'.join(words[:8])}。{e.get('desc', '')}")


def _picture_text(e: dict, lang: str) -> str:
    """What the drawing shows, without its search keywords (so a keyword's other meanings don't leak in)."""
    return e.get('desc', '') if lang in ('en', 'es') else '，'.join((e.get('zh') or [])[:8])


TEXTS = {'embed': _entry_text, 'picture': _picture_text}


def searchable() -> dict:
    """Catalog entries that search may return: every pose of a creature preset stays resolvable by id, but
    only its canonical picture (standing, facing right) competes in search."""
    return {i: e for i, e in catalog().items() if e.get('search', True)}


def _table(lang: str, kind: str = 'embed'):
    lang = 'en' if lang == 'es' else lang
    entries = searchable()
    ids = sorted(entries)
    texts = [TEXTS[kind](entries[i], lang) for i in ids]
    digest = hashlib.sha256(('\n'.join(texts) + EMBED_MODELS[lang]).encode()).hexdigest()[:16]
    return ids, texts, digest


@lru_cache(maxsize=4)
def catalog_vectors(lang: str, kind: str = 'embed'):
    """Embeddings of every doodle ('embed': description + keywords, for search; 'picture': description
    only, for judging senses): shipped with the app, else cached, else computed once (about a minute)."""
    if lang == 'es':
        return catalog_vectors('en') if kind == 'embed' else catalog_vectors('en', kind)
    with _LOCK:
        ids, texts, digest = _table(lang, kind)
        for path in (ASSETS / f'{kind}-{lang}.npz', CACHE / f'catalog-{kind}-{lang}-{digest}.npz'):
            if path.exists():
                data = np.load(path)
                if str(data['digest']) == digest:
                    return ids, data['vecs'].astype(np.float32)
        vecs = _normalize(np.array(list(_model(lang).embed(texts)), np.float32))
        CACHE.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(CACHE / f'catalog-{kind}-{lang}-{digest}.npz', vecs=vecs.astype(np.float16), digest=digest)
        return ids, vecs


def bundle():
    """Write assets/doodles/{embed,picture}-<lang>.npz so new users never wait (run after changing the library)."""
    for lang in EMBED_MODELS:
        if lang == 'es':
            continue
        for kind in TEXTS:
            ids, texts, digest = _table(lang, kind)
            vecs = _normalize(np.array(list(_model(lang).embed(texts)), np.float32))
            np.savez_compressed(ASSETS / f'{kind}-{lang}.npz', vecs=vecs.astype(np.float16), digest=digest)
            print(lang, kind, len(ids), 'doodles ->', ASSETS / f'{kind}-{lang}.npz')


def _normalize(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)


def ensure_model(lang: str, progress=None) -> Path:
    """The doodle-search model for ``lang``, downloaded once from Hugging Face and checksum-verified;
    ``progress(done, total)`` in bytes. (fastembed's own download shows no byte progress and, for Chinese,
    falls back to a second host.)"""
    from ..net import download
    lang = 'en' if lang == 'es' else lang
    repo, files = EMBED_FILES[lang]
    folder = CACHE / f"{repo.split('/')[1]}-{repo.split('/')[3][:8]}"
    download([(HF + repo + name, folder / name, digest, size) for name, (digest, size) in files.items()], progress)
    return folder


@lru_cache(maxsize=3)
def _model(lang: str):
    if lang == 'es':
        return _model('en')
    from fastembed import TextEmbedding
    return TextEmbedding(EMBED_MODELS[lang], cache_dir=str(CACHE), specific_model_path=str(ensure_model(lang)))


if __name__ == '__main__':
    bundle()
