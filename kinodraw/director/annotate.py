"""Rules annotator and energy planner: what each sentence does, which scene shows it, and how much it moves.

A storyboard can carry three direction dials (engine/storyboard.py fills in the defaults): ``look`` (whiteboard ·
collage · bold), ``story`` (explain · promo · story · showcase) and ``motion`` (lively · calm · showreel), and a
``brand`` ({name, url, cta}). The collage and bold renderers turn every sentence into a scene from a fixed template
library (SCENES) and animate it at an energy of 0-3 (ENERGY_TREATMENT); the whiteboard renderer ignores all of it.

annotate() writes ``beat['direction']`` for every title, opener, narration, take and closing beat: one entry per
sentence with its role, energy, scene and emphasis (a key phrase of at most three words, cut from the sentence),
and the options an LLM may later pick from by index. The rules pick always comes first, so the plan is complete
without one; an entry whose source is "user" is never changed. plan() fits the energies to the motion dial.

Roles, in order of precedence (English; in Chinese: questions, numbers, lists, quotes and a few cue words):
- quote: words in quotation marks, or "X said, Y";
- mechanic: condition pairs ("Not enough interest? Then it's called off.", "Enough people? Green light."), with
  the threshold set just before them ("Set a minimum.");
- brand: the brand's reveal ("Meet X", "Introducing X", "With X.", or X alone); later mentions are taglines. The
  brand is board['brand']['name'], else a domain (name.tld), else a capitalized name said at least twice that the
  title or a reveal backs up (a history of the "Bible" has no brand);
- turn: "There's a much easier way"; reveal: "Turns out", "The truth is", "In fact";
- feature: "No app." / "No more X."; channels: "In the group chat, on Signal, or by email.";
- social: people joining ("your friends sign up with a single tap");
- use_cases: a promo's or showcase's list of short things said on its own; list: three or more things in a row;
- question: ends with a question mark;
- step: an order in the middle of the video ("Share one link.") or "in 20 seconds", numbered (``n``);
- number: a salient number (not a year or a date; 20 or more, or with a unit, a scale or a percent sign);
- problem: trouble words, or what is said before an early turn or brand.
Then by place: the first question of the opening is the hook (the title counts; with none, the first sentence);
the last call to action near the end (the brand, a domain, "free", "Try it") is the cta, and what follows it are
taglines; with no cta the last sentence is the end_line; short lines, recaps and brand mentions in the last
quarter are taglines. Titles, openers and takeaways are taglines (or questions); the closing line is none.
"""
from __future__ import annotations

import re

from .. import numbers, script, styles
from ..engine.storyboard import DIALS

ROLES = {                                             # role -> baseline energy (plan() fits it to the motion dial)
    'hook': 2, 'question': 1, 'problem': 1, 'turn': 2, 'brand': 3, 'step': 1, 'feature': 2, 'channels': 1,
    'social': 1, 'mechanic': 2, 'use_cases': 2, 'list': 1, 'number': 2, 'quote': 1, 'reveal': 2, 'tagline': 1,
    'cta': 3, 'end_line': 2, 'none': 0}
ENERGY_TREATMENT = {                                  # what a renderer does with each energy
    0: 'still: the scene is simply there (a fade at most); nothing moves while the sentence is said',
    1: 'calm: one soft entrance (slide or draw-on) and a gentle mark on the emphasis',
    2: 'lively: a quick entrance with overshoot; the emphasis pops (scale or colour); a small camera push',
    3: "showpiece: the scene's full move (burst, morph, assemble, camera sweep); a few a video, 12 s apart"}
_PROMO = ['chat_pileup', 'chaos', 'brand_reveal', 'step_card', 'share_link', 'rsvp', 'feature_chips', 'threshold',
          'use_case_grid', 'brand_endcard', 'script_page', 'app_paste', 'app_press', 'hand_draws', 'sticker_row']
_STORY = ['title_question', 'crowd', 'stack', 'sky_speech', 'room_reaction', 'journey', 'document_reveal', 'collect',
          'moodboard', 'box_reveal', 'tools_idea', 'assemble', 'end_line', 'sticker_row']
_BOLD = ['slam_line', 'bracket_focus', 'count_up', 'marquee_rings', 'morph', 'particle_assemble', 'iris_end']
SCENES = {**{look: {story: ['board'] for story in DIALS['story']}            # the whiteboard renderer (and every
             for look in DIALS['look'] if styles.renderer(look) == 'whiteboard'},   # skin over it): one scene
          'collage': {'explain': list(_STORY), 'promo': list(_PROMO), 'story': list(_STORY), 'showcase': list(_PROMO)},
          'bold': {story: list(_BOLD) for story in DIALS['story']}}

# ------------------------------------------------------------------ scenes
PICKS = {   # template family -> role -> the scenes that suit it, best first (the look's default is always offered)
    'board': {},
    'promo': {'hook': ['chaos', 'chat_pileup'], 'question': ['chaos', 'chat_pileup'], 'problem': ['chat_pileup', 'chaos'],
              'turn': ['brand_reveal'], 'brand': ['brand_reveal', 'brand_endcard'], 'step': ['step_card', 'share_link'],
              'feature': ['feature_chips'], 'channels': ['share_link', 'step_card'], 'social': ['rsvp', 'share_link'],
              'mechanic': ['threshold', 'rsvp'], 'use_cases': ['use_case_grid', 'feature_chips'],
              'list': ['use_case_grid', 'feature_chips'], 'number': ['step_card', 'chaos'], 'quote': ['chat_pileup'],
              'reveal': ['brand_reveal', 'feature_chips'], 'tagline': ['sticker_row', 'brand_endcard'],
              'cta': ['brand_endcard', 'brand_reveal'], 'end_line': ['brand_endcard']},
    'story': {'hook': ['title_question', 'crowd'], 'question': ['title_question', 'room_reaction'],
              'problem': ['room_reaction', 'crowd'], 'turn': ['box_reveal', 'journey'],
              'brand': ['box_reveal', 'document_reveal'], 'step': ['assemble', 'tools_idea'],
              'feature': ['moodboard', 'box_reveal'], 'channels': ['journey', 'collect'],
              'social': ['crowd', 'room_reaction'], 'mechanic': ['tools_idea', 'assemble'],
              'use_cases': ['moodboard', 'collect'], 'list': ['moodboard', 'collect'], 'number': ['stack', 'document_reveal'],
              'quote': ['sky_speech', 'room_reaction'], 'reveal': ['box_reveal', 'document_reveal'],
              'cta': ['end_line', 'assemble'], 'end_line': ['end_line', 'assemble']},     # (a tagline: its words)
    'bold': {'hook': ['slam_line', 'bracket_focus'], 'question': ['bracket_focus', 'slam_line'],
             'problem': ['bracket_focus', 'slam_line'], 'turn': ['morph', 'slam_line'],
             'brand': ['particle_assemble', 'marquee_rings'], 'step': ['count_up', 'bracket_focus', 'slam_line'],
             'feature': ['slam_line', 'bracket_focus'], 'channels': ['marquee_rings', 'bracket_focus'],
             'social': ['bracket_focus', 'marquee_rings'], 'mechanic': ['morph', 'bracket_focus'],
             'use_cases': ['marquee_rings', 'slam_line'], 'list': ['marquee_rings', 'bracket_focus'],
             'number': ['count_up', 'slam_line'], 'quote': ['bracket_focus', 'slam_line'], 'reveal': ['morph', 'slam_line'],
             'tagline': ['slam_line', 'marquee_rings'], 'cta': ['iris_end', 'particle_assemble'],
             'end_line': ['iris_end', 'slam_line']}}
LIBRARY = {'board': ['board'], 'promo': _PROMO, 'story': _STORY, 'bold': _BOLD}
DEFAULT_SCENE = {'board': 'board', 'promo': 'sticker_row', 'story': 'sticker_row', 'bold': 'slam_line'}
SPARE = {'board': None, 'promo': 'feature_chips', 'story': 'collect', 'bold': 'bracket_focus'}   # a plain line's 2nd
KIND_SCENES = {'closing': {'promo': 'brand_endcard', 'story': 'end_line', 'bold': 'iris_end'},
               'title': {'story': 'title_question', 'bold': 'slam_line'},
               'endcard': {'promo': 'brand_endcard'}}      # (a promo's sign-off run, from the brand to the cta)
CUE_FIRST = {'none', 'problem', 'step', 'number', 'quote', 'social', 'tagline'}   # roles whose words choose
LEADS = {'script_page', 'app_paste', 'app_press', 'hand_draws'}   # scenes that show exactly what the words say lead


def _cues(*pairs):
    return [(re.compile(pattern, re.I), scene) for pattern, scene in pairs]


CUES = {'board': [], 'bold': [],                     # (bold: a salient number counts up)
        'promo': _cues((r'^(?:(?:first|just|simply|now|then),?\s+)?(?:paste|type|drop|upload|import)\b', 'app_paste'),
                       (r'^(?:(?:then|now|just|and|next),?\s+)?(?:press|click|tap|hit)\s+(?:on\s+)?(?:the\s+)?[“"]?'
                        r'(?-i:[A-Z])', 'app_press'),
                       (r'\b(?:hand|pen|pencil|marker)\s+(?:draws?|sketch(?:es)?|doodles?|writes?)\b', 'hand_draws'),
                       (r"\b(?:you|i|we|they)\s+(?:wrote|write|have\s+written|typed)\b|"
                        r'\b(?:your|my|a)\s+(?:script|essay|notes|draft|lesson plan)\b', 'script_page'),
                       (r'\b(?:messages?|texts?|chats?|pings?|notifications?|another one)\b', 'chat_pileup'),
                       (r"\b(?:chaos|mess|who'?s|nobody|no one|confus\w*)\b", 'chaos'),
                       (r'\b(?:links?|share|send|invite)\b', 'share_link'),
                       (r'\b(?:sign(?:s|ed)? up|rsvps?|taps?|join\w*|coming|say yes)\b', 'rsvp'),
                       (r'\b(?:minimum|maximum|threshold|enough|at least|called off|green light)\b', 'threshold'),
                       (r'\b(?:create|make|set up|start|build|plan)\b', 'step_card'),
                       (r'^(?:no|zero|without)\b|\bfree\b', 'feature_chips')),
        'story': _cues((r'\b(?:people|everyone|everybody|crowds?|humans?|friends|we all)\b', 'crowd'),
                       (r'\b(?:books?|wrote|writ(?:e|es|ing|ten)|philosoph\w*|librar\w*|pages?)\b', 'stack'),
                       (r'\b(?:stars?|sky|moon|heavens?|universe|planets?)\b', 'sky_speech'),
                       (r'\b(?:cats?|dogs?|laugh\w*|react\w*|shrug\w*)\b', 'room_reaction'),
                       (r'\b(?:went|going|travel\w*|journey\w*|mountains?|seas?|oceans?|roads?|paths?|looking|search\w*)\b',
                        'journey'),
                       (r'\b(?:fine print|documents?|papers?|letters?|contracts?|reports?|files?)\b', 'document_reveal'),
                       (r'\b(?:picked up|collect\w*|gather\w*|pieces|found)\b', 'collect'),
                       (r'\b(?:turns out|boxe?s?|gifts?|unwrap\w*|hidden|secrets?)\b', 'box_reveal'),
                       (r'\b(?:scissors|glue|tools?|ideas?|pencils?|tape)\b', 'tools_idea'),
                       (r'\b(?:stick\w*|together|build\w*|assembl\w*|cut out)\b', 'assemble'))}

ES_CUES = {'board': [], 'bold': [],
           'promo': _cues((r'^(?:(?:primero|solo|simplemente|ahora|luego),?\s+)?'
                            r'(?:pega|peguen|escribe|escriban|sube|suban|carga|carguen|importa|importen)\b',
                            'app_paste'),
                           (r'^(?:(?:luego|ahora|solo|y|después),?\s+)?'
                            r'(?:pulsa|pulsen|presiona|presionen|toca|toquen|haz\s+clic|hagan\s+clic)\s+'
                            r'(?:(?:en|el|la)\s+)*[«“"]?(?-i:[A-ZÁÉÍÓÚÜÑ])', 'app_press'),
                           (r'\b(?:mano|bolígrafo|lápiz|marcador)\s+(?:dibuja|esboza|escribe)\b', 'hand_draws'),
                           (r'\b(?:tu|mi|un|el)\s+(?:guion|guión|ensayo|borrador|plan\s+de\s+clase)\b|'
                            r'\b(?:tus|mis)\s+notas\b', 'script_page'),
                           (r'\b(?:mensajes?|chats?|notificaciones?|otro\s+más)\b', 'chat_pileup'),
                           (r'\b(?:caos|desorden|nadie|confusi\w*)\b', 'chaos'),
                           (r'\b(?:enlaces?|comparte|compartan|compartir|envía|envíen|enviar|invita|inviten|invitar)\b',
                            'share_link'),
                           (r'\b(?:inscrib\w*|registr\w*|une|unen|unirse|confirma\w*|dicen\s+sí)\b', 'rsvp'),
                           (r'\b(?:mínimo|máximo|umbral|suficientes?|al\s+menos|se\s+cancela|luz\s+verde)\b',
                            'threshold'),
                           (r'\b(?:crea|creen|crear|haz|hagan|hacer|configura|configuren|empieza|empiecen|'
                            r'construye|construyan|planifica|planifiquen)\b', 'step_card'),
                           (r'^(?:sin|cero|no\s+más)\b|\bgratis\b', 'feature_chips')),
           'story': _cues((r'\b(?:personas?|gente|todos|multitud\w*|humanos?|amig[oa]s?)\b', 'crowd'),
                           (r'\b(?:libros?|escrib\w*|filóso\w*|bibliotec\w*|páginas?)\b', 'stack'),
                           (r'\b(?:estrellas?|cielo|luna|universo|planetas?)\b', 'sky_speech'),
                           (r'\b(?:gat[oa]s?|perr[oa]s?|risa|ríe|reacci\w*)\b', 'room_reaction'),
                           (r'\b(?:viaj\w*|camino\w*|montañas?|mares?|océanos?|carreteras?|busc\w*)\b', 'journey'),
                           (r'\b(?:letra\s+pequeña|documentos?|papeles?|cartas?|contratos?|informes?|archivos?)\b',
                            'document_reveal'),
                           (r'\b(?:recog\w*|recolect\w*|reun\w*|piezas?|encontr\w*)\b', 'collect'),
                           (r'\b(?:resulta\s+que|cajas?|regalos?|ocult[oa]s?|secretos?)\b', 'box_reveal'),
                           (r'\b(?:tijeras|pegamento|herramientas?|ideas?|lápices|cinta)\b', 'tools_idea'),
                           (r'\b(?:pega\w*|juntos|constru\w*|ensamb\w*|recorta\w*)\b', 'assemble'))}

# ------------------------------------------------------------------- roles
DIRECTED = ('title', 'opener', 'narration', 'take', 'closing')
QUESTION = {'en': re.compile(r'\?[”’"\')\]]*$'), 'zh': re.compile(r'[?？][”’"」』）)]*$')}
QUOTED = {'en': re.compile(r'[“"]([^”"]{1,200})[”"]'), 'zh': re.compile(r'[“「『]([^”」』]{1,80})[”」』]')}
QUESTION['es'] = re.compile(r'\?[»”’"\')\]]*$')
QUOTED['es'] = re.compile(r'[«“"]([^»”"]{1,200})[»”"]')
SAID = {'en': re.compile(r"(?P<who>\b(?:(?:the|a|an|my|our|his|her|their)\s+)?[A-Za-z][\w'’-]*)\s+"
                         r"(?:said|says|asked|asks|replied|replies|answered|whispered|wrote|writes|shouted)\s*[,:]\s*"
                         r"(?P<q>[^,;:]+?)[.!?…]*$", re.I),
        'zh': re.compile(r'(?P<who>[一-鿿]{1,6})(?:说|写道|问|回答|喊)[：:，,]\s*(?P<q>[^，。！？]+)[。！？]*$')}
COND = {'en': re.compile(r'^(?:not\s+enough|enough|too\s+(?:few|many|much|little)|(?:fewer|more|less)\s+than)\b[^?]{0,40}\?',
                         re.I),
        'zh': re.compile(r'^(?:不够|人数不够|够了|太少|太多|少于|多于|超过|没人)[^？?]{0,12}[？?]')}
THRESHOLD = {'en': re.compile(r'\b(?:minimum|maximum|threshold|quorum|at\s+least|at\s+most|limit)\b', re.I),
             'zh': re.compile(r'最少|最低|至少|门槛|上限|下限')}
REVEAL = {'en': re.compile(r'^(?:(?:and|but|so)\s+)?(?:it\s+)?turns\s+out\b|^the\s+(?:truth|secret|answer|twist)\s+is\b|'
                           r'^in\s+fact\b', re.I),
          'zh': re.compile(r'^(?:原来|其实|事实上|真相是|结果发现)')}
PAIN = {'en': re.compile(r'\b(?:risks?|dangers?|dangerous|problems?|worr(?:y|ies|ied)|fears?|threats?|crisis|mistakes?|'
                         r'warnings?|hassle|annoying|chaos|chaotic|mess|messy|struggl\w*|frustrat\w*|tired\s+of|sick\s+of|'
                         r'wast(?:e|es|ed|ing)|stuck|painful)\b', re.I),
        'zh': re.compile(r'风险|危险|问题|担心|害怕|危机|错误|警告|麻烦|浪费|痛苦|困扰')}
SAID['es'] = re.compile(r"(?P<who>\b(?:(?:el|la|un|una|mi|nuestro|nuestra|su)\s+)?[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\w'’-]*)\s+"
                        r'(?:dijo|dice|preguntó|pregunta|respondió|responde|contestó|susurró|escribió|escribe|gritó)'
                        r'\s*[,:]\s*(?P<q>[^,;:]+?)[.!?…]*$', re.I)
COND['es'] = re.compile(r'^¿?(?:no\s+hay\s+suficientes?|no\s+hay\s+bastantes?|suficientes?|hay\s+suficientes?|'
                        r'faltan|demasiad[oa]s?|muy\s+poc[oa]s?|(?:menos|más)\s+de)\b[^?]{0,40}\?', re.I)
THRESHOLD['es'] = re.compile(r'\b(?:mínimo|máximo|umbral|cuórum|al\s+menos|como\s+mínimo|como\s+máximo|límite)\b', re.I)
REVEAL['es'] = re.compile(r'^(?:(?:y|pero|así\s+que)\s+)?(?:resulta\s+que|la\s+(?:verdad|respuesta|clave)\s+es|'
                          r'de\s+hecho|en\s+realidad)\b', re.I)
PAIN['es'] = re.compile(r'\b(?:riesgos?|peligros?|peligros[oa]s?|problemas?|preocup\w*|miedo|amenazas?|crisis|'
                        r'errores?|advertencias?|molest\w*|caos|desorden|frustra\w*|cansad[oa]s?\s+de|'
                        r'desperdici\w*|atascad[oa]s?|dolor\w*)\b', re.I)
ES_TURN = re.compile(r'^(?:(?:pero|ahora|por\s+suerte),?\s+)?hay\s+una\s+(?:forma|manera)\s+'
                     r'(?:(?:mucho|más)\s+)*(?:fácil|mejor|simple|sencilla|rápida)\b|^(?:hasta\s+ahora|ya\s+no)\b', re.I)
ES_FEATURE = re.compile(r'^(?:sin|cero|no\s+más)\s+\S', re.I)
ES_PEOPLE = re.compile(r'\b(?:amig[oa]s?|personas?|gente|todos|invitad[oa]s?|equipo|compañer[oa]s?|familia|'
                          r'miembros?|usuari[oa]s?|clientes?|vecin[oa]s?|jugador[ae]s?)\b', re.I)
ES_JOIN = re.compile(r'\b(?:se\s+)?(?:inscrib\w*|registr\w*|unen?|unirse|apunt\w*|confirma\w*|'
                        r'acepta\w*|responde\w*|vota\w*|dicen?\s+sí)\b', re.I)
ES_CHANNEL_PREPS = {'en', 'por', 'vía', 'mediante', 'desde'}
ES_IN_TIME = re.compile(r'\ben\s+(?:solo\s+|apenas\s+|menos\s+de\s+)?\d+\s+'
                           r'(?:segundos?|minutos?|horas?|días?|clics?|toques?|pasos?)\b', re.I)
ES_IMPERATIVE = set('''añade agrega pide trae construye compra llama comprueba elige pulsa conecta copia crea
descarga arrastra suelta introduce rellena busca sigue consigue da ve instala invita únete mantén deja haz abre
pega paga escoge presiona pon guarda escanea programa selecciona envía comparte firma empieza toma toca prueba
pruébalo escribe sube usa utiliza visita vota espera mira recorta añadan agreguen pidan traigan construyan compren
llamen comprueben elijan pulsen conecten copien creen descarguen arrastren suelten introduzcan rellenen busquen
sigan consigan den vayan instalen inviten únanse mantengan dejen hagan abran peguen paguen escojan presionen
pongan guarden escaneen programen seleccionen envíen compartan firmen empiecen tomen toquen prueben pruébenlo
escriban suban usen utilicen visiten voten esperen miren recorten'''.split())
ES_CTA = re.compile(r'\bgratis\b|^(?:(?:así\s+que|y|ahora|solo)\s+)?(?:prueba|prueben|pruébalo|pruébenlo|'
                       r'empieza|empiecen|comienza|comiencen|consigue|consigan|descarga|descarguen|instala|instalen|'
                       r'regístrate|regístrense|inscríbete|inscríbanse|únete|únanse|visita|visiten|suscríbete|'
                       r'suscríbanse|sigue|sigan|reserva|reserven|compra|compren|ve\s+a|vayan\s+a|descubre|'
                       r'descubran|aprende\s+más|aprendan\s+más|crea\s+tu\s+primer|creen\s+su\s+primer)\b', re.I)
ES_INTRO = re.compile(r'^(?i:conoce|presentamos|te\s+presentamos|presentando|saluda\s+a)\s+'
                         r'([A-ZÁÉÍÓÚÜÑ][\w-]*(?:\s+[A-ZÁÉÍÓÚÜÑ][\w-]*)?)')
ES_LIST_WORD = r"\b(?!(?:y|e|o|u|pero|en|de|a|para|con|desde|por|es|son|era|somos|yo|tú|él|ella)\b)[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\w'’-]*"
ES_LIST_ITEM = rf'(?:(?:un|una|el|la|los|las|unos|unas|su|sus|nuestro|nuestra|tu|tus|mi|mis)\s+)?{ES_LIST_WORD}(?:\s+{ES_LIST_WORD})?'
ES_LIST_RUN = re.compile(rf'{ES_LIST_ITEM}(?:,\s+{ES_LIST_ITEM}){{1,4}},?\s+(?:y|e|o|u)\s+{ES_LIST_ITEM}', re.I)
ES_MONTHS = re.compile(r'\b(?:ene(?:ro)?|feb(?:rero)?|mar(?:zo)?|abr(?:il)?|may(?:o)?|jun(?:io)?|jul(?:io)?|'
                          r'ago(?:sto)?|sep(?:tiembre)?|oct(?:ubre)?|nov(?:iembre)?|dic(?:iembre)?)\b', re.I)
ES_SCALE = re.compile(r'(?:\s+(?:cien|cientos?|mil|millones?|billones?))+', re.I)
ES_UNIT = re.compile(r'\s+(?:segundos?|minutos?|horas?|días?|semanas?|meses|años?|pasos?|clics?|toques?|'
                        r'euros?|dólares?|personas?|veces|kilómetros?|metros?|kilos?|por\s+ciento)\b', re.I)
TURN = re.compile(r"^(?:but\s+|now\s+|luckily,?\s+|thankfully,?\s+)?there(?:'s|’s|\s+is)\s+(?:a\s+)?"
                  r"(?:(?:much|far|way|so\s+much)\s+)?(?:easier|better|simpler|faster|smarter|quicker|new)\s+way\b|"
                  r"^(?:until\s+now|not\s+any\s*more)\b", re.I)
FEATURE = re.compile(r'^(?:no(?:\s+more)?|zero|without)\s+(?!one\b|matter\b|longer\b|doubt\b|wonder\b)\S', re.I)
PEOPLE = re.compile(r'\b(?:friends?|people|everyone|everybody|guests?|team(?:mates)?|colleagues?|family|crew|members?|'
                    r'users?|customers?|fans?|neighbou?rs?|classmates?|players?)\b', re.I)
JOIN = re.compile(r'\b(?:sign(?:s|ed)?\s+up|join(?:s|ed)?|tap(?:s|ped)?|rsvps?|say(?:s)?\s+yes|repl(?:y|ies|ied)|'
                  r'respond(?:s|ed)?|accept(?:s|ed)?|register(?:s|ed)?|show(?:s)?\s+up|vot(?:e|es|ed)|chip(?:s)?\s+in|'
                  r'opt(?:s)?\s+in)\b', re.I)
CHANNEL_PREPS = {'in', 'on', 'by', 'via', 'through', 'over', 'from', 'across'}
IN_TIME = re.compile(r'\bin\s+(?:just\s+|only\s+|under\s+)?\d+\s+(?:seconds?|minutes?|hours?|days?|clicks?|taps?|steps?)\b',
                     re.I)
IMPERATIVE = set('''add ask bring build buy call check choose click connect copy create download drag drop enter fill
find follow get give go grab install invite join keep let make open paste pay pick pour press put save scan schedule
select send set share sign snap start take tap try type upload use visit vote wait watch write'''.split())
CTA = re.compile(r'\bfree\b|^(?:(?:so|and|now|just)\s+)?(?:try|start|get|download|install|sign\s+up|join|visit|'
                 r'subscribe|follow|book|order|shop|head\s+(?:to|over)|go\s+to|find\s+out|learn\s+more|check\s+out|'
                 r'create\s+your\s+first)\b', re.I)
DOMAIN = re.compile(r'\b(?:https?://)?(?:www\.)?([A-Za-z0-9][A-Za-z0-9-]*)(?:\.[A-Za-z0-9-]+)*'
                    r'\.(?!(?:js|py|md|txt|pdf|html?|css|jpe?g|png|gif|svg|mp[34]|zip|exe)\b)[a-z]{2,}\b(?:/[\w./-]*)?')
INTRO = re.compile(r'^(?i:meet|introducing|say hello to|presenting)\s+([A-Z][\w-]*(?:\s+[A-Z][\w-]*)?)')
LIST_WORD = r"\b(?!(?:and|or|but|in|on|at|of|to|for|with|from|by|is|are|was|were|we|you|they|it|he|she|i)\b)[A-Za-z][\w'’-]*"
LIST_ITEM = rf'(?:(?:a|an|the|some|their|his|her|its|our|your|my)\s+)?{LIST_WORD}(?:\s+{LIST_WORD})?'
LIST_RUN = re.compile(rf'{LIST_ITEM}(?:,\s+{LIST_ITEM}){{1,4}},?\s+(?:and|or)\s+{LIST_ITEM}')
MONTHS = re.compile(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\b')
SCALE = re.compile(r'(?:\s+(?:hundred|thousand|million|billion|trillion))+', re.I)
OPENING, MIDDLE, TAIL = .25, (.1, .8), .75           # where the hook, steps and the closing run are looked for

# ---------------------------------------------------------------- emphasis
FUNCTION = set('''a an the and or but nor so yet if then than as of to in on at by for with from into onto about over
under up down out off through after before between during without within against among across around is are was
were be been being am do does did has have had will would can could shall should may might must it its it's this
that that's these those there there's here i i'm me my mine we we're our us you you're your he he's his him she
she's her they they're their them who who's whom whose which what what's when where why how not don't doesn't
didn't isn't aren't wasn't weren't won't can't just also very really too only even still again ever never always
often much many more most such some any all each every both either neither own well now oh yes no later ago today
tomorrow yesterday'''.split())
LEADING = set('and but so then or yet well now plus also just'.split())
DETS = set('a an the your my our their his her its this that these those one another every each some no'.split())
PARTICLES = set('off up out down away back over'.split())
INDEFINITE = set('everyone everybody everything anyone anybody anything someone somebody something nobody '
                 'nothing'.split())
NOT_ITEM = FUNCTION - DETS - {'no', 'not', 'more', 'most', 'all', 'both'}  # an item never starts with these
TOKEN = re.compile(r"(?:[A-Za-z0-9-]+\.)+[a-z]{2,}\b|[$€£]?\d(?:[\d,.]*\d)?(?:%|[a-z]+\b)?|[A-Za-z][\w'’-]*")
ZH_FUNCTION = set('的 了 是 在 和 与 或 也 都 就 还 又 很 会 能 要 把 被 让 给 对 从 到 这 那 这些 那些 它 他 她 我们 你们 '
                  '他们 我 你 吗 呢 吧 啊 着 过 一个 一些 所以 但是 而且 因为 如果 可以 其实 就是'.split())
ZH_UNIT = re.compile(r'(?:个小时|小时|分钟|个月|个|位|名|本|家|座|年|岁|天|秒|倍|次|人|万|亿|千|百|元)')
ES_FUNCTION = set('''el la los las un una unos unas y e o u pero ni así si entonces que como de del a al en por
para con sin desde hasta entre sobre bajo tras durante hacia es son era eran ser sido siendo soy somos eres está
están estaba estaban estar estoy estamos estás hay ha han haber he hemos has había tienen tiene tener puede
pueden podría debe deben será serán fue fueron sea sean lo le les se este esta estos estas ese esa esos esas
eso esto aquel aquella yo me mí mi mis nosotros nos nuestro nuestra nuestros nuestras tú te ti tu tus usted
ustedes él su sus ella ellos ellas quien quién quienes qué cuál cuáles cuándo dónde porqué porque cómo no
también muy más menos solo sólo incluso todavía aún ya otra otro otros otras todo toda todos todas cada ambos
algún alguna algunos algunas cualquier mucho mucha muchos muchas poco poca pocos pocas bien ahora sí nunca
siempre hoy mañana ayer después antes'''.split())
ES_LEADING = set('y e pero así entonces o u bueno ahora también solo sólo luego'.split())
ES_DETS = set('el la los las un una unos unas tu tus mi mis nuestro nuestra nuestros nuestras su sus este esta '
              'estos estas ese esa esos esas otro otra cada algún alguna algunos algunas ningún ninguna'.split())
ES_INDEFINITE = set('todos todo alguien algo cualquiera nadie nada'.split())
ES_NOT_ITEM = ES_FUNCTION - ES_DETS - {'no', 'más', 'menos', 'todo', 'todos', 'ambos'}
ES_TOKEN = re.compile(r"(?:[A-Za-z0-9-]+\.)+[a-z]{2,}\b|[$€£]?\d(?:[\d,.]*\d)?(?:%|[a-z]+\b)?|[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\w'’-]*")
EMPHASIS_WORDS, READABLE_WORDS = 3, 4                 # an emphasis option; the longest emphasis a big move allows

# ----------------------------------------------------------------- planner
MOTION = {'calm': (1, 0., 0), 'lively': (3, .20, 2), 'showreel': (3, .45, 5)}   # top energy, share at 2+, showpieces
REST, APART = 3.0, 12.0                               # seconds of rest after a hit; seconds between showpieces
CPS = {'en': 15.0, 'zh': 4.4}                          # characters a second without a timeline (zh: its reading rate)
CPS['es'] = 15.0
CASCADE = {'feature', 'mechanic', 'step', 'use_cases', 'list', 'channels'}   # runs that may stay up together
STRONG = {'brand', 'turn', 'reveal', 'feature', 'mechanic', 'channels', 'social', 'use_cases', 'number', 'quote', 'cta'}


def sentences_of(beat: dict, lang: str) -> list[tuple[int, int, int]]:
    """(i, start, end) of every sentence of the beat's display text, split as script.sentences splits it:
    ``display[start:end]`` is the sentence."""
    text = (beat.get('display') or {}).get(lang, '')
    out, cursor = [], 0
    for i, sentence in enumerate(script.sentences(text, lang)):
        start = text.find(sentence, cursor)
        out.append((i, start, start + len(sentence)))
        cursor = start + len(sentence)
    return out


# ------------------------------------------------------------ entry points
def annotate(board: dict) -> dict:
    """Give every sentence of every title, opener, narration, take and closing beat its direction (keeping every
    entry whose source is "user", matched by sentence index), then fit the energies to the motion dial (plan).
    The same board always gets the same plan."""
    lang = board['lang']
    look, story, motion = _dials(board)
    family = _family(look, story)
    rows = []
    for beat in board['beats']:
        if beat.get('kind') in DIRECTED:
            text = beat['display'][lang]
            for i, a, b in sentences_of(beat, lang):
                head = _label_end(text[a:b]) if i == 0 and beat['kind'] in ('title', 'opener', 'take') else 0
                rows.append({'beat': beat, 'i': i, 'span': [a, b], 'text': text[a:b], 'head': head, 'kind': beat['kind']})
    content = [r for r in rows if r['kind'] == 'narration']
    brand = _brand(board, [r['text'] for r in content], lang)
    _roles(rows, content, lang, story, brand)
    directions, kept, steps, prev = {}, 0, 0, None
    for r in rows:
        beat = r['beat']
        if beat['id'] not in directions:              # the user's entries by sentence (and any others), the new list
            by_i, loose = {}, []
            for e in beat.get('direction') or []:
                if isinstance(e, dict) and e.get('source') == 'user':
                    if isinstance(e.get('i'), int) and e['i'] not in by_i:
                        by_i[e['i']] = e
                    else:
                        loose.append(e)
            directions[beat['id']] = (by_i, [], loose)
        users, made, _ = directions[beat['id']]
        entry = users.pop(r['i'], None)
        if entry is None:
            phrases = _phrases(r['text'], r['role'], lang, brand, r['head'], names=r['kind'] != 'title')
            scenes = _scenes(r['role'], r['text'], r.get('lead', r['kind']), family, prev, lang)
            if r['role'] == 'none' and prev == 'feature_chips' and 'feature_chips' in scenes and \
                    len(_body(r['text']).split()) <= 8:       # "No account. It all runs on your computer." goes on
                scenes = ['feature_chips'] + [x for x in scenes if x != 'feature_chips']
            energy = min(ROLES[r['role']], MOTION[motion][0])
            if energy >= 2 and not _readable(phrases[0] if phrases else '', lang):
                energy = 1
            entry = {'i': r['i'], 'span': r['span'], 'role': r['role'], 'energy': energy, 'scene': scenes[0],
                     'emphasis': phrases[0] if phrases else '',
                     'options': {'scene': scenes, 'emphasis': phrases, 'energy': [max(0, energy - 1), energy]},
                     'source': 'rules'}
            if r['role'] == 'step':
                steps += 1
                entry['n'] = steps
        else:
            kept += 1
        made.append(entry)
        prev = entry.get('scene')
    for beat in board['beats']:
        if beat['id'] in directions:                  # a user's entry is kept even when it no longer fits
            left, made, loose = directions[beat['id']]
            beat['direction'] = made + [left[i] for i in sorted(left)] + loose
    roles: dict = {}
    for r in rows:
        roles[r['role']] = roles.get(r['role'], 0) + 1
    return {'sentences': len(rows), 'roles': roles, 'user': kept, 'brand': brand, 'plan': plan(board)}


def plan(board: dict, timeline: dict | None = None) -> dict:
    """Fit every energy to the motion dial. Entries a user set are never changed, only reported.

    calm: nothing above 1. lively: at most 20% of the runtime at energy 2 or more and at most 2 showpieces
    (energy 3); showreel: 45% and 5. Always: showpieces at least 12 s apart; after a sentence at 2 or more, the
    next 3 s stay at 1 or less (the rest of a list or cascade excepted); only a sentence whose emphasis has at
    most four words may reach 2. Energies start from each role's baseline, so plan() can run again once the
    real timing is known. When something must give, the lowest priority goes first: the anchors (the first hook,
    the brand reveal, the final cta or end line) outrank other strong roles, which outrank the rest; then the
    higher baseline wins; then, when time must be cut, the longer sentence goes (it frees the most and reads worst
    when it moves); otherwise the later one. Times come from the timeline (each beat's start plus the char_times
    of its spoken text), else 15 characters a second."""
    lang, motion = board['lang'], _dials(board)[2]
    top, share_cap, show_cap = MOTION[motion]
    notes: list = []
    rows = _timed(board, timeline, notes)
    anchors = _anchors(rows)
    for r in rows:
        entry = r['entry']
        energy = entry.get('energy') if isinstance(entry.get('energy'), int) else 0
        want = ROLES.get(r['role'], 0) if entry.get('source') == 'rules' else min(3, max(0, energy))
        readable = isinstance(entry.get('emphasis'), str) and _readable(entry['emphasis'], lang)
        if r['user']:
            r['e'] = want
            if want > top:
                notes.append(f"{r['id']}: user energy {want} breaks {motion} (at most {top})")
            elif want >= 2 and not readable:
                notes.append(f"{r['id']}: user energy {want} needs an emphasis of at most {READABLE_WORDS} words")
            continue
        r['e'] = min(want, top, 3 if readable else 1)

    def rank(r, longest=False):                       # lowest first out; trimming time, the longest goes first
        tier = 2 if r['n'] in anchors else 1 if r['role'] in STRONG else 0
        return (tier, ROLES.get(r['role'], 0)) + ((r['t0'] - r['t1'],) if longest else ()) + (-r['n'],)

    def demote(pool, to, why, longest=False):
        movable = [r for r in pool if not r['user']]
        if not movable:
            return False
        victim = min(movable, key=lambda r: rank(r, longest))
        notes.append(f"{victim['id']}: {victim['role']} {victim['e']} -> {to} ({why})")
        victim['e'] = to
        return True
    while True:                                       # showpieces: few enough, far enough apart
        show = [r for r in rows if r['e'] == 3]
        close = [(a, b) for a, b in zip(show, show[1:]) if b['t0'] - a['t0'] < APART and not (a['user'] and b['user'])]
        if len(show) > show_cap:
            if not demote(show, 2, f'{motion} allows {show_cap} showpieces'):
                notes.append(f'{len(show)} user showpieces; {motion} allows {show_cap}')
                break
        elif not close or not demote(close[0], 2, f'showpieces {APART:.0f} s apart'):
            break
    show = [r for r in rows if r['e'] == 3]
    for a, b in zip(show, show[1:]):
        if b['t0'] - a['t0'] < APART and a['user'] and b['user']:
            notes.append(f"{b['id']}: user showpiece within {APART:.0f} s of {a['id']}")
    while True:                                       # rest after a hit
        clashes = _clashes(rows)
        if not clashes or not demote({r['n']: r for pair in clashes for r in pair}.values(), 1,
                                     f'{REST:.0f} s of rest after a hit'):
            break
    for a, b in _clashes(rows, users=True):
        notes.append(f"{b['id']}: user energy {b['e']} follows {a['id']} within {REST:.0f} s")
    runtime = sum(r['t1'] - r['t0'] for r in rows) or 1.

    def share():
        return sum(r['t1'] - r['t0'] for r in rows if r['e'] >= 2) / runtime
    while share() > share_cap + 1e-9:                # time at energy 2 or more
        if not demote([r for r in rows if r['e'] >= 2], 1, f'{motion} keeps {share_cap:.0%} at 2+', longest=True):
            notes.append(f'user entries keep {share():.0%} of the runtime at 2+; {motion} allows {share_cap:.0%}')
            break
    for r in rows:
        if not r['user']:
            r['entry']['energy'] = r['e']
            r['entry'].setdefault('options', {})['energy'] = [max(0, r['e'] - 1), r['e']]
    histogram = {e: sum(r['e'] == e for r in rows) for e in range(4)}
    return {'histogram': histogram, 'e2_share': round(share(), 4), 'showpieces': histogram[3], 'notes': notes}


# ------------------------------------------------------------------ dials
def _dials(board):
    """(look, story, motion), defaults filled in; an unknown value is an error."""
    out = []
    for dial, values in DIALS.items():
        value = board.get(dial) or values[0]
        if value not in values:
            raise ValueError(f'{dial} must be one of {", ".join(values)}, got {value!r}')
        out.append(value)
    return tuple(out)


def _family(look, story):
    """Which template rules a look and story use: collage promos and showcases share one library."""
    if look != 'collage':
        return 'board' if styles.renderer(look) == 'whiteboard' else 'bold'
    return 'promo' if story in ('promo', 'showcase') else 'story'


def _label_end(text):
    """Where the words start after a structural label ("Today: ", "Part 1: ", "Key takeaway: ", "本节要点：")."""
    m = re.match(r'[^:：]{1,24}[:：]\s*', text)
    return m.end() if m else 0


def _body(text):
    return re.sub(r'[\s.!?。！？…”’"\')\]」』）]+$', '', text)


# ------------------------------------------------------------------- roles
def _brand(board, texts, lang):
    """{'name', 'url'} of the brand the video is about, or None (see the module docstring)."""
    given = board.get('brand') or {}
    if given.get('name'):
        return {'name': given['name'], 'url': given.get('url') or ''}
    if lang == 'es':
        return _es_brand(board, texts)
    if lang != 'en' or not texts:
        return None
    whole = ' '.join(texts)
    domain = DOMAIN.search(whole)
    for text in texts:
        m = INTRO.match(text)
        if m:                                         # "Meet Khan Academy.", not khanacademy.org's "khanacademy"
            return {'name': m.group(1), 'url': domain.group(0) if domain else ''}
    counts: dict = {}
    initial: dict = {}
    for text in texts:
        for k, m in enumerate(re.finditer(r"[A-Za-z][\w'’-]*", text)):
            word = m.group(0)
            if word[0].isupper() and word.lower() not in FUNCTION:
                counts[word] = counts.get(word, 0) + 1
                initial[word] = initial.get(word, 0) + (k == 0)
    if domain:                                        # friendr.nl -> "Friendr", as the script writes it
        return {'name': next((w for w in counts if w.lower() == domain.group(1).lower()), domain.group(1)),
                'url': domain.group(0)}
    lower = set(re.findall(r"\b[a-z][\w'’-]*", whole))
    title = (board.get('title') or {}).get(lang, '').strip()
    names = [w for w, n in counts.items() if n >= 2 and n > initial[w] and w.lower() not in lower
             and (w == title or any(_reveals(_body(t), w) for t in texts))]
    return {'name': max(names, key=counts.get), 'url': ''} if names else None


def _es_brand(board, texts):
    """Spanish introductions, domains and recurring names use the same brand evidence as English."""
    if not texts:
        return None
    whole = ' '.join(texts)
    domain = DOMAIN.search(whole)
    for text in texts:
        m = ES_INTRO.match(text)
        if m:
            return {'name': m.group(1), 'url': domain.group(0) if domain else ''}
    counts, initial = {}, {}
    for text in texts:
        for k, m in enumerate(re.finditer(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\w'’-]*", text)):
            word = m.group(0)
            if word[0].isupper() and word.lower() not in ES_FUNCTION:
                counts[word] = counts.get(word, 0) + 1
                initial[word] = initial.get(word, 0) + (k == 0)
    if domain:
        return {'name': next((w for w in counts if w.lower() == domain.group(1).lower()), domain.group(1)),
                'url': domain.group(0)}
    lower = set(re.findall(r"\b[a-záéíóúüñ][\w'’-]*", whole))
    title = (board.get('title') or {}).get('es', '').strip()
    names = [w for w, n in counts.items() if n >= 2 and n > initial[w] and w.lower() not in lower
             and (w == title or any(_reveals(_body(t), w, 'es') for t in texts))]
    return {'name': max(names, key=counts.get), 'url': ''} if names else None


def _reveals(body, name, lang='en'):
    """Does the sentence reveal the brand: "Meet X", "Introducing X", "With X", or just "X"?"""
    if lang == 'es':
        m = re.match(rf'(?:(conoce|presentamos|te presentamos|presentando|saluda a|con|esto es)\s+)?'
                     rf'{re.escape(name)}\b', body, re.I)
        return bool(m) and bool(m.group(1) or m.end() == len(body))
    m = re.match(rf'(?:(meet|introducing|say hello to|presenting|enter|with|this is)\s+)?{re.escape(name)}\b', body, re.I)
    return bool(m) and bool(m.group(1) or m.end() == len(body))


def _split_items(body, start=0, lang='en'):
    """(start, end) of the comma-separated parts of ``body[start:]``; "werewolves or padel" is two."""
    if lang == 'es':
        cuts = [(start + m.start(), start + m.end(), bool(re.search(r'(?:y|e|o|u)\s+$', m.group(0))))
                for m in re.finditer(r'\s*,\s*(?:(?:y|e|o|u)\s+)?', body[start:])]
    else:
        cuts = [(start + m.start(), start + m.end(), bool(re.search(r'(?:and|or)\s+$', m.group(0))))
                for m in re.finditer(r'\s*,\s*(?:(?:and|or)\s+)?', body[start:])]
    spans, a = [], start
    for s, e, _ in cuts:
        spans.append((a, s))
        a = e
    if cuts and not cuts[-1][2]:
        m = re.search(r'\s+(?:y|e|o|u)\s+' if lang == 'es' else r'\s+(?:and|or)\s+', body[a:])
        if m:
            return spans + [(a, a + m.start()), (a + m.end(), len(body))]
    return spans + [(a, len(body))]


def _whole_list(body, lang='en'):
    """Items of a sentence that is nothing but a list ("Drinks, movie night, werewolves or padel."), or []."""
    lead = re.match(r'(?:(?:y|e|o|u|como)\s+)?' if lang == 'es' else r'(?:(?:and|or|like)\s+)?', body, re.I).end()
    items = _split_items(body, lead, lang)
    first = [body[a:b].split()[0].lower() if body[a:b].split() else '' for a, b in items]
    if 3 <= len(items) <= 6 and all(1 <= len(body[a:b].split()) <= 7 for a, b in items) \
            and not any(w in (ES_NOT_ITEM if lang == 'es' else NOT_ITEM) or not w for w in first):
        return items
    return []


def _channels(body, lang='en'):
    """Items of "In the group chat, on Signal, or by email.", or []."""
    items = _split_items(body, lang=lang)
    preps = ES_CHANNEL_PREPS if lang == 'es' else CHANNEL_PREPS
    if 2 <= len(items) <= 5 and all(body[a:b].split() and body[a:b].split()[0].lower() in preps
                                    and len(body[a:b].split()) <= 5 for a, b in items):
        return items
    return []


def _inline_list(body, lang='en'):
    """Items of three or more short things in a row inside a longer sentence ("a book, a newspaper or a website")."""
    m = (ES_LIST_RUN if lang == 'es' else LIST_RUN).search(body)
    return [(m.start() + a, m.start() + b) for a, b in _split_items(m.group(0), lang=lang)] if m else []


def _zh_items(body):
    """Items of a Chinese list: three or more things between 、 (or short clauses between ，)."""
    tail = re.split(r'[：:]', body)[-1]
    at = len(body) - len(tail)
    for sep, cap in (('、', 8), ('，', 10)):
        parts = [(m.start() + at, m.end() + at) for m in re.finditer(rf'[^{sep}]+', tail)]
        if len(parts) >= 3 and all(len(re.findall(r'[一-鿿]', body[a:b])) <= cap for a, b in parts):
            return parts
    return []


def _imperative(body, lang='en'):
    if lang == 'es':
        words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\w'’-]*", body)
        while words and words[0].lower() in ES_LEADING | {'primero', 'después', 'finalmente', 'simplemente'}:
            words = words[1:]
        return len(words) >= 2 and words[0].lower() in ES_IMPERATIVE and words[1].lower() not in (
            'es', 'son', 'era', 'eran', 'ha', 'han', 'será', 'puede', 'pueden', 'podría', 'debe', 'deben')
    words = re.findall(r"[A-Za-z][\w'’-]*", body)
    while words and words[0].lower() in LEADING | {'first', 'next', 'finally', 'simply'}:
        words = words[1:]
    return len(words) >= 2 and words[0].lower() in IMPERATIVE and words[1].lower() not in (
        'is', 'are', 'was', 'were', 'has', 'have', 'had', 'will', 'can', 'could', 'would', 'should', 'may', 'might')


def _numbers(text, lang):
    """(start, end) of every salient number: not a year, decade, date or time; 20 or more, or with a unit, a scale
    or a percent sign."""
    out = []
    for d0, d1, _, _ in numbers.normalize(text, lang).spans:
        token = text[d0:d1]
        if lang == 'es':
            if re.fullmatch(r'(?:1[1-9]\d\d|20\d\d)(?:\s?[-–]\s?(?:1[1-9]\d\d|20\d\d))?', token) \
                    or ':' in token or ES_MONTHS.search(token):
                continue
            digits = re.sub(r'[^\d,.]', '', token).strip('.,')
            digits = digits.replace('.', '').replace(',', '.') if ',' in digits else digits
            if re.fullmatch(r'\d{1,3}(?:\.\d{3})+', digits):
                digits = digits.replace('.', '')
            value = float(digits) if re.fullmatch(r'\d+(?:\.\d+)?', digits) else 0.
            if value >= 20 or ES_SCALE.match(text[d1:]) or ES_UNIT.match(text[d1:]) \
                    or re.search(r'[%％$€£¥x×]|[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]', token):
                out.append((d0, d1))
            continue
        if re.fullmatch(r'(?:1[1-9]\d\d|20\d\d)(?:s|\s?[-–]\s?(?:1[1-9]\d\d|20\d\d))?', token) or ':' in token \
                or MONTHS.search(token) or re.match(r'\s*年', text[d1:]):
            continue
        digits = re.sub(r'[^\d.]', '', token).strip('.')
        value = float(digits) if re.fullmatch(r'\d+(?:\.\d+)?', digits) else 0.
        scaled = SCALE.match(text[d1:]) if lang == 'en' else re.match(r'[百千万亿倍]', text[d1:])
        if value >= 20 or scaled or re.search(r'[%％$€£¥x×]|[A-Za-z]', token):
            out.append((d0, d1))
    return out


def _quote(text, lang):
    """(start, end) of the quoted words ("the cat said, nap" -> "nap"), or None. A term in quotation marks
    (the "dandy horse") is not a quote."""
    m = QUOTED[lang].search(text)
    if m and (len(m.group(1).split()) >= 3 if lang in ('en', 'es') else len(re.findall(r'[一-鿿]', m.group(1))) >= 4):
        return m.start(1), m.end(1)
    m = SAID[lang].search(text)
    return (m.start('q'), m.end('q')) if m else None


def _mechanics(texts, lang):
    """Indexes of the sentences of condition pairs, with the threshold set just before them."""
    out = set()
    for k, text in enumerate(texts):
        if COND[lang].match(text):
            out.add(k)
            if k + 1 < len(texts) and not QUESTION[lang].search(texts[k + 1]):
                out.add(k + 1)                        # the answer: "Then it's called off." / "Green light."
            out |= {j for j in (k - 1, k - 2) if j >= 0 and THRESHOLD[lang].search(texts[j])}
    return out


def _detect(text, lang, story, brand, f, mechanic):
    """A narration sentence's role from its own words (``f``: where it is in the video, 0-1)."""
    body = _body(text)
    question = bool(QUESTION[lang].search(text))
    if _quote(text, lang):
        return 'quote'
    if mechanic:
        return 'mechanic'
    if lang == 'zh':
        if REVEAL['zh'].match(body):
            return 'reveal'
        if not question and _zh_items(body):
            return 'list'
        return 'question' if question else 'number' if _numbers(text, lang) else \
            'problem' if PAIN['zh'].search(text) else 'none'
    if lang == 'es':
        if brand and _reveals(body, brand['name'], lang):
            return 'brand'
        if ES_TURN.match(body):
            return 'turn'
        if REVEAL['es'].match(body):
            return 'reveal'
        if not question:
            if ES_FEATURE.match(body) and len(body.split()) <= 5:
                return 'feature'
            if _channels(body, lang):
                return 'channels'
            if ES_PEOPLE.search(body) and ES_JOIN.search(body):
                return 'social'
            items = _whole_list(body, lang)
            if items and story in ('promo', 'showcase') and all(len(body[a:b].split()) <= 3 for a, b in items):
                return 'use_cases'
            if items or _inline_list(body, lang):
                return 'list'
        if question:
            return 'question'
        if MIDDLE[0] <= f < MIDDLE[1] and (_imperative(body, lang) or ES_IN_TIME.search(body)):
            return 'step'
        if _numbers(text, lang):
            return 'number'
        return 'problem' if PAIN['es'].search(body) else 'none'
    if brand and _reveals(body, brand['name']):
        return 'brand'
    if TURN.match(body):
        return 'turn'
    if REVEAL['en'].match(body):
        return 'reveal'
    if not question:
        if FEATURE.match(body) and len(body.split()) <= 5:
            return 'feature'
        if _channels(body):
            return 'channels'
        if PEOPLE.search(body) and JOIN.search(body):
            return 'social'
        items = _whole_list(body)
        if items and story in ('promo', 'showcase') and all(len(body[a:b].split()) <= 3 for a, b in items):
            return 'use_cases'
        if items or _inline_list(body):
            return 'list'
    if question:
        return 'question'
    if MIDDLE[0] <= f < MIDDLE[1] and (_imperative(body) or IN_TIME.search(body)):
        return 'step'
    if _numbers(text, lang):
        return 'number'
    return 'problem' if PAIN['en'].search(body) else 'none'


def _roles(rows, content, lang, story, brand):
    """Set every row's role: its own words first, then its place in the video (see the module docstring)."""
    n = len(content)
    mechanic = _mechanics([r['text'] for r in content], lang)
    for k, r in enumerate(content):
        r['k'] = k
        r['role'] = _detect(r['text'], lang, story, brand, k / max(1, n - 1), k in mechanic)
    for r in rows:
        if r['kind'] != 'narration':
            r['role'] = 'question' if QUESTION[lang].search(r['text']) else 'none' if r['kind'] == 'closing' else 'tagline'
    for r in [r for r in content if r['role'] == 'brand'][1:]:
        r['role'] = 'tagline'                         # the brand is revealed once; later it signs off
    pivot = next((r['k'] for r in content if r['role'] in ('turn', 'brand')), None)
    if pivot is not None and pivot <= n // 2:         # what is said before an early turn sets up the problem
        for r in content[:pivot]:
            if r['role'] == 'none':
                r['role'] = 'problem'
    opening = max(4, round(n * OPENING))
    hook = next((r for r in rows if r['role'] == 'question' and (r['kind'] == 'title' or
                                                                   (r['kind'] == 'narration' and r['k'] < opening))), None)
    if hook is None and content and content[0]['role'] in ('none', 'problem', 'number'):
        hook = content[0]
    if hook is not None:
        hook['role'] = 'hook'
    tail = content[min(n - 1, int(n * TAIL)):] if content else []
    cta = next((r for r in reversed(tail) if r['role'] not in ('hook', 'quote') and
                ((ES_CTA if lang == 'es' else CTA).search(_body(r['text'])) or DOMAIN.search(r['text']) or
                 (brand and brand['name'].lower() in r['text'].lower()))), None)
    if cta is not None:
        cta['role'] = 'cta'
        for r in content[cta['k'] + 1:]:
            r['role'] = 'tagline'                     # what follows the call to action signs off
    elif content:
        content[-1]['role'] = 'end_line'
    for a, b in zip(content, content[1:]):            # what follows the uses in their paragraph sums them up
        if a['role'] == 'use_cases' and b['role'] == 'none' and a['beat'] is b['beat'] and story in ('promo', 'showcase'):
            b['role'] = 'tagline'
    for r in content:                                 # the closing run: "Everything that's better together."
        short = len(_body(r['text']).split()) <= 6 if lang in ('en', 'es') else len(re.findall(r'[一-鿿]', r['text'])) <= 12
        if r['role'] == 'none' and r['k'] / max(1, n - 1) >= TAIL and short and not QUESTION[lang].search(r['text']) \
                and r['beat']['chapter'] == content[-1]['beat']['chapter']:
            r['role'] = 'tagline'
    if cta is not None:                               # the sign-off: from the brand's last mention to the cta
        run = cta['k']
        while run > 0 and content[run - 1]['role'] == 'tagline':
            run -= 1
        start = next((r['k'] for r in reversed(content[run:cta['k']])
                      if brand and brand['name'].lower() in r['text'].lower()), cta['k'])
        for r in content[start:cta['k'] + 1]:
            r['lead'] = 'endcard'


# ------------------------------------------------------------------ scenes
def _scenes(role, text, kind, family, prev, lang):
    """2-3 scene ids for a sentence, the rules pick first; the look's default is always among them (the
    whiteboard has one scene). A plain sentence's words choose; otherwise the role does, then the words."""
    counts = family == 'bold' and bool(_numbers(text, lang))          # only a salient number counts up
    picks = [scene for scene in PICKS[family].get(role, []) if scene != 'count_up' or counts]
    cues = ES_CUES if lang == 'es' else CUES
    cued = [scene for pattern, scene in cues[family] if pattern.search(text)] + (['count_up'] if counts else [])
    order = ([s for s in cued if s in picks] + picks + cued) if role in CUE_FIRST else picks + cued
    order = [s for s in cued if s in LEADS] + order
    lead = KIND_SCENES.get(kind, {}).get(family)
    out = list(dict.fromkeys(([lead] if lead else []) + order))[:2]
    for extra in (DEFAULT_SCENE[family], prev, SPARE[family]):
        if extra and extra not in out and (extra == DEFAULT_SCENE[family] or len(out) < 2) \
                and extra in LIBRARY[family]:
            out.append(extra)
    return out[:3]


# ---------------------------------------------------------------- emphasis
def _words(phrase, lang):
    """How many words a phrase has (Chinese: about two characters a word; a number or a range is one)."""
    if lang == 'zh':
        return -(-len(re.findall(r'[一-鿿]', phrase)) // 2) + \
            len(re.findall(r'[A-Za-z]+|\d[\d.,%％]*(?:\s?[到至~～–-]\s?\d[\d.,%％]*)?', phrase))
    return len(phrase.split())


def _readable(emphasis, lang):
    """A big move needs a short key phrase to show: at most four words."""
    return bool(emphasis) and _words(emphasis, lang) <= READABLE_WORDS


def _last_content(toks, j, lang='en'):
    """Index of the last word at or before ``j`` that carries meaning, or -1: "called off" keeps its particle,
    "for everyone" is dropped."""
    function = ES_FUNCTION if lang == 'es' else FUNCTION
    indefinite = ES_INDEFINITE if lang == 'es' else INDEFINITE
    while j >= 0:
        word = toks[j][2]
        if lang != 'es' and word in PARTICLES and j > 0 and toks[j - 1][2] not in function:
            return j
        if word in function or (word in indefinite and j > 0 and toks[j - 1][2] in function):
            j -= 1
            continue
        return j
    return -1


def _end_focus(toks, lang='en'):
    """The words at the end of a clause, where English puts what is new: "a purpose", "enormous books",
    "scissors and glue", "purpose of life", "called off" (at most three words)."""
    function = ES_FUNCTION if lang == 'es' else FUNCTION
    indefinite = ES_INDEFINITE if lang == 'es' else INDEFINITE
    dets = ES_DETS if lang == 'es' else DETS
    links = ('y', 'e', 'o', 'u', 'de') if lang == 'es' else ('and', 'or', 'of')
    j = _last_content(toks, len(toks) - 1, lang)
    if j < 0:
        return None
    k = j
    if k > 0 and toks[k - 1][2] not in function and toks[k - 1][2] not in indefinite:
        k -= 1
    if k == j and k >= 2 and toks[k - 1][2] in links and toks[k - 2][2] not in function:
        k -= 2                                        # "scissors and glue", "purpose of life"
    if k > 0 and toks[k - 1][2] in dets and j - k < 2:
        k -= 1
    return toks[k][0], toks[j][1]


def _phrases(text, role, lang, brand, head=0, names=True):
    """Up to four key phrases (at most three words each, each cut from ``text``), the rules pick first: the role's
    own (the brand, the domain, a quote's words, list items, a threshold), then a short sentence whole, salient
    numbers, names, the end of each clause (last clause first) and its first words. ``head``: where the words
    start after a label."""
    out: list = []

    def add(a, b):
        while a < b and not (text[a].isalnum() or text[a] in '$€£'):
            a += 1
        while b > a and not (text[b - 1].isalnum() or text[b - 1] in '%％'):
            b -= 1
        phrase = text[a:b]
        low = phrase.lower() + ' '
        if phrase and _words(phrase, lang) <= EMPHASIS_WORDS and not any(      # "Enough" adds nothing to "Enough people"
                low.startswith(p.lower() + ' ') or (p.lower() + ' ').startswith(low) for p in out):
            out.append(phrase)
    if lang == 'zh':
        _zh_phrases(text, role, head, add)
        return out[:4]
    function = ES_FUNCTION if lang == 'es' else FUNCTION
    leading = ES_LEADING if lang == 'es' else LEADING
    dets = ES_DETS if lang == 'es' else DETS
    not_item = ES_NOT_ITEM if lang == 'es' else NOT_ITEM
    preps = ES_CHANNEL_PREPS if lang == 'es' else CHANNEL_PREPS
    token = ES_TOKEN if lang == 'es' else TOKEN
    body_end = head + len(_body(text[head:]))
    toks = [(m.start(), m.end(), m.group(0).lower().replace('’', "'")) for m in token.finditer(text, head, body_end)]
    domains = [m.span() for m in DOMAIN.finditer(text)]
    if role == 'cta':
        for a, b in domains:
            add(a, b)
    if brand and role in ('brand', 'tagline', 'cta', 'turn'):
        for m in re.finditer(re.escape(brand['name']), text, re.I):
            if not any(a <= m.start() < b for a, b in domains):
                add(*m.span())
    if role == 'cta':
        pattern = r'\b(?:por\s+)?gratis\b|\b(?:pruébalo|pruébenlo|regístrate|regístrense|únete|únanse)\b|' \
            r'\b(?:prueba|prueben|empieza|empiecen|descarga|descarguen)\s+(?:ahora|hoy)\b' \
            if lang == 'es' else r'\b(?:for\s+)?free\b|\b(?:try|start|get|join|download)\s+(?:it|now|today|started)\b'
        for m in re.finditer(pattern,
                             text, re.I):
            add(*m.span())
    if role == 'quote':
        span = _quote(text, lang)
        if span:
            add(*span)
        m = SAID[lang].search(text)
        if m:
            add(*m.span('who'))
    if role in ('channels', 'use_cases', 'list'):
        body = text[head:body_end]
        items = _channels(body, lang) if role == 'channels' else _whole_list(body, lang) or _inline_list(body, lang)
        for a, b in items:
            words = [(m.start(), m.end(), m.group(0).lower()) for m in token.finditer(body, a, b)]
            while words and (words[0][2] in preps or (role == 'channels' and words[0][2] in dets)
                             or (len(words) > 1 and words[0][2] in not_item)):
                words = words[1:]
            if len(words) > EMPHASIS_WORDS:           # "a dog who's thrilled you're home" -> "a dog"
                words = words[:2] if words[0][2] in dets else words[:1]
            if words:
                add(head + words[0][0], head + words[-1][1])
    if role == 'mechanic':
        for m in THRESHOLD[lang].finditer(text):
            before = re.search(r'\b(?:un|una|el|la)\s+$' if lang == 'es' else r'\b(?:a|an|the)\s+$', text[:m.start()])
            add(before.start() if before else m.start(), m.end())
    join = ES_JOIN if lang == 'es' else JOIN
    if role == 'social' and join.search(text):
        add(*join.search(text).span())
    k = 0
    while k < len(toks) and toks[k][2] in leading:
        k += 1
    j = _last_content(toks, len(toks) - 1, lang)
    if k <= j and j - k < EMPHASIS_WORDS:             # a short line whole: "Green light", "No account"
        add(toks[k][0], toks[j][1])
    for a, b in [(a, b) for a, b in _numbers(text, lang) if a >= head]:
        rest = text[b:]
        if lang == 'es':
            scale = ES_SCALE.match(rest)
            end = b + (scale.end() if scale else 0)
            unit = ES_UNIT.match(text, end)
            if unit:
                end = unit.end()
            else:
                m = re.match(r"\s+de\s+(?:(?:el|la|los|las)\s+)?[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\w'’-]*", text[end:]) \
                    if text[a:b].endswith('%') else None
                end += m.end() if m else 0
            add(a, end)
            continue
        end = b + (SCALE.match(rest).end() if SCALE.match(rest) else 0)
        m = re.match(r"\s+of\s+(?:the\s+)?[A-Za-z][\w'’-]*", text[end:]) if text[a:b].endswith('%') else \
            re.match(r"\s+(?:[A-Z][\w'’-]*\s+)?(?!(?:and|or|of|to|in|on|at|for|by|with|from|than|later|ago|more|"
                     r"less|is|are|was|were)\b)[A-Za-z][\w'’-]*", text[end:])
        add(a, end + m.end() if m else end)
    if names:                                         # a name said mid-sentence: "Signal", "Susan B. Anthony"
        run = []
        for t in toks[1:] + [(len(text), len(text), '')]:
            if t[2] and text[t[0]].isupper() and t[2] not in function and \
                    (not run or re.fullmatch(r'\.?\s+', text[run[-1][1]:t[0]])):
                run.append(t)
                continue
            if run:
                add(run[0][0], run[-1][1])
            run = [t] if t[2] and text[t[0]].isupper() and t[2] not in function else []
    clauses = [(m.start(), m.end()) for m in re.finditer(r'[^,;:—–]+', text[:body_end])]
    for a, b in reversed([c for c in clauses if c[1] > head]):
        span = _end_focus([t for t in toks if a <= t[0] < b], lang)
        if span:
            add(*span)
    first = next((n for n in range(k, len(toks)) if toks[n][2] not in function), None)
    if first is not None:                             # the first word that carries meaning: "your friends"
        add(toks[first - 1][0] if first > k and toks[first - 1][2] in dets else toks[first][0], toks[first][1])
    return out[:4]


def _zh_phrases(text, role, head, add):
    """Chinese key phrases: numbers with their unit, quoted words, list items, the last words of each clause."""
    spans = [(a, b) for a, b in _numbers(text, 'zh') or [s[:2] for s in numbers.normalize(text, 'zh').spans] if a >= head]
    while spans:
        a, b = spans.pop(0)
        if spans and re.fullmatch(r'\s?(?:到|至|-|–|~|～)\s?', text[b:spans[0][0]]):
            b = spans.pop(0)[1]                       # "7到9个小时": a range is one phrase
        unit = ZH_UNIT.match(text, b)
        add(a, unit.end() if unit else b)
    span = _quote(text, 'zh')
    if span:
        add(*span)
    if role == 'list':
        body = _body(text[head:])
        for a, b in _zh_items(body):
            add(head + a, head + b)
    import jieba
    for m in reversed(list(re.finditer(r'[^，。！？；：、,.!?;:]+', text[head:]))):
        a = head + m.start()
        words = [(a + s, a + e) for w, s, e in jieba.tokenize(m.group(0))
                 if re.search(r'[一-鿿A-Za-z0-9]', w) and w not in ZH_FUNCTION]
        if words:
            s, e = words[-1]
            if len(words) > 1 and len(re.findall(r'[一-鿿]', text[words[-2][0]:e])) <= 6:
                s = words[-2][0]                      # "最好的投资": the last two words when they are short
            add(s, e)


# ----------------------------------------------------------------- planner
def _timed(board, timeline, notes):
    """One row per direction entry, in video order, with its time on the master clock (t0, t1)."""
    lang = board['lang']
    info_of = (timeline or {}).get('beats') or {}
    rows, clock = [], 0.
    for beat in board['beats']:
        norm = numbers.normalize(beat['display'][lang], lang)
        info = info_of.get(beat['id'])
        if info and info.get('char_times'):
            end, clock = info['speech_end'], info.get('end', info['speech_end'])

            def at(pos, start=info['start'], ct=info['char_times']):
                return start + ct[min(pos, len(ct) - 1)]
        else:
            end = clock + len(norm.spoken) / CPS[lang]

            def at(pos, start=clock):
                return start + pos / CPS[lang]
            clock = end
        entries = []
        for entry in beat.get('direction') or []:
            span = entry.get('span') if isinstance(entry, dict) else None
            if isinstance(span, list) and len(span) == 2 and all(isinstance(x, int) for x in span):
                entries.append(entry)
            else:
                notes.append(f"{beat['id']}: a direction entry without a usable span is left out of the plan")
        for entry in sorted(entries, key=lambda e: e['span'][0]):
            s0, s1 = norm.to_spoken(entry['span'][0]), norm.to_spoken(entry['span'][1])
            role = entry.get('role') if isinstance(entry.get('role'), str) else 'none'
            rows.append({'entry': entry, 'id': f"{beat['id']}#{entry.get('i')}", 'role': role,
                         'user': entry.get('source') == 'user', 'n': len(rows),
                         't0': at(s0), 't1': max(at(s0), end if s1 >= len(norm.spoken) else at(s1))})
    return rows


def _anchors(rows):
    """Row numbers of the structural anchors: the first hook, the brand reveal, the final cta (else end line)."""
    first = {role: next((r['n'] for r in rows if r['role'] == role), None) for role in ('hook', 'brand')}
    last = {role: next((r['n'] for r in reversed(rows) if r['role'] == role), None) for role in ('cta', 'end_line')}
    final = last['cta'] if last['cta'] is not None else last['end_line']
    return {first['hook'], first['brand'], final} - {None}


def _clashes(rows, users=False):
    """(hit, sentence) pairs where a sentence at 2 or more starts within REST seconds after a hit ends, unless it
    goes on the hit's list or cascade. ``users``: only pairs a user set on both sides (they stay, reported)."""
    out = []
    for a in rows:
        if a['e'] < 2:
            continue
        for b in rows[a['n'] + 1:]:
            if b['t0'] >= a['t1'] + REST:
                break
            if b['e'] >= 2 and (a['user'] and b['user']) == users and not (
                    a['role'] == b['role'] and a['role'] in CASCADE
                    and all(r['role'] == a['role'] for r in rows[a['n']:b['n'] + 1])):
                out.append((a, b))
    return out
