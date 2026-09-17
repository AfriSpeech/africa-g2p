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
import warnings
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

# Virtual language code: the same idea, but injective per language, so the text
# can be read back into the original orthography.
#
# The two exist separately because they want opposite things. UNIVERSAL spells a
# sound the way most languages spell it, which makes text from different
# languages directly comparable and is what a shared column across a corpus
# wants -- and it is lossy, because Twi /o/ and /ɔ/ both land on "o". Recovering
# the orthography means those two must differ, and that spelling can only be
# chosen per language, so the result is no longer comparable across languages:
# Twi writes /ɔ/ "ohh" and Ewe writes it "oh", each avoiding sequences its own
# corpus already uses. Collapsing both behaviours into one target would have
# forced every caller to take the per-language spellings.
UNIVERSAL_REVERSIBLE = "universal-reversible"

#: Both virtual targets, for membership checks.
_VIRTUAL = (UNIVERSAL, UNIVERSAL_REVERSIBLE)

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
# When two different phonemes land on the same target vowel, the earlier one is
# rewritten to a near neighbour so the pair stays distinguishable. For a real
# language target the neighbour may be any vowel that language writes; for the
# universal orthography it has to be a plain letter, and "a" -> "ə" was putting a
# schwa into output that is supposed to be a-z only ("náań" -> "nəan").
_UNIVERSAL_VOWEL_ALTERNATIVES = {"o": "u", "u": "o", "e": "i", "i": "e",
                                 "ɔ": "u", "ɛ": "i", "a": "e", "ə": "a"}

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


# The universal orthography is plain a-z letters, enforced in the data file itself
# (see meta.revision there). Apostrophes marking ejectives, punctuation, placeholder
# tokens and non-Latin script winners were all removed at the source, because a
# speech synthesiser reads them as pauses or skips them: Xhosa "ukuba nikwazi
# ukucalula" used to be written "uk'uba nik'wazi uk'ucalula".
#
# Nothing rewrites graphemes at load time any more. What remains is a guard: if the
# table ever ships a grapheme that is not plain letters again, callers are told
# rather than finding out from the audio.
_PLACEHOLDER_GRAPHEMES = {"VV", "V", "C", "CC"}
# Phonemes the universal orthography deliberately does not write.
_UNWRITTEN = {"∅", "ʔ∅", "ʔ", "ː"}


def _strip_combining(text: str) -> str:
    """Reduce a phoneme to its base letters for a last-resort lookup.

    Drops combining marks and the modifier letters and symbols that ride on a
    phoneme — tone bars (˥ ˦ ˧), pharyngealisation (ˤ), velarisation (ˠ) — none of
    which the universal orthography writes:

        "ɔ́" -> "ɔ"    "h̃" -> "h"    "ɔ˥" -> "ɔ"    "əˤ" -> "ə"

    Only reached when the full unit is unmapped, so a base-letter match is always
    better than what it replaces: passing the symbol through into the text.
    """
    return "".join(ch for ch in unicodedata.normalize("NFD", text)
                   if not unicodedata.combining(ch)
                   and unicodedata.category(ch) not in ("Lm", "Sk"))


def _is_plain_latin(grapheme: str) -> bool:
    return bool(grapheme) and all("a" <= ch <= "z" for ch in grapheme.lower())


def _is_usable(grapheme: str) -> bool:
    return _is_plain_latin(grapheme) and grapheme not in _PLACEHOLDER_GRAPHEMES


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
            grapheme = v["grapheme"]
            # An empty grapheme is deliberate, not missing: the glottal stop and the
            # null phoneme are written as nothing. They must still enter the reverse
            # table, or the phoneme falls through as unknown and the raw IPA symbol
            # lands in the text ("dunmanʔn"). Nothing enters the forward table — an
            # empty string is not readable back.
            if grapheme:
                _universal_reverse.setdefault(ipa, grapheme)
                if _is_single_phoneme(raw_ipa) and _readable_grapheme(grapheme):
                    _universal_forward.setdefault(grapheme, ipa)
            elif "grapheme_note" in v or raw_ipa in _UNWRITTEN:
                _universal_reverse.setdefault(ipa, "")
        _warn_non_alphabetic(_universal_reverse)
    return _universal_forward, _universal_reverse


def universal_non_alphabetic() -> Dict[str, str]:
    """IPA -> universal grapheme, for every grapheme still holding a non a-z character.

    The universal orthography is supposed to be plain letters. Where the survey had
    no plain-Latin vote for a phoneme at all — the bilabial clicks of the Khoisan
    languages are the main case — the original symbol is kept rather than
    approximated by a letter the language does not use or dropped from the
    transcript. Callers feeding a speech synthesiser should know which those are.
    """
    _, reverse = _universal_tables()
    return {ipa: g for ipa, g in reverse.items() if g and not _is_usable(g)}


def _warn_non_alphabetic(reverse: Dict[str, str]) -> None:
    """Warn once that some universal graphemes are not plain letters."""
    # An empty grapheme is a deliberate "written as nothing", not a bad spelling.
    offenders = {ipa: g for ipa, g in reverse.items() if g and not _is_usable(g)}
    if not offenders:
        return
    sample = ", ".join(f"{ipa} -> {g}" for ipa, g in list(offenders.items())[:5])
    warnings.warn(
        f"{len(offenders)} universal graphemes are not plain a-z letters ({sample}"
        f"{', ...' if len(offenders) > 5 else ''}). No plain-Latin spelling was "
        f"attested for these phonemes. Text-to-speech will usually skip them; call "
        f"africa_g2p.convert.universal_non_alphabetic() for the full list.",
        UserWarning,
        stacklevel=2,
    )


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



# --- plain-Latin orthographies -------------------------------------------------
# A language whose orthography uses only the 26 basic Latin letters already *is*
# written in the universal grapheme set: every letter maps to itself, so routing
# it through IPA and back can only introduce noise. For those languages the
# universal form is the text as written.
#
# An apostrophe does not disqualify a language. It marks glottalisation or
# elision in several orthographies and carries no grapheme of its own, so it is
# simply dropped from the universal form.

_APOSTROPHES = "'\u2019\u2018\u02bc\u02bb`"


def _is_plain_latin(alphabet) -> bool:
    """True when every grapheme is made only of basic a-z (apostrophes ignored)."""
    seen = False
    for g in alphabet or ():
        for ch in unicodedata.normalize("NFD", str(g)):
            if ch in _APOSTROPHES or not ch.strip():
                continue
            if not ("a" <= ch.lower() <= "z"):
                return False
            seen = True
    return seen


_PLAIN_LATIN_FILE = _DATA / "plain_latin_languages.json"
_plain_latin_registry: "Dict[str, dict] | None" = None


def plain_latin_languages() -> Dict[str, dict]:
    """Languages recorded as writing in basic Latin only, with no rule table.

    These have a corpus but no grapheme-to-IPA chart. A table is not needed for
    universal output — the orthography already is the universal grapheme set —
    so they are declared here rather than given a rule file asserting phonetic
    values nobody has verified.
    """
    global _plain_latin_registry
    if _plain_latin_registry is None:
        if _PLAIN_LATIN_FILE.exists():
            with _PLAIN_LATIN_FILE.open(encoding="utf-8") as fh:
                _plain_latin_registry = json.load(fh)
        else:
            _plain_latin_registry = {}
    return _plain_latin_registry


def is_plain_latin_language(code: str) -> bool:
    """True when ``code``'s orthography needs no conversion for universal output."""
    if code in plain_latin_languages():
        return True
    try:
        rules = load_rules(code)
    except Exception:
        return False
    alphabet = rules.get("alphabet") or rules.get("graphemes") or {}
    if isinstance(alphabet, dict):
        alphabet = list(alphabet)
    return _is_plain_latin(alphabet)


def strip_apostrophes(text: str) -> str:
    """Remove apostrophes, which the universal orthography does not write."""
    return "".join(ch for ch in text if ch not in _APOSTROPHES)




# --- stored per-language universal tables ---------------------------------------
# A language's grapheme -> universal mapping was always language-specific (532
# graphemes take different universal values in different languages), but it was
# not injective: Twi wrote both `e` and `ɛ` as `e`, so the universal form could
# not be turned back. Each language now stores an injective mapping and its
# inverse, built by scripts/build_reversible_universal.py.

def stored_universal(code: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """(grapheme -> universal, universal -> grapheme) for ``code``, or two empties."""
    try:
        rules = load_rules(code)
    except Exception:
        return {}, {}
    return rules.get("universal") or {}, rules.get("universal_reverse") or {}


def _greedy_units(text: str, table: Dict[str, str]) -> list:
    """Rewrite text with the longest matching key at each position, one unit per
    grapheme matched, so a caller can join them with its own separator."""
    if not table:
        return [text]
    keys = sorted(table, key=len, reverse=True)
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch.isspace() or unicodedata.category(ch).startswith("P") or ch.isdigit():
            out.append(ch)
            i += 1
            continue
        for k in keys:
            if k and text.startswith(k, i):
                out.append(table[k])
                i += len(k)
                break
        else:
            out.append(ch)
            i += 1
    return out


def _greedy_map(text: str, table: Dict[str, str]) -> str:
    """Rewrite text with the longest matching key at each position."""
    return "".join(_greedy_units(text, table))


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
        # A plain-Latin orthography already writes the universal graphemes, in
        # either direction: its universal form is the text itself.
        self.passthrough = (
            (target in _VIRTUAL and source not in _VIRTUAL
             and is_plain_latin_language(source))
            or (source in _VIRTUAL and target not in _VIRTUAL
                and is_plain_latin_language(target)))

        # Stored injective tables, for the reversible target only. Using them for
        # plain UNIVERSAL too would have given every caller the per-language
        # spellings and broken cross-language comparability.
        self._stored_fwd: Dict[str, str] = {}
        self._stored_rev: Dict[str, str] = {}
        if not self.passthrough:
            if target == UNIVERSAL_REVERSIBLE and source not in _VIRTUAL:
                self._stored_fwd, _ = stored_universal(source)
            elif source == UNIVERSAL_REVERSIBLE and target not in _VIRTUAL:
                _, self._stored_rev = stored_universal(target)
        # Forward engine: language graphemes -> IPA (or majority graphemes -> IPA).
        # Skipped entirely when passing through: a plain-Latin orthography needs
        # no phoneme round-trip, and such a table may assert no IPA at all.
        if self.passthrough:
            self._forward = None
        elif source in _VIRTUAL:
            self._forward = G2P.from_rules({"code": UNIVERSAL, "graphemes": forward})
        else:
            self._forward = G2P(source, output="ipa")
        # Reverse table: IPA -> target graphemes.
        self._reverse = reverse if target in _VIRTUAL else reverse_table(target)
        self._universal_reverse = reverse
        # Source's own spelling per phoneme -> flag when a target differs, so a
        # converted phoneme that lands next to the same letter can be tripled.
        # Both are unused when passing through, and a plain-Latin language may
        # have no rule file to read them from.
        if self.passthrough or source in _VIRTUAL:
            self._source_spelling = {}
        else:
            self._source_spelling = reverse_table(source)

    def convert(self, text: str, *, sep: str = "", lower: bool = True) -> str:
        """Convert a full text. Word boundaries (spacing and punctuation) are always
        preserved; `sep` joins the phoneme units *within* a word — so the default
        ``sep=""`` emits continuous text, while ``sep=" "`` prints every unit as a
        separate token (the phoneme-sequence view)."""
        text = normalize_text(text, lower=lower)
        if self.passthrough:
            return strip_apostrophes(text)
        # The stored table still goes through tokenization. Running it over the
        # whole string skipped the English check (so "great" came back "greath")
        # and ignored `sep` entirely, since there was nothing to join.
        stored = self._stored_fwd or self._stored_rev
        out: list = []
        for tok in tokenize(text):
            # The English skip is for plain UNIVERSAL, where a loanword is worth
            # keeping legible. The reversible target must not use it: conversion
            # can turn a native word into an English one -- Dagbani <o> spells
            # "ooh" -- and the reverse pass would then skip the token it was
            # supposed to convert. Treating loanwords as ordinary text instead is
            # symmetric, so they still survive the round trip.
            skip_english = not stored
            if not tok.is_word or (skip_english and _is_english_word(tok.text)):
                out.append(tok.text)
                continue
            if stored:
                out.append(sep.join(_greedy_units(tok.text, stored)))
                continue
            units = self._forward.convert_word(tok.text, sep=" ", lower=False).split(" ")
            out.append(sep.join(self._map_units(units)))
        return "".join(out)

    def convert_word(self, word: str, *, sep: str = "", lower: bool = True) -> str:
        """Convert a single word (no tokenization)."""
        if self.passthrough:
            return strip_apostrophes(normalize_text(word, lower=lower))
        stored = self._stored_fwd or self._stored_rev
        if not stored and _is_english_word(word):
            return word
        word = normalize_text(word, lower=lower)
        if stored:
            return sep.join(_greedy_units(word, stored))
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
            alternatives = (_UNIVERSAL_VOWEL_ALTERNATIVES if self.target in _VIRTUAL
                            else _VOWEL_ALTERNATIVES)
            if converted and len(g) >= 2 and len(set(g)) == 1 and g[0] in _VOWELS:
                alt = alternatives.get(g[0], "u" if g[0] in "oɔ" else "i")
                g = alt + g[0]
            # Only collide if it's the same target grapheme AND different source phonemes
            # (so true source doubles like hyɛɛ -> hyee are left as double ee, not ii/etc.)
            is_different_phoneme_collision = (g == prev_g and ipa != prev_ipa)
            if is_different_phoneme_collision and g and g[0] in _VOWELS:
                if mapped and mapped[-1] and mapped[-1][-1] in _VOWELS:
                    last_v = mapped[-1][-1]
                    alt = alternatives.get(last_v, "u" if last_v in "oɔ" else "i")
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
        if self.target not in _VIRTUAL:
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
        # 3) a tone-marked or nasalised variant of a phoneme the table does know.
        #    Source orthographies write tone on the vowel ("lɔ́lɔndai", "ɣɛ́i"), and the
        #    accented form is absent from the survey, so it used to fall through to
        #    step 4 — leaving a bare ɔ or ɛ in universal output once normalisation
        #    stripped the accent, which is exactly the character universal exists to
        #    remove. Retry on the base letter, keeping the mark off: the universal
        #    orthography does not write tone.
        if g is None and self.target in _VIRTUAL:
            base = _strip_combining(ipa)
            # A unit that is nothing but modifiers — a lone tone bar or ˤ emitted as
            # its own unit — writes as nothing, the same as the other phonemes the
            # universal orthography does not mark.
            if ipa and not base:
                return "", True
            if base and base != ipa:
                for form in (base, _strip_combining(relaxed)):
                    g = self._universal_reverse.get(form)
                    if g is not None:
                        break
                else:
                    g = None

        # 4) unmappable: pass the IPA unit through untouched.
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