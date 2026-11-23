"""Token budgeting: estimate, rank and condense evidence so it fits a budget."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# USD per 1M tokens (input, output). Unknown models -> no cost shown.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-2": (8.00, 40.00),
}

# Room kept for the system prompt, the question and formatting around the context.
PROMPT_OVERHEAD = 600


@dataclass
class Chunk:
    source: str  # evidence pointer: path, path:line, binary@offset or URL
    text: str
    weight: float = 1.0  # prior importance (README > random file)


def parse_budget(value: str | int) -> int:
    """'20k' -> 20000, '1.5m' -> 1500000, '8000' -> 8000."""
    s = str(value).strip().lower().replace("_", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)", s)
    if not m:
        raise ValueError(f"budget inválido: {value!r} (use ex.: 8000, 20k, 1m)")
    n = float(m.group(1)) * {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2)]
    if n < 1000:
        raise ValueError("budget mínimo é 1000 tokens")
    return int(n)


def estimate_tokens(text: str) -> int:
    # shortcut: ~3.5 chars/token is a conservative offline guess for code+English;
    # use the provider's count_tokens endpoint for exact numbers (done before real calls).
    return math.ceil(len(text) / 3.5) if text else 0


def terms_of(question: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_]{3,}", question.lower())
    stop = {"how", "does", "what", "the", "and", "work", "works", "this", "that", "with",
            "como", "funciona", "que", "para", "uma", "isso", "esse", "essa", "onde"}
    return {w for w in words if w not in stop}


def score(chunk: Chunk, terms: set[str]) -> float:
    hay_src = chunk.source.lower()
    hay = chunk.text.lower()
    hits = sum(3 * (t in hay_src) + min(hay.count(t), 10) for t in terms)
    return chunk.weight * (1 + math.log1p(hits))


def condense(chunks: list[Chunk], budget: int, question: str) -> tuple[list[Chunk], int]:
    """Pick the highest-scoring chunks that fit `budget`. Returns (kept, n_dropped).

    Greedy: best-first, whole chunks when they fit, otherwise the chunk is cut to the
    remaining space (if that space is still worth it) and the rest are dropped.
    """
    terms = terms_of(question)
    room = budget - PROMPT_OVERHEAD - estimate_tokens(question)
    kept: list[Chunk] = []
    dropped = 0
    for c in sorted(chunks, key=lambda c: score(c, terms), reverse=True):
        cost = estimate_tokens(c.text) + estimate_tokens(c.source) + 4
        if cost <= room:
            kept.append(c)
            room -= cost
        elif room > 150:
            cut = int((room - estimate_tokens(c.source) - 10) * 3.5)
            kept.append(Chunk(c.source, c.text[:cut] + "\n…[cortado pelo budget]", c.weight))
            room = 0
        else:
            dropped += 1
    return kept, dropped


def render(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"### {c.source}\n{c.text}" for c in chunks)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    if model not in PRICES:
        return None
    pin, pout = PRICES[model]
    return (input_tokens * pin + output_tokens * pout) / 1_000_000
