"""Markup in a script that is a picture, never a voice or a caption.

- A fenced code block (```python ... ```) is shown as code (engine/markup_boards.py): never read aloud, never
  captioned, its language tag included. The voice pauses while it types in.
- A display math line ("A = P(1 + r)^n", $$...$$, \\[...\\]) is typeset on the board; the voice says it in words
  ("A equals P times one plus r, to the power of n") and the caption leaves it to the board.
- A numbered list ("1. ...", "2) ...") gets a step indicator that stays on screen while its steps are read.
- A warning callout ("> ⚠️ Never share ...", "Warning: ...") gets a warning card with its own words.
- A key combo ("Ctrl + Shift + N", "Cmd+K") is drawn as keycaps.

Ingest keeps the fences (code exactly as written) and list numbers; script.py turns them into beats with a
``markup`` entry; speech.hidden leaves fences and display math out of the voice and the captions.
"""
from __future__ import annotations

import re

FENCE = re.compile(r'(?P<fence>```|~~~)[ \t]*(?P<lang>[\w+#.-]*)[^\n]*\n?(?P<code>.*?)(?:\n?[ \t]*(?P=fence)|\Z)', re.S)
FENCE_LINE = re.compile(r'^\s*(```|~~~)')
STEP = re.compile(r'^(\d{1,2})[.)]\s+(?=\S)')
# A paragraph that is a warning: it opens with a warning sign, or with a warning word and a colon.
WARNING = re.compile(r'^\W*?(?:⚠|🚫|⛔|❗|‼|☢|☣)|^\s*(?:\*\*)?(?:warning|caution|danger|important|never)\b\s*(?:\*\*)?\s*[:!—–-]',
                     re.I)
MODIFIERS = r'(?:Ctrl|Control|Cmd|Command|⌘|Shift|⇧|Alt|AltGr|Option|Opt|⌥|Win|Windows|Super|Meta|Fn)'
KEY = (MODIFIERS[:-1] + r'|Esc|Escape|Tab|Enter|Return|Space|Spacebar|Delete|Del|Backspace|Home|End|PgUp|PgDn|'
       r'PageUp|PageDown|Insert|Ins|F\d{1,2}|Up|Down|Left|Right|[←→↑↓]|[A-Z0-9]|[`\-=\[\];\',./\\])')
COMBO = re.compile(r'(?<![\w+])' + MODIFIERS + r'(?:\s*\+\s*' + KEY + r')+(?![\w+])')
FUNCS = {'sin', 'cos', 'tan', 'log', 'ln', 'exp', 'sqrt', 'max', 'min', 'lim', 'sum', 'mod'}


# ------------------------------------------------------------------ code
def code_block(text: str):
    """(language tag, code) when ``text`` is one fenced code block, else None."""
    m = FENCE.fullmatch(text.strip())
    if not m:
        return None
    return m.group('lang').lower(), m.group('code').rstrip('\n')


def fence_spans(text: str) -> list[tuple[int, int]]:
    """Every fenced block in ``text`` (an unclosed fence runs to the end)."""
    return [m.span() for m in FENCE.finditer(text)]


def hold(display: str) -> float | None:
    """Seconds of silence a code beat keeps for its code to type in (None for any other beat)."""
    found = code_block(display)
    if not found:
        return None
    lines = [line for line in found[1].split('\n') if line.strip()]
    return round(min(4., max(1.5, .5 * len(lines))), 2)


# ------------------------------------------------------------------ math
def _unwrap(text: str) -> str | None:
    s = text.strip()
    for a, b in (('$$', '$$'), ('\\[', '\\]'), ('$', '$')):
        if len(s) > len(a) + len(b) and s.startswith(a) and s.endswith(b):
            return s[len(a):-len(b)].strip()
    return None


def math_line(text: str) -> bool:
    """Whether ``text`` is a display formula on its own line: $$...$$, \\[...\\], or an equation of short symbols
    ("A = P(1 + r)^n", "E = mc^2", "a² + b² = c²"), never a sentence ("Total = $50 per month")."""
    inner = _unwrap(text)
    if inner is not None:
        return True
    s = text.strip()
    if not s or len(s) > 80 or '\n' in s or not re.search(r'[=≈≤≥]', s) or s[-1] in ':?!,':
        return False
    if re.search(r'[$€£¥%]|https?:|@', s):
        return False
    words = re.findall(r'[A-Za-z]+', s)
    if not words or any(len(w) > 3 and w.lower() not in FUNCS for w in words):
        return False
    return bool(re.fullmatch(r"[\w\s=≈≤≥<>+\-−*×·/÷^()\[\]{}.,'²³¹⁰⁴⁵⁶⁷⁸⁹√πθαβγΔλμσ_|!]+", s))


def formula(text: str) -> str:
    """The formula itself, without $$ or \\[ \\] around it."""
    inner = _unwrap(text)
    return inner if inner is not None else text.strip()


SAY = {'=': 'equals', '≈': 'is about', '≤': 'is at most', '≥': 'is at least', '<': 'is less than',
       '>': 'is greater than', '+': 'plus', '−': 'minus', '-': 'minus', '*': 'times', '×': 'times', '·': 'times',
       '/': 'divided by', '÷': 'divided by', '√': 'the square root of', 'π': 'pi', 'θ': 'theta', 'α': 'alpha',
       'β': 'beta', 'γ': 'gamma', 'Δ': 'delta', 'λ': 'lambda', 'μ': 'mu', 'σ': 'sigma', '!': 'factorial'}
SUPER = {'²': '2', '³': '3', '¹': '1', '⁰': '0', '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9'}
MATH_TOKEN = re.compile(r'\\[A-Za-z]+|\d+(?:\.\d+)?|[A-Za-z]+|[²³¹⁰⁴⁵⁶⁷⁸⁹]+|\S')


def _group(tokens, i):
    """The tokens of one exponent or subscript starting at i: {...}, (...) or one token; returns (tokens, next i)."""
    if i >= len(tokens):
        return [], i
    if tokens[i] in '{(':
        close, depth, j = '}' if tokens[i] == '{' else ')', 0, i
        while j < len(tokens):
            depth += tokens[j] in '{(' and 1 or 0
            depth -= tokens[j] in '})' and 1 or 0
            if depth == 0:
                break
            j += 1
        return tokens[i + 1:j], j + 1
    return [tokens[i]], i + 1


def _words(tokens: list[str]) -> list[str]:
    out, i, prev = [], 0, None
    while i < len(tokens):
        tok = tokens[i]
        if tok == '^':
            exponent, i = _group(tokens, i + 1)
            said = ' '.join(_words(exponent))
            if said in ('2', '3'):
                out.append({'2': 'squared', '3': 'cubed'}[said])
            else:
                if out:
                    out[-1] += ','
                out.append('to the power of ' + said)
            prev = ')'
            continue
        if tok == '_':
            sub, i = _group(tokens, i + 1)
            out.append('sub ' + ' '.join(_words(sub)))
            prev = 'x'
            continue
        if tok.startswith('\\'):
            name = tok[1:]
            tok = {'cdot': '·', 'times': '×', 'div': '÷', 'approx': '≈', 'le': '≤', 'leq': '≤', 'ge': '≥',
                   'geq': '≥', 'pi': 'π', 'theta': 'θ', 'alpha': 'α', 'beta': 'β', 'Delta': 'Δ', 'sqrt': '√',
                   'frac': '/'}.get(name, name)
            if tok == '/':                           # \frac{a}{b}
                num, i = _group(tokens, i + 1)
                den, i = _group(tokens, i)
                out += _words(num) + ['over'] + _words(den)
                prev = ')'
                continue
        if tok in '([{':
            if prev in ('x', '1', ')'):
                out.append('times')
            prev = '('
            i += 1
            continue
        if tok in ')]}':
            prev = ')'
            i += 1
            continue
        if tok == '-' and prev in (None, '=', 'op', '('):
            out.append('minus')
            prev = 'op'
            i += 1
            continue
        if tok in SAY:
            out.append(SAY[tok])
            prev = '=' if tok in '=≈≤≥<>' else 'op' if tok != '!' else ')'
            i += 1
            continue
        if re.fullmatch(r'\d+(?:\.\d+)?', tok):
            out.append(tok)
            prev = '1'
        elif re.fullmatch(r'[A-Za-z]+', tok):
            if tok.lower() in FUNCS:
                out.append({'sqrt': 'the square root of', 'ln': 'the natural log of', 'log': 'log'}.get(tok.lower(),
                                                                                                         tok.lower()))
                prev = 'op'
            else:
                out += list(tok)                     # mc -> m c: each letter is a quantity
                prev = 'x'
        i += 1
    return out


def say_math(text: str) -> str:
    """A formula in words, as a teacher says it: "A = P(1 + r)^n" -> "A equals P times one plus r, to the power of
    n" (digits stay digits: the number reader says them)."""
    tokens = []
    for tok in MATH_TOKEN.findall(formula(text)):
        tokens += ['^', ''.join(SUPER[c] for c in tok)] if tok[0] in SUPER else [tok]
    words = _words(tokens)
    said = re.sub(r'\s+,', ',', ' '.join(words)).strip()
    return said[:1].upper() + said[1:] + '.' if said else said


# ------------------------------------------------------------------ steps, warnings, keys
def step(paragraph: str):
    """(number, text) of a numbered list item ("2. Choose Security" -> (2, "Choose Security")), else None."""
    m = STEP.match(paragraph)
    return (int(m.group(1)), paragraph[m.end():]) if m else None


def warning(text: str) -> bool:
    """Whether a paragraph is a warning callout."""
    return bool(WARNING.match(text))


def combos(text: str) -> list[tuple[int, int, list[str]]]:
    """(start, end, keys) of every key combo in ``text``: "Ctrl + Shift + N" -> ['Ctrl', 'Shift', 'N']."""
    return [(m.start(), m.end(), [k.strip() for k in m.group().split('+')]) for m in COMBO.finditer(text)]


def hidden_spans(text: str) -> list[tuple[int, int]]:
    """The parts of a beat's text that are pictures only: fenced code blocks, or the whole text when it is a
    display formula."""
    if math_line(text):
        return [(0, len(text))]
    return fence_spans(text)


def board(beat: dict, lang: str) -> dict | None:
    """The markup a beat shows as its own board ({'kind': 'code'|'math'|'warning', ...}), else None."""
    mark = beat.get('markup') or {}
    if mark.get('kind') not in ('code', 'math', 'warning'):
        return None
    display = beat.get('display')
    text = display.get(lang, next(iter(display.values()), '')) if isinstance(display, dict) else str(display or '')
    if mark['kind'] == 'code':
        found = code_block(text)
        return {'kind': 'code', 'lang': found[0], 'code': found[1]} if found else None
    if mark['kind'] == 'math':
        return {'kind': 'math', 'formula': formula(text)}
    return {'kind': 'warning', 'text': text}
