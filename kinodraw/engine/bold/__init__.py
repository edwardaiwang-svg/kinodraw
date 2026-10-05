"""Smooth procedural motion graphics, alongside the whiteboard and collage looks."""
from .model import MotionElement, MotionScene, Palette
from .render import render_frame
from .transitions import render_transition
from .production import BoldProduction

__all__ = ['MotionElement', 'MotionScene', 'Palette', 'render_frame', 'render_transition', 'BoldProduction']
