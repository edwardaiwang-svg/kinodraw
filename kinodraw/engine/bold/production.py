"""A scene timeline with the frame/warnings/ctx.elements/cues interface of the collage renderer."""
from __future__ import annotations

import bisect
from types import SimpleNamespace

from PIL import Image

from .render import render_frame
from .transitions import render_transition


class BoldProduction:
    vertical = False

    def __init__(self, scenes, size=(1920, 1080), transition_duration=.65):
        if not scenes or transition_duration <= 0:
            raise ValueError('A bold production needs scenes and a positive transition duration')
        self.scenes = list(scenes)
        self.size = size
        self.transition_duration = transition_duration
        self.starts = []
        self.duration = 0.
        for scene in self.scenes:
            self.starts.append(self.duration)
            self.duration += scene.duration
        self.warnings = []
        self.ctx = SimpleNamespace(elements=[SimpleNamespace(beat=None, start=start + e.start,
                                   end=start + (e.end if e.end is not None else scene.duration),
                                   skipped=False, fixed=True, words=e.text)
                                   for start, scene in zip(self.starts, self.scenes) for e in scene.elements])
        self.els = self.ctx.elements
        self.cuts = [start for start, scene in zip(self.starts[1:], self.scenes[1:]) if scene.transition_in == 'cut']

    def frame_array(self, t):
        i = max(0, min(len(self.scenes) - 1, bisect.bisect_right(self.starts, t) - 1))
        local = t - self.starts[i]
        scene = self.scenes[i]
        w, h = self.size
        if i and scene.transition_in != 'cut' and local < min(self.transition_duration, scene.duration):
            return render_transition(self.scenes[i - 1], scene, local, w, h,
                                     duration=min(self.transition_duration, scene.duration))
        return render_frame(scene, local, w, h)

    def frame(self, t):
        return Image.fromarray(self.frame_array(t), 'RGB')

    def cues(self):
        return [{'t': start, 'kind': 'whoosh', 'strength': .5, 'id': f'bold.join.{i}'}
                for i, (start, scene) in enumerate(zip(self.starts, self.scenes)) if i and scene.transition_in != 'cut']
