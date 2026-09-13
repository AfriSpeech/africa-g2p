"""Cross-language grapheme converter.

Takes the native-orthography graphemes of one language and rewrites them in the
graphemes another language uses for the same phonemes, routing both through IPA:

    L1 graphemes -> IPA -> L2 graphemes

Either side may be the virtual language ``"universal"`` — the per-IPA majority
grapheme set distilled from all 400 language charts (see
``scripts/ipa_universal_graphemes.py``). When a source phoneme has no entry in the
target's chart, the universal grapheme is used as a fallback.

    >>> from africa_g2p import GraphemeConverter
    >>> GraphemeConverter("twi", "ewe").convert("Onyankopɔn")      # text, words kept
    >>> GraphemeConverter("twi", "universal").convert("Onyankopɔn", sep=" ")  # units
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

from .g2p import G2P
from .loader import load_rules
from .normalizer import normalize_text, tie_affricates, tokenize

_DATA = Path(__file__).resolve().parent / "data"
_UNIVERSAL_FILE = _DATA / "ipa_universal_graphemes.json"

# Virtual language code: "write every phoneme with the grapheme most languages use".
UNIVERSAL = "universal"

_universal_forward: Dict[str, str] = {}
_universal_reverse: Dict[str, str] = {}
_reverse_cache: Dict[str, Dict[str, str]] = {}


def _universal_tables() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Forward (majority grapheme -> IPA) and reverse (IPA -> majority grapheme)
    tables for the virtual "universal" language, loaded once from the survey output."""
    global _universal_forward, _universal_reverse
    if not _universal_reverse:
        data = json.loads(_UNIVERSAL_FILE.read_text(encoding="utf-8"))
        # Build forward with the most-widespread phoneme winning on grapheme collisions
        # (two phonemes whose majority grapheme is the same string, e.g. 'j' for d͡ʒ
        # and ɟ), so `setdefault` keeps the commonest reading. IPA keys and values are
        # tie-affricate-normalised to match the forward engine's output exactly.
        order = sorted(data["phonemes"].items(), key=lambda kv: -kv[1]["langs"])
        for raw_ipa, v in order:
            ipa = tie_affricates(raw_ipa)
            if v["grapheme"]:  # guard against empty winners
                _universal_forward.setdefault(v["grapheme"], ipa)
                _universal_reverse.setdefault(ipa, v["grapheme"])
    return _universal_forward, _universal_reverse


def _primary_grapheme(rule: dict, candidates: set) -> str:
    """Choose the canonical written grapheme for a phoneme within one language.

    Picks the first candidate to appear in the language's own `alphabet` row (the
    orthographer's ordering), then the first in the Latin script list, then the
    shortest, then lexicographically — so the result is deterministic and prefers the
    language's endorsed way of writing the sound over an allophonic variant.
    """
    for a in rule.get("alphabet") or []:
        if a in candidates:
            return a
    for a in (rule.get("scripts") or {}).get("latin") or []:
        if a in candidates:
            return a
    return min(sorted(candidates), key=lambda g: (len(g), g))


def reverse_table(lang: str) -> Dict[str, str]:
    """IPA -> primary grapheme for a real language's chart (cached)."""
    if lang not in _reverse_cache:
        rules = load_rules(lang)
        grouped: Dict[str, set] = {}
        for g, ipa in rules.get("graphemes", {}).items():
            # keys normalised the same way as the forward engine's IPA output
            grouped.setdefault(tie_affricates(ipa), set()).add(g)
        _reverse_cache[lang] = {
            ipa: _primary_grapheme(rules, cands) for ipa, cands in grouped.items()
        }
    return _reverse_cache[lang]


class GraphemeConverter:
    """Rewrite one language's graphemes in another's, per shared phonemes."""

    def __init__(self, source: str, target: str):
        """
        Args:
            source: ISO 639-3 code of the input language, or "universal" to read the
                    majority grapheme set.
            target: ISO 639-3 code of the output language, or "universal" to write
                    every phoneme with the grapheme most languages use.
        """
        forward, reverse = _universal_tables()
        self.source = source
        self.target = target
        # Forward engine: language graphemes -> IPA (or majority graphemes -> IPA).
        if source == UNIVERSAL:
            self._forward = G2P.from_rules({"code": UNIVERSAL, "graphemes": forward})
        else:
            self._forward = G2P(source, output="ipa")
        # Reverse table: IPA -> target graphemes.
        self._reverse = reverse if target == UNIVERSAL else reverse_table(target)
        self._universal_reverse = reverse

    def convert(self, text: str, *, sep: str = "", lower: bool = True) -> str:
        """Convert a full text. Word boundaries (spacing and punctuation) are always
        preserved; `sep` joins the phoneme units *within* a word — so the default
        ``sep=""`` emits continuous text, while ``sep=" "`` prints every unit as a
        separate token (the phoneme-sequence view)."""
        text = normalize_text(text, lower=lower)
        out: list = []
        for tok in tokenize(text):
            if not tok.is_word:
                out.append(tok.text)
                continue
            units = self._forward.convert_word(tok.text, sep=" ", lower=False).split(" ")
            out.append(sep.join(self._map(ipa) for ipa in units))
        return "".join(out)

    def convert_word(self, word: str, *, sep: str = "", lower: bool = True) -> str:
        """Convert a single word (no tokenization)."""
        """Convert a single word (no tokenization)."""
        word = normalize_text(word, lower=lower)
        units = self._forward.convert_word(word, sep=" ", lower=False).split(" ")
        return sep.join(self._map(ipa) for ipa in units)

    def _map(self, ipa: str) -> str:
        # Target's own writing for the phoneme; the majority grapheme if the target
        # chart has no entry; the IPA unit itself as a last-resort passthrough.
        return self._reverse.get(ipa, self._universal_reverse.get(ipa, ipa))


def convert_lang(text: str, source: str, target: str, *, sep: str = "") -> str:
    """One-shot converter: ``convert_lang("Onyankopɔn", "twi", "ewe")``. Words are
    kept whole by default; pass ``sep=" "`` for per-unit (phoneme-sequence) output."""
    return GraphemeConverter(source, target).convert(text, sep=sep)