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
from typing import Dict, List, Tuple
from functools import lru_cache

from .g2p import G2P
from .loader import load_rules, LanguageNotFoundError
from .normalizer import normalize_text, tie_affricates, tokenize

_DATA = Path(__file__).resolve().parent / "data"
_FALLBACK_FILE = _DATA / "universal_fallback.json"
_ESCAPES_FILE = _DATA / "proxy_escapes.json"
_UNIVERSAL_FILE = _DATA / "ipa_universal_graphemes.json"

# Virtual language code: "write every phoneme with the grapheme most languages use".
UNIVERSAL = "universal"

# Virtual language code: a per-language alphabet that reads back.
#
# `universal` writes each sound the way most languages write it, which is what
# makes text from different languages comparable, and is lossy on purpose --
# Twi writes both /o/ and /ɔ/ as "o". A proxy alphabet is the same idea made
# reversible for one language: it starts from the universal spelling and moves
# a grapheme off it only where reversibility demands, so Twi writes /ɔ/ "ox"
# while Ewe writes it "oh". Comparable across languages or reversible within
# one -- no single spelling can be both, which is why these are two targets.
PROXY = "proxy"

_VIRTUAL = (UNIVERSAL, PROXY)

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

# U+A78C SALTILLO is a letter, not punctuation, but orthographies use it exactly
# as an apostrophe (Beja writes ꞌ where others write '), so it goes too.
_APOSTROPHES = "'\u2019\u2018\u02bc\u02bb`\ua78c\ua78b"


def _alphabet_is_plain_latin(alphabet) -> bool:
    """True when every grapheme in an alphabet is basic a-z (apostrophes ignored).

    Distinct from the grapheme-level ``_is_plain_latin`` defined above, which
    gates entry to the universal tables and does not tolerate apostrophes.
    """
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
    return _alphabet_is_plain_latin(alphabet)


@lru_cache(maxsize=1)
def _fallback() -> Tuple[Dict[str, str], frozenset]:
    """How the corpus as a whole writes a letter, for tables that omit it.

    A letter a language's own table does not list used to survive into universal
    output verbatim, so universal text came back with ŋ, ɔ, ɛ and ʃ still in it.
    Every other table is evidence for how to write it: ŋ is spelt ng by 346 of
    them, ɔ is spelt o by 295. One table's opinion is not a consensus, so a
    spelling needs a quorum before it is used here.
    """
    try:
        d = json.loads(_FALLBACK_FILE.read_text(encoding="utf-8"))
        return d.get("spell", {}), frozenset(d.get("drop", []))
    except Exception:
        return {}, frozenset()


def universal_fallback(ch: str) -> str | None:
    """Spelling for a single letter no table of this language covers."""
    spell, drop = _fallback()
    if ch in drop:
        return ""
    return spell.get(ch)


# Typographic punctuation that has a plain ASCII equivalent. Universal output is
# meant to be plain a-z with ordinary punctuation, and these are the same marks
# in fancier clothing: a hundred corpora write « » where ASCII writes ", and two
# dozen use a non-breaking hyphen. Proxy must not fold them -- it has to give
# back exactly what came in -- so this belongs to the universal path only.
_ASCII_PUNCT = {
    "\u00ab": '"', "\u00bb": '"', "\u2039": "'", "\u203a": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2018": "'", "\u2019": "'",
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u2015": "-", "\u2212": "-", "\u00a0": " ", "\u2007": " ", "\u202f": " ",
    "\u2026": "...", "\u00b7": ".", "\u2022": ".", "\uff0c": ",", "\uff0e": ".",
    "\u061b": ";", "\u061f": "?", "\u060c": ",", "\u061e": ".", "\u06d4": ".",
    "\u2044": "/", "\u00d7": "x", "\u2032": "'", "\u2033": '"',
    "\u201a": "'", "\u201b": "'", "\u00bf": "?", "\u00a1": "!",
    "\u2035": "'", "\u2036": '"', "\u00ba": "o", "\u00aa": "a",
}


def _apply_fallback(text: str) -> str:
    """Spell any leftover non a-z character the way most tables spell it.

    Everything outside ASCII is handled, not only letters. An IPA unit the
    survey has no spelling for passes through whole, tie bar and all, and a
    combining tie bar is a mark rather than a letter -- so "ntsaa" came out
    "n͡t͡saa" and the checks for plain a-z output never saw it, because they
    asked isalpha(). A mark that carries no sound of its own is dropped; a
    character with a spelling takes it.
    """
    spell, drop = _fallback()
    if not spell:
        return text
    out = []
    for ch in text:
        if ch in drop:
            continue
        if ord(ch) < 128:
            out.append(ch)
            continue
        if ch in spell:
            out.append(spell[ch])
        elif ch in _ASCII_PUNCT:
            out.append(_ASCII_PUNCT[ch])
        elif not ch.isalpha():
            # Anything left that is not a letter -- a tie bar, undertie, tone
            # bar, modifier, invisible formatting character, dagger,
            # private-use or control character -- is written as nothing.
            # Universal output is plain ASCII and such a mark has no ASCII
            # equivalent to fall back on. A letter is kept instead, so a gap
            # in the tables shows up rather than silently deleting words.
            continue
        else:
            out.append(ch)
    return "".join(out)


def _nfc(s: str) -> str:
    """Recompose. Matching runs decomposed, but callers and the normalizer work
    in NFC -- emitting decomposed text made every accented language compare
    unequal to its own source and looked like a system-wide collapse."""
    return unicodedata.normalize("NFC", s)


def _greedy_units(text: str, table: Dict[str, str]) -> list:
    """Rewrite text with the longest matching key at each position, one unit per
    grapheme matched, so a caller can join them with its own separator.

    Text and keys are both compared decomposed, longest key first, and any
    combining marks trailing a match ride along to the end of its replacement.

    Decomposing is what makes that safe. Ngomba /ɑ̂/ spells "ah" plus a
    combining circumflex, and NFC fuses the mark with the "h" into ĥ (U+0125);
    matching the composed text, the reverse key "ah" could never match it again.
    Acute survived only because Unicode has no precomposed "h with acute", which
    is why one word round-tripped with one accent and not another. Decomposed,
    ĥ is h plus a mark again and the key matches as written.

    Matching stays exact. Letting a key match across marks instead -- so that
    "ah" could find a-circumflex-h -- let long keys swallow accents belonging to
    a language's own accented graphemes, and cost more languages than it fixed.
    """
    if not table:
        return [text]
    nfd = {unicodedata.normalize("NFD", k): v for k, v in table.items()}
    # Longest first; at equal length an accented grapheme of the language's own
    # chart beats a bare one, so Avokaya ị is read as ị, not i plus a mark.
    keys = sorted(nfd, key=lambda k: (len(k),
                                      any(unicodedata.combining(c) for c in k)),
                  reverse=True)
    flat = unicodedata.normalize("NFD", text)

    out, i = [], 0
    while i < len(flat):
        ch = flat[i]
        if ch.isspace() or unicodedata.category(ch).startswith("P") or ch.isdigit():
            out.append(_nfc(ch))
            i += 1
            continue
        for k in keys:
            if k and flat.startswith(k, i):
                j = i + len(k)
                break
        else:
            k, j = None, i + 1
        held = ""
        while j < len(flat) and unicodedata.combining(flat[j]):
            # A mark the table gives a letter for becomes that letter, so the
            # output stays inside a-z. A marked letter the corpus actually uses
            # is a table key in its own right and never reaches here.
            held += nfd.get(flat[j], flat[j])
            j += 1
        out.append(_nfc((nfd[k] if k is not None else ch) + held))
        i = j
    return out


def _greedy_map(text: str, table: Dict[str, str]) -> str:
    """Rewrite text with the longest matching key at each position."""
    return "".join(_greedy_units(text, table))


def proxy_tables(code: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """(grapheme -> proxy, proxy -> grapheme) for ``code``, or two empties.

    The forward table carries the combining marks as keys of their own, so a
    marked letter the corpus never showed still comes out as letters rather
    than as a stray accent.
    """
    try:
        rules = load_rules(code)
    except Exception:
        return {}, {}
    fwd = dict(rules.get("proxy") or {})
    if fwd:
        fwd.update(rules.get("proxy_marks") or {})
    return fwd, rules.get("proxy_reverse") or {}


def proxy_supported(code: str) -> bool:
    """True when ``code`` has a proxy alphabet to convert through."""
    fwd, rev = proxy_tables(code)
    return bool(fwd and rev)


def _non_latin_script(ch: str) -> bool:
    o = ord(ch)
    return (0x1200 <= o <= 0x137F or 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F
            or 0x08A0 <= o <= 0x08FF or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF
            or 0xA500 <= o <= 0xA63F or 0x07C0 <= o <= 0x07FF
            or 0x2D30 <= o <= 0x2D7F or 0x0400 <= o <= 0x04FF
            or 0x2C80 <= o <= 0x2CFF or 0x1360 <= o <= 0x137F)


def _romanise(text: str) -> str:
    """Write a non-Latin script in Latin, from the baked uroman table.

    Deriving a whole script from our own rule tables produced a romanisation
    nobody uses -- Amharic ክርስቶስ came out "kirisitosi" -- and a chart that
    lists Ethiopic graphemes never reached the fallback at all, so the table
    alone did not change what those languages emitted. A token written in a
    non-Latin script is romanised here instead of going through the chart.
    """
    spell, drop = _fallback()
    out = []
    for ch in text:
        if ch in drop:
            continue
        if _non_latin_script(ch):
            out.append(spell.get(ch, ch))
        else:
            out.append(ch)
    return "".join(out)


@lru_cache(maxsize=1)
def _escapes() -> Tuple[Dict[str, str], Dict[str, str]]:
    """(character -> payload, payload -> character) for the proxy alphabet."""
    try:
        d = json.loads(_ESCAPES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    fwd = d.get("payloads", {})
    return fwd, {v: k for k, v in fwd.items()}


# No "x": it ends an escape, and a payload containing one was cut short --
# the Vai syllable ꘋ encoded as "zzckwx" and came back as ٢.
_B25 = "abcdefghijklmnopqrstuvwyz"


def _codepoint_payload(ch: str) -> str:
    """"zz" plus the codepoint in base 26, for a character with no entry."""
    n, out = ord(ch), ""
    while n:
        out = _B25[n % 25] + out
        n //= 25
    return "zz" + (out or "a")


def _payload_codepoint(payload: str) -> str | None:
    if not payload.startswith("zz") or len(payload) < 3:
        return None
    n = 0
    for c in payload[2:]:
        if c not in _B25:
            return None
        n = n * 25 + _B25.index(c)
    try:
        return chr(n)
    except ValueError:
        return None


def to_proxy(text: str) -> str:
    """Write text in the proxy alphabet: plain a-z, and exactly reversible.

    An a-z letter stands for itself, a literal x doubles to xx, and anything
    else is written x<payload>x -- ɔ is xox, ŋ is xngx, a combining acute is
    xqx. The code is decodable by construction, so this needs no per-language
    table and cannot fail on a language: the earlier per-language version had
    to check every spelling for collisions and still left 175 languages short
    of a clean round trip.
    """
    fwd, _ = _escapes()
    out = []
    for ch in unicodedata.normalize("NFD", text):
        if ch == "x":
            # before the a-z test, which would otherwise pass x through and
            # leave a real x indistinguishable from the start of an escape
            out.append("xx")
        elif "a" <= ch <= "z":
            out.append(ch)
        elif ch in fwd:
            out.append("x" + fwd[ch] + "x")
        elif ord(ch) < 128 and not ch.isalpha():
            # ASCII spaces, digits and punctuation carry through as themselves.
            # Anything outside ASCII is escaped even when it is punctuation: a
            # guillemet is not a-z either, and proxy cannot fold it to a quote
            # the way universal does, because it has to give back what came in.
            out.append(ch)
        else:
            # No entry: encode the codepoint itself, so a letter nobody
            # tabulated still round-trips. The Vai syllable ꘋ appears in real
            # text and in no rule table, and used to pass through as itself.
            out.append("x" + _codepoint_payload(ch) + "x")
    return "".join(out)


def from_proxy(text: str) -> str:
    """Read proxy text back into the original orthography."""
    _, rev = _escapes()
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch != "x":
            out.append(ch)
            i += 1
            continue
        if text.startswith("xx", i):
            out.append("x")
            i += 2
            continue
        j = text.find("x", i + 1)
        if j == -1:
            out.append(ch)
            i += 1
            continue
        payload = text[i + 1:j]
        ch = rev.get(payload) or _payload_codepoint(payload)
        out.append(ch if ch is not None else payload)
        i = j + 1
    return unicodedata.normalize("NFC", "".join(out))


def strip_apostrophes(text: str) -> str:
    """Remove apostrophes, which the universal orthography does not write."""
    return "".join(ch for ch in text if ch not in _APOSTROPHES)


def _drop_marks(text: str) -> str:
    """Drop combining marks, which the universal orthography does not write.

    A language whose declared alphabet is plain a-z is passed through unchanged,
    but several write tone on top of it -- Bokyi and Bwamu mark é í á ú -- and
    those accents reached universal output verbatim. The chart path already
    drops them (a tone-marked phoneme falls back to its base letter), so this
    only makes passthrough agree with it.
    """
    return unicodedata.normalize(
        "NFC", "".join(ch for ch in unicodedata.normalize("NFD", text)
                       if not unicodedata.combining(ch)))


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
        # A plain-Latin orthography already writes the universal graphemes.
        self.passthrough = (target == UNIVERSAL and source != UNIVERSAL
                            and is_plain_latin_language(source))
        # Proxy is one global escape scheme rather than a per-language table,
        # so there is nothing to look up and no language it can fail on.
        self._to_proxy = target == PROXY and source != PROXY
        self._from_proxy = source == PROXY and target != PROXY
        # Forward engine: language graphemes -> IPA (or majority graphemes -> IPA).
        # Skipped entirely when passing through: a plain-Latin orthography needs
        # no phoneme round-trip, and such a table may assert no IPA at all.
        if self.passthrough or self._to_proxy or self._from_proxy:
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
            return _apply_fallback(strip_apostrophes(_drop_marks(text)))
        if self._to_proxy:
            return to_proxy(text)
        if self._from_proxy:
            return from_proxy(text)
        stored = None
        out: list = []
        for tok in tokenize(text):
            # The English skip keeps a loanword legible in universal. A proxy
            # alphabet cannot use it: converting can turn a native word into an
            # English one, and the reverse pass would then skip the very token
            # it had to convert. Treating loanwords as ordinary text is
            # symmetric, so they still come back unchanged.
            if not tok.is_word or (not stored and _is_english_word(tok.text)):
                out.append(tok.text)
                continue
            if stored:
                # Recompose the word: a mark letter turns back into a combining
                # mark, which has to settle onto the letter before it.
                out.append(_nfc(sep.join(_greedy_units(tok.text, stored))))
                continue
            if self.target == UNIVERSAL and any(_non_latin_script(c) for c in tok.text):
                out.append(_romanise(tok.text))
                continue
            units = self._forward.convert_word(tok.text, sep=" ", lower=False).split(" ")
            out.append(sep.join(self._map_units(units)))
        result = "".join(out)
        # The universal orthography does not write apostrophes, and a word-initial
        # one is punctuation to the tokenizer, so it passed through untouched --
        # Bijwa writes many ('jäa, 'ŋlë) and they survived into universal text,
        # while the same mark at the end of a word was absorbed and dropped. No
        # universal value contains an apostrophe, so removing them here cannot
        # corrupt a mapping.
        if self.target == UNIVERSAL:
            result = _apply_fallback(strip_apostrophes(_romanise(result)))
        return result

    def convert_word(self, word: str, *, sep: str = "", lower: bool = True) -> str:
        """Convert a single word (no tokenization)."""
        if self.passthrough:
            return _apply_fallback(
                strip_apostrophes(_drop_marks(normalize_text(word, lower=lower))))
        if self._to_proxy:
            return to_proxy(normalize_text(word, lower=lower))
        if self._from_proxy:
            return from_proxy(normalize_text(word, lower=lower))
        if _is_english_word(word):
            return word
        word = normalize_text(word, lower=lower)
        units = self._forward.convert_word(word, sep=" ", lower=False).split(" ")
        out = sep.join(self._map_units(units))
        return (_apply_fallback(strip_apostrophes(out))
                if self.target == UNIVERSAL else out)

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


# --- IPA back to a language's orthography ---------------------------------------
# The universal form deliberately collapses distinctions (ɔ and o both write as
# "o"), so it cannot be reversed. IPA keeps them apart, so a language's own chart
# can map it back. Measured round-trip on corpus text: twi 60/60, bwu 60/60,
# dag 60/60, ewe 18/60 (nasalised open vowels).

def from_ipa(ipa: str, lang: str, *, unknown: str = "keep") -> str:
    """Write an IPA string in ``lang``'s orthography.

    The inverse of ``G2P(lang, output="ipa")``. Segments the IPA greedily,
    longest phoneme first, and writes each with the grapheme that language uses
    for it.

    Args:
        ipa: IPA text. Word boundaries and punctuation are preserved.
        lang: ISO 639-3 code of the language to write in.
        unknown: what to do with a phoneme the language has no grapheme for --
            "keep" leaves the IPA as-is, "drop" removes it, "mark" emits "?".

    >>> from_ipa("ɔdɔ", "twi")
    'ɔdɔ'
    """
    table = reverse_table(lang)
    if not table:
        raise LanguageNotFoundError(f"no reverse table for {lang!r}")
    keys = sorted(table, key=len, reverse=True)
    out, i = [], 0
    text = unicodedata.normalize("NFC", ipa)
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
            if unknown == "drop":
                pass
            elif unknown == "mark":
                out.append("?")
            else:
                out.append(ch)
            i += 1
    return "".join(out)


def roundtrip(text: str, lang: str) -> str:
    """Write ``text`` through IPA and back into ``lang``'s own orthography.

    Useful for checking that a language's chart is reversible: where it is, the
    output equals the lower-cased input.
    """
    return GraphemeConverter(lang, lang).convert(text)
