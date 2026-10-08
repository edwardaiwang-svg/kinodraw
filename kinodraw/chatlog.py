"""A pasted chat log: message lines with a time and a sender, system notices, voice notes, a header naming the chat.

English word lists, general shapes (never one script's lines). Each reading works on the written text and on its
spoken form, where numbers are already words ("8:05 AM" -> "eight oh five AM"):

- ``prefix_end(text, pos)``: where a sender label starts after a time (or date and time) written before it:
  "[8:06] Maya: ...", "8:05 AM — Coach Rivera: ...", "10/8/26, 8:05 PM - Theo: ..." (a sender label after the time
  is speech.LABEL, which also reads "Theo (8:09 PM): ...").
- ``system(line)``: a notice the app writes, never a message: someone joined, was added or left, a deleted message,
  a missed call, a changed group name or photo, an encryption notice; with or without a time in front.
- ``voice_note(line)``: a voice message ("[Voice note 0:07]", "🎤 Voice message (0:12)", "<audio omitted>") and its
  length when written.
- ``header(line)``: a short line naming the chat ("Group chat: Tigers U12 Parents"), its name.
- ``is_log(lines, labelled, timed)``: whether a script is a chat log (most of its lines are messages and notices).
"""
from __future__ import annotations

import re

_NUM = (r'(?:zero|oh|o|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|'
        r'sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|hundred|o[\'’]clock)')
_MONTH = (r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?')
_DAY = r'(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?|yesterday|today'
_ORD = r'(?:\w+(?:st|nd|rd|th))'
# One piece of a written or spoken time or date.
_PIECE = (r'(?:\d{1,4}(?:[:/.\-]\d{1,4}){0,3}|' + _NUM + r'(?:[\s-]+' + _NUM + r')*(?::' + _NUM + r'(?:[\s-]+'
          + _NUM + r')*)?|[AaPp]\.?\s?[Mm]\.?|' + _MONTH + r'|' + _DAY + r'|' + _ORD + r'|at)')
STAMP = re.compile(r'(?i:' + _PIECE + r'(?:[,\s]+' + _PIECE + r'){0,7})')
TIMEISH = re.compile(r'\d|\b(?:[ap]\.?\s?m\.?|' + _NUM + r')\b', re.I)
# "[8:06] ", "[10/8/26, 8:05:12 PM] "; "8:05 AM — ", "10/8/26, 8:05 PM - ".
BRACKET = re.compile(r'[ \t]*\[(?P<t>[^\[\]\n]{1,48})\][ \t]*')
DASHED = re.compile(r'[ \t]*(?P<t>' + STAMP.pattern + r')[ \t]*[,]?[ \t]*(?:[—–-]{1,2}|[|•·])[ \t]*')

SYSTEM = re.compile(
    r'^\W*(?:(?:[\w’\'.-]+\s+){0,3}(?:joined(?:\s+(?:the\s+(?:group|chat|conversation)|using\s+[\w\s’\']*link))?|'
    r'left(?:\s+the\s+(?:group|chat|conversation))?|was\s+(?:added|removed)|has\s+(?:joined|left)|'
    r'(?:added|removed)\s+(?:[\w’\'.-]+\s*){1,4}|changed\s+(?:the\s+)?(?:group\s+|chat\s+)?(?:name|subject|'
    r'icon|photo|description)[^\n]*|created\s+(?:the\s+)?(?:group|chat)[^\n]*|named\s+the\s+(?:group|'
    r'conversation|chat)[^\n]*|pinned\s+a\s+message|unsent\s+a\s+message|reacted\s+[^\n]{1,40})|'
    r'(?:this\s+message\s+was\s+deleted|you\s+deleted\s+this\s+message|message\s+deleted|'
    r'(?:missed|declined)\s+(?:voice\s+|video\s+)?call[^\n]*|(?:voice|video)\s+call\s+(?:ended|missed)[^\n]*|'
    r'messages?\s+(?:and\s+calls\s+)?(?:are|is)\s+end-to-end\s+encrypted[^\n]*|'
    r'<?(?:media|image|video|sticker|gif|document)\s+omitted>?|today|yesterday))\W*$', re.I)
VOICE = re.compile(r'^\W*(?:🎤|🎙️?)?\s*\[?\s*(?:<\s*)?(?:voice\s+(?:note|message|memo|clip)|audio(?:\s+(?:message|'
                   r'note|omitted))?|(?:ptt|opus)(?:-\S+)?)(?:\s*>)?\s*[:(-]?\s*(?P<len>[^)\]\n]{0,24}?)\s*[)\]]?\W*$'
                   r'|^\W*(?:🎤|🎙️?)\s*(?P<len2>[\d:]{3,6}|[\w\s:-]{0,24})\W*$', re.I)
CHAT_WORD = re.compile(r'\b(?:group\s+chat|chat|group|thread|text(?:s|ing)?|messages?|whatsapp|imessage|signal|'
                       r'telegram|discord|slack|dms?|team|family|fam|crew|squad|parents|club|gc)\b', re.I)
TEXTING = re.compile(r'\b(?:lol|lmao|lmfao|rofl|brb|omg|omw|idk|tbh|ttyl|ikr|smh|imo|btw|np|thx|ty|pls|plz|ur|u|k|kk|'
                     r'ya|yep|nope|haha\w*|hehe\w*|gonna|wanna|gotta)\b|[?!]{2,}', re.I)
EMOJI = re.compile('[\U0001F000-\U0001FAFF☀-➿⬀-⯿]')


def stamp_end(text: str, pos: int) -> tuple[int, str] | None:
    """(where the label starts, the time as written) when a time or a date and time is written before a sender label
    at ``pos``: "[8:06] Maya:", "8:05 AM — Coach Rivera:"; None otherwise."""
    for pattern in (BRACKET, DASHED):
        m = pattern.match(text, pos)
        if m and TIMEISH.search(m.group('t')) and len(m.group('t').split()) <= 9:
            if STAMP.fullmatch(m.group('t').strip(' ,')):
                return m.end(), m.group('t').strip(' ,')
    return None


def _strip_stamp(line: str) -> str:
    found = stamp_end(line, 0)
    return line[found[0]:] if found else line


def system(line: str) -> bool:
    """A notice the chat app writes ("Maya joined", "This message was deleted", "Missed voice call")."""
    body = _strip_stamp(line.strip()).strip()
    return bool(body) and len(body) <= 90 and bool(SYSTEM.match(body)) and ':' not in body.rstrip(':')


def voice_note(line: str):
    """A voice message line: its written length ("0:07") or '' when none is written; None for any other line."""
    body = _strip_stamp(line.strip()).strip()
    m = VOICE.match(body)
    if not m:
        return None
    length = (m.group('len') or m.group('len2') or '').strip(' ()[]:-')
    return length if re.fullmatch(r'\d{1,2}:\d{2}|' + _NUM + r'(?:[\s-]+' + _NUM + r')*', length, re.I) else ''


def header(line: str) -> str | None:
    """The chat's name a header line gives ("Group chat: Tigers U12 Parents" -> "Tigers U12 Parents"), else None.
    A header is short, ends with no sentence mark and names a chat or a group, or is only a name with an emoji."""
    text = re.sub(r"\s*[(\[—–-]\s*(?:screenshot\s+)?(?:from\s+|on\s+)?[A-Z][\w]*['’]s\s+(?:phone|cell|mobile|screen)"
                  r"\s*[)\]]?\s*$", '', line.strip())
    if not text or len(text.split()) > 9 or re.search(r'[.?!]$', text) or system(text) or voice_note(text) is not None:
        return None
    m = re.match(r'^(?:(?:the\s+)?(?:group\s+chat|chat|group|thread|conversation)\s*[:—–-]\s*)(?P<n>.+)$', text, re.I)
    if m:
        return m.group('n').strip(' "“”')
    if re.search(r'^[^:]+:\s', text):
        return None                                   # "Maya: ok" is a message
    if CHAT_WORD.search(text) or EMOJI.search(text):
        return re.sub(r'\s*\((?:group\s+chat|chat|group)\)\s*$', '', text, flags=re.I).strip(' "“”')
    return None


def is_log(lines: list[str], messages: int, timed: int, senders: int) -> bool:
    """A script that is a chat log: at least three message lines from at least two senders, messages and notices
    being most of its lines, and either a time on the messages, a notice, a header, or the way people text (emoji,
    lol, brb, "??"). ``messages``: its lines with a sender label; ``timed``: those with a time."""
    lines = [l.strip() for l in lines if l.strip()]
    if messages < 3 or senders < 2 or not lines:
        return False
    notices = sum(1 for l in lines if system(l) or voice_note(l) is not None)
    heads = sum(1 for l in lines[:2] if header(l))
    if (messages + notices + heads) * 2 < len(lines):
        return False
    return timed >= 2 or notices > 0 or heads > 0 or sum(1 for l in lines if TEXTING.search(l) or EMOJI.search(l)) >= 2
