"""Twelve seconds of one amber motif turning from a dot into a ring, a line and data."""
from .model import MotionElement as E, MotionScene


def demo_scenes():
    def captions(chapter):
        return [E(text='KINODRAW / MOTION', preset='corner_caption', x=.15, y=.065, size=19, width=440),
                E(text=chapter, preset='corner_caption', x=.85, y=.94, size=19, width=440)]

    title = MotionScene(duration=2.5, camera='slow_push', treatment='kinetic_type', elements=[
        E(text='Everything flows.', x=.5, y=.44, size=122, width=1480),
        E(text='ONE IDEA. MANY FORMS.', preset='corner_caption', x=.5, y=.61, size=23, start=.9),
        E(kind='dot', motif='idea', x=.5, y=.72, size=24, emissive=True),
        *captions('01 / THE IDEA')])
    counter = MotionScene(duration=2.5, transition_in='morph', elements=[
        E(kind='ring', motif='idea', x=.5, y=.49, size=390, emissive=True),
        E(text='', preset='counter', value_to=4160, duration=1.8, x=.5, y=.46, size=132, width=700),
        E(text='WEEKS TO MAKE IT COUNT', preset='corner_caption', x=.5, y=.65, size=22, start=.6),
        *captions('02 / KEEP COUNTING')])
    reveal = MotionScene(duration=3., transition_in='morph', energy=4, elements=[
        E(kind='line', motif='idea', x=.5, y=.7, width=1230, size=10, emissive=True),
        E(text='Build', preset='word_pop', x=.23, y=.42, width=440, start=.3, kick=10),
        E(text='Move', preset='word_pop', x=.5, y=.42, width=440, start=.95, kick=10, accent=True),
        E(text='Connect', preset='word_pop', x=.77, y=.42, width=440, start=1.6, kick=10),
        E(kind='particle_field', x=.5, y=.68, width=1250, height=170, count=48, start=.5, emissive=True),
        *captions('03 / THREE SMALL STEPS')])
    chart = MotionScene(duration=4., transition_in='morph', treatment='chart', elements=[
        E(kind='dot', motif='idea', x=.79, y=.3, size=22, emissive=True),
        E(text='Motion compounds.', preset='cascade', x=.5, y=.22, size=90, width=1400, start=.2),
        E(kind='chart', chart='bar', values=(22, 38, 59, 84), labels=('IDEA', 'FORM', 'FLOW', 'IMPACT'),
          x=.35, y=.58, width=800, height=280, start=.7),
        E(kind='chart', chart='line', values=(12, 25, 20, 48, 62, 84), x=.79, y=.52, width=420, height=180, start=.8),
        E(kind='chart', chart='number', value_to=84, suffix='%', x=.79, y=.74, size=100, width=400, start=.8),
        *captions('04 / MAKE IT VISIBLE')])
    return [title, counter, reveal, chart]
