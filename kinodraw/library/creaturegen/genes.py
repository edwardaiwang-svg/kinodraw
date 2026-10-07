"""Typed genes with seeded sampling around a species prior.

As in procedural-pixel-creatures, a species is a prior (typical values) and an individual is sampled
around it: float genes move within a bounded spread, choice genes pick by weight. Random numbers come
from a tiny xorshift stream seeded by (species, variant, stream) so outputs are identical on every
machine and Python version.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields, replace


def stream(*key) -> callable:
    seed = int.from_bytes(hashlib.sha256('|'.join(map(str, key)).encode()).digest()[:4], 'big') or 1
    state = [seed]

    def nxt():
        x = state[0]
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        state[0] = x & 0xFFFFFFFF
        return state[0] / 0xFFFFFFFF
    return nxt


def seed_of(*key) -> int:
    return int.from_bytes(hashlib.sha256('|'.join(map(str, key)).encode()).digest()[:4], 'big')


@dataclass(frozen=True)
class FloatGene:
    name: str
    spread: float = .04           # relative spread (fraction of the prior value)
    lo: float = 0.0
    hi: float = 10.0


# Proportion genes shared by every plan that has these fields; spreads stay small so the species
# silhouette never changes, only the individual.
PROPORTIONS = (
    FloatGene('L', .04), FloatGene('chest_r', .04), FloatGene('hip_r', .04), FloatGene('head_r', .03),
    FloatGene('neck_len', .06), FloatGene('tail_len', .08), FloatGene('ear_size', .06), FloatGene('snout', .05),
    FloatGene('leg_r', .04),
)


def individual(prior, *key, amount: float = 1.0):
    """Sample an individual around ``prior`` (a dataclass) with the anatomy stream of ``key``."""
    rnd = stream('anatomy', *key)
    names = {f.name for f in fields(prior)}
    changes = {}
    for gene in PROPORTIONS:
        if gene.name not in names:
            continue
        value = getattr(prior, gene.name)
        if not isinstance(value, float) or value == 0:
            continue
        changes[gene.name] = min(gene.hi, max(gene.lo, value * (1 + (rnd() * 2 - 1) * gene.spread * amount)))
    if 'seed' in names:
        changes['seed'] = seed_of('pattern', *key)
    return replace(prior, **changes)
