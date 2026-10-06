"""Source headlines must not erase an ordinary chapter's only narration."""
from kinodraw import ingest, script
from kinodraw.engine import timeline


def test_single_sentence_sections_keep_their_narration_and_title_takeaway():
    facts = ['The ferry stopped beside the harbor.', 'The crew gave supplies to the island.']
    doc = ingest.Document('An island journey', 'en', [], [
        ingest.Section('Ferries stop', [facts[0]]), ingest.Section('Crews deliver', [facts[1]])])
    board = script.build(doc)
    for chapter, fact, title in zip(['s1', 's2'], facts, ['Ferries stop', 'Crews deliver']):
        beats = [b for b in board['beats'] if b['chapter'] == chapter]
        assert [b['kind'] for b in beats] == ['opener', 'narration', 'take']
        assert beats[1]['display']['en'] == fact
        assert beats[-1]['take']['headline']['en'] == title + '.'
        section = next(c for c in board['chapters'] if c['id'] == chapter)
        assert section['hook']['en'].removesuffix('…') in fact
    timing = timeline.layout(board, 'en', timeline.synthetic_clips(board, 'en'))
    first_take = next(b for b in board['beats'] if b['chapter'] == 's1' and b['kind'] == 'take')
    first_narration = next(b for b in board['beats'] if b['chapter'] == 's1' and b['kind'] == 'narration')
    assert timing['beats'][first_take['id']]['start'] > timing['beats'][first_narration['id']]['speech_end']


def test_a_question_title_keeps_its_only_complete_source_fact_in_narration():
    fact = 'The ferry stopped beside the harbor.'
    board = script.build(ingest.Document('The journey', 'en', [], [
        ingest.Section('Where did the ferry stop?', [fact]),
        ingest.Section('Supplies', ['The crew unloaded fresh supplies.'])]))
    beats = [b for b in board['beats'] if b['chapter'] == 's1']
    assert [b['kind'] for b in beats] == ['opener', 'narration', 'take']
    assert beats[1]['display']['en'] == fact
    assert beats[-1]['take']['headline']['en'] == fact
    assert beats[-1]['display']['en'] == script.take_text(fact, 'en')


def test_a_separate_closing_summary_is_still_said_once_on_the_note():
    fact = 'The ferry carried supplies to the island.'
    board = script.build(ingest.Document('The journey', 'en', [], [
        ingest.Section('Supplies reach the island', ['Workers loaded the ferry at dawn.', fact]),
        ingest.Section('Homeward', ['The crew returned to the harbor.'])]))
    beats = [b for b in board['beats'] if b['chapter'] == 's1']
    assert [b['kind'] for b in beats] == ['opener', 'narration', 'take']
    assert beats[-1]['take']['headline']['en'] == fact
    assert sum(fact in b['display']['en'] for b in beats) == 1
