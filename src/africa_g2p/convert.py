"""Cross-language grapheme converter.

Takes the native-orthography graphemes of one language and rewrites them in the
graphemes another language uses for the same phonemes, routing both through IPA:

    L1 graphemes -> IPA -> L2 graphemes

Either side may be the virtual language ``"universal"`` — the per-IPA grapheme set distilling
    all 400 language charts: majority winners of ``scripts/ipa_universal_graphemes.py``, re-judged
    per IPA by Gemini into common Latin/English spellings (see
    ``scripts/build_universal_from_gemini.py``). When a source phoneme has no entry in the target's
    chart, the universal grapheme is used as a fallback.

    >>> from africa_g2p import GraphemeConverter
    >>> GraphemeConverter("twi", "ewe").convert("Onyankopɔn")      # text, words kept
    >>> GraphemeConverter("twi", "universal").convert("Onyankopɔn", sep=" ")  # units
"""
from __future__ import annotations

import json
import re
import unicodedata
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
_universal_g2p: "G2P | None" = None
_reverse_cache: Dict[str, Dict[str, str]] = {}

# IPA aspiration marks: modifier small-h U+02B0 (ʰ) and breathy-voiced hook U+02B1 (ʱ).
# Dropped to relax an aspirated phoneme onto its plain counterpart for matching.
_ASPIRATION_TRANS = str.maketrans({"\u02b0": "", "\u02b1": ""})


def _relax_aspiration(ipa: str) -> str:
    """Drop aspiration/breathy marks: /tɕʰ/ -> /tɕ/, /kʰ/ -> /k/, /ɡʱ/ -> /ɡ/."""
    return ipa.translate(_ASPIRATION_TRANS)


# --- single-phoneme filter for the universal *forward* ("reading") table ---------
# The per-IPA grapheme picks include transliterations of multi-phoneme fidel
# syllables (e.g. /k͡p a/ as "kpa", /ɓ i/ as "bi"). Those are fine for writing
# (reverse table: IPA -> pick verbatim) but must not become graphemes of the
# virtual universal orthography (forward table) — the greedy tokenizer would
# otherwise slice ordinary words like "kpako" into "kpa"+"ko". A value counts as
# one phoneme segment iff it has at most two core letters, and for two they form
# a coarticulated CONSONANT pair (k͡p, t͡ʃ, ᵑɡ͡b, ts, ny ...), not C+V.
_VOWELS = set("aàáãäæèéêëɛəɐɑɒɔɜɞɘɚeẽiĩɪɨɤɵoõöòóôuùũüʊʉɯʏøœyỹʌǝǐịụ")
_VOWEL_ALTERNATIVES = {
    "o": "u",
    "u": "o",
    "e": "i",
    "i": "e",
    "ɔ": "u",
    "ɛ": "i",
    "a": "ə",
    "ə": "a",
}

try:
    from spellchecker import SpellChecker
    _spell = SpellChecker()
except ImportError:
    _spell = None


def _is_english_word(word: str) -> bool:
    if _spell is None or len(word) < 3:
        return False
    if not word.isalpha() or not word.isascii():
        return False
    return word.lower() in _spell
_SKIP_CATEGORIES = frozenset(("Mn", "Lm", "Cn", "Pc", "Pe", "Pf", "Po", "Ps", "Sm"))
_TIE_SPLIT = re.compile("[\u0361\u035C]")


def _phone_cores(ipa: str) -> list:
    """Base (consonant/vowel) letters of an IPA value, tie bars and all diacritic
    marks, aspiration/glide/length modifiers and superscript prenasals removed."""
    s = tie_affricates(ipa)
    s = "".join(ch for ch in s if unicodedata.category(ch) not in _SKIP_CATEGORIES)
    return [
        ch
        for part in _TIE_SPLIT.split(s)
        for ch in part
        if unicodedata.category(ch) in ("Ll", "Lo")
    ]


def _is_single_phoneme(ipa: str) -> bool:
    cores = _phone_cores(ipa)
    if len(cores) > 2:
        return False
    if len(cores) < 2:
        return True
    return cores[0] not in _VOWELS and cores[1] not in _VOWELS


def _readable_grapheme(g: str) -> bool:
    """A reading grapheme of the universal orthography must not start with a vowel
    followed by a consonant letter. Gemini transliterates nasal vowels as <Vn>
    ("an", "on", "in"...) — fine for writing, but as reading keys they would swallow
    ordinary word-initial segments ("onyankopon" -> /õ.../). Vowel digraphs ("aa",
    "ei") stay: they only match genuinely adjacent vowels."""
    if len(g) < 2 or g[0] not in _VOWELS:
        return True
    return not any(ch not in _VOWELS for ch in g[1:])


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
                _universal_reverse.setdefault(ipa, v["grapheme"])
                if _is_single_phoneme(raw_ipa) and _readable_grapheme(v["grapheme"]):
                    _universal_forward.setdefault(v["grapheme"], ipa)
    return _universal_forward, _universal_reverse


def _universal_g2p_engine() -> G2P:
    """G2P engine that reads the virtual universal orthography back to IPA."""
    global _universal_g2p
    if _universal_g2p is None:
        forward, _ = _universal_tables()
        _universal_g2p = G2P.from_rules({"code": UNIVERSAL, "graphemes": forward})
    return _universal_g2p


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

    def __init__(self, source: str, target: str, *, relax_aspiration: bool = True):
        """
        Args:
            source: ISO 639-3 code of the input language, or "universal" to read the
                    majority grapheme set.
            target: ISO 639-3 code of the output language, or "universal" to write
                    every phoneme with the grapheme most languages use.
            relax_aspiration: when a source phoneme has no writing in the target (e.g.
                    aspirated /tʰ/ where the target only spells plain /t/), drop the
                    aspiration mark and map the plain phoneme instead — /tɕʰ/ writes
                    like /tɕ/, /kʰ/ like /k/. Exact target readings always win when the
                    target does mark aspiration. Default True.
        """
        forward, reverse = _universal_tables()
        self.source = source
        self.target = target
        self.relax_aspiration = relax_aspiration
        # Forward engine: language graphemes -> IPA (or majority graphemes -> IPA).
        if source == UNIVERSAL:
            self._forward = G2P.from_rules({"code": UNIVERSAL, "graphemes": forward})
        else:
            self._forward = G2P(source, output="ipa")
        # Reverse table: IPA -> target graphemes.
        self._reverse = reverse if target == UNIVERSAL else reverse_table(target)
        self._universal_reverse = reverse
        # Source's own spelling per phoneme -> flag when a target differs, so a
        # converted phoneme that lands next to the same letter can be tripled.
        self._source_spelling = {} if source == UNIVERSAL else reverse_table(source)

    def convert(self, text: str, *, sep: str = "", lower: bool = True) -> str:
        """Convert a full text. Word boundaries (spacing and punctuation) are always
        preserved; `sep` joins the phoneme units *within* a word — so the default
        ``sep=""`` emits continuous text, while ``sep=" "`` prints every unit as a
        separate token (the phoneme-sequence view)."""
        text = normalize_text(text, lower=lower)
        out: list = []
        for tok in tokenize(text):
            if not tok.is_word or _is_english_word(tok.text):
                out.append(tok.text)
                continue
            units = self._forward.convert_word(tok.text, sep=" ", lower=False).split(" ")
            out.append(sep.join(self._map_units(units)))
        return "".join(out)

    def convert_word(self, word: str, *, sep: str = "", lower: bool = True) -> str:
        """Convert a single word (no tokenization)."""
        if _is_english_word(word):
            return word
        word = normalize_text(word, lower=lower)
        units = self._forward.convert_word(word, sep=" ", lower=False).split(" ")
        return sep.join(self._map_units(units))

    def _map_units(self, units: list) -> list:
        """Map each phoneme to a target grapheme, replacing the existing (preceding)
        vowel in a conversion collision (between different source phonemes) with its
        closest alternative (e.g. o -> u) while keeping true source doubles (long
        vowels like hyɛɛ -> hyee) and converted vowels untouched."""
        mapped: list = []
        prev_g, prev_ipa, run_converted = None, None, False
        for ipa in units:
            g, converted = self._map(ipa)
            if converted and len(g) >= 2 and len(set(g)) == 1 and g[0] in _VOWELS:
                alt = _VOWEL_ALTERNATIVES.get(g[0], "u" if g[0] in "oɔ" else "i")
                g = alt + g[0]
            # Only collide if it's the same target grapheme AND different source phonemes
            # (so true source doubles like hyɛɛ -> hyee are left as double ee, not ii/etc.)
            is_different_phoneme_collision = (g == prev_g and ipa != prev_ipa)
            if is_different_phoneme_collision and g and g[0] in _VOWELS:
                if mapped and mapped[-1] and mapped[-1][-1] in _VOWELS:
                    last_v = mapped[-1][-1]
                    alt = _VOWEL_ALTERNATIVES.get(last_v, "u" if last_v in "oɔ" else "i")
                    mapped[-1] = mapped[-1][:-1] + alt
                mapped.append(g)
                run_converted = True
            else:
                if g != prev_g:
                    prev_g, prev_ipa, run_converted = g, ipa, converted
                    mapped.append(g)
                else:
                    mapped.append(g)
                    prev_ipa = ipa
                    run_converted = run_converted or converted
        return mapped

    def _map(self, ipa: str) -> tuple:
        """Return (grapheme, converted). `converted` is True when the target writes
        this phoneme differently from the source's own spelling (or the source has no
        spelling for it), i.e. a merge/simplification actually happened."""
        # 1) a real-language target's own writing: exact reading first (a target that
        #    spells /tʰ/ as <th> still wins), aspiration-relaxed as its fallback (a
        #    target with no /tʰ/ at all uses its /t/ reading). For the virtual
        #    "universal" target this step is identical to the majority step below.
        relaxed = _relax_aspiration(ipa) if self.relax_aspiration else ipa
        if self.target != UNIVERSAL:
            for form in (ipa, relaxed):
                g = self._reverse.get(form)
                if g is not None:
                    break
            else:
                g = None
        else:
            g = None
        if g is None:
            # 2) the majority grapheme set. Rare aspirated phonemes win their vote by
            #    tiny samples (e.g. /tɕʰ/ is written <q> by just 3 languages), so prefer
            #    the relaxed, plain-phoneme majority (/tɕʰ/ reads like the /tɕ/ winner)
            #    and keep the exact entry only as a last resort.
            for form in (relaxed, ipa):
                g = self._universal_reverse.get(form)
                if g is not None:
                    break
            else:
                g = None
        # 3) unmappable: pass the IPA unit through untouched.
        if g is None:
            return ipa, False
        if not self._source_spelling:
            return g, False
        src = self._source_spelling.get(tie_affricates(ipa))
        return g, src != g


def convert_lang(text: str, source: str, target: str, *, sep: str = "") -> str:
    """One-shot converter: ``convert_lang("Onyankopɔn", "twi", "ewe")``. Words are
    kept whole by default; pass ``sep=" "`` for per-unit (phoneme-sequence) output."""
    return GraphemeConverter(source, target).convert(text, sep=sep)


def convert_to_ipa(text: str, source: str, *, sep: str = "") -> str:
    """G2U2P pipeline: a language's graphemes -> universal graphemes -> IPA.

    Writes the source in the universal majority-grapheme set first, then reads that
    back to IPA, so every language phonemicizes along the same curated conventions
    (Gemini-normalised spellings and aspiration relaxation included). Lossy by design:
    two phonemes the universal set writes alike (e.g. /ɔ/ and /o/ both <o>) read back
    as the single winner phoneme. ``sep=" "`` prints per-unit phonemes; the default
    ``sep=""`` emits continuous IPA."""
    universal = GraphemeConverter(source, UNIVERSAL).convert(text)
    return _universal_g2p_engine().convert(universal, sep=sep)