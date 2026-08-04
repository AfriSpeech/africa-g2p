"""Reachability of rule entries, and invariants over the rule data itself.

The repo-wide checks matter more than the per-language ones: a rule entry that can never
match is invisible in normal use — the engine silently falls back to the base letter and
produces plausible-looking output — so nothing catches it except an explicit assertion.
"""
from __future__ import annotations

import re
import unicodedata

import pytest

from africa_g2p import G2P
from africa_g2p.loader import available_languages, load_rules
from africa_g2p.normalizer import tokenize

ALL = available_languages()

# Genuine IPA codepoints that happen to be Greek letters.
LEGIT_GREEK = set("βθχ")


def composed_keys(code):
    """Rule keys containing a combining mark."""
    g = load_rules(code).get("graphemes", {})
    return {
        k: v for k, v in g.items()
        if v and any(unicodedata.combining(c) for c in unicodedata.normalize("NFD", k))
    }


# -- the systemic bug: composed keys were unreachable ----------------------

@pytest.mark.parametrize(
    "code,key,expected",
    [
        ("gur", "ẽ", "ɛ̃"),    # nasalization changes vowel quality — not a suffix
        ("acz", "ä", "ə"),
        ("ade", "ä", "ɨ"),
        ("ada", "ɛ̃", "ɛ̃"),
        ("amf", "በ፟", "ɓə"),   # Ethiopic combining mark (U+135F), outside U+0300-U+036F
    ],
)
def test_composed_key_reachable(code, key, expected):
    assert "".join(G2P(code, output="ipa").phonemes(key)) == expected


def test_composed_keys_reachable_repo_wide():
    """Rule entries that can never match are dead data — keep them near zero."""
    total = working = 0
    for code in ALL:
        try:
            g2p = G2P(code, output="ipa", unknown="mark")
        except Exception:
            continue
        for key, val in composed_keys(code).items():
            total += 1
            if "".join(g2p.phonemes(key)) == str(val):
                working += 1
    assert total > 1000, "expected a substantial number of composed keys"
    assert working / total >= 0.94, f"only {working}/{total} composed keys reachable"


def test_marks_outside_latin_block_stay_in_words():
    """Ethiopic, Arabic and Hebrew marks must not tokenize as separators."""
    for text in ("በ፟", "ጉ፟"):
        toks = tokenize(text)
        assert len(toks) == 1 and toks[0].is_word, f"{text!r} split into {toks}"


def test_leading_combining_mark_does_not_match():
    """A mark with no base must not be absorbed into a following grapheme."""
    assert G2P("twi", output="ipa").phonemes("̃a") == ["a"]


# -- rule data invariants -------------------------------------------------

def test_no_phonetic_brackets_in_values():
    bad = {
        c: {k: v for k, v in load_rules(c).get("graphemes", {}).items()
            if v and re.search(r"[\[\]]", str(v))}
        for c in ALL
    }
    bad = {c: v for c, v in bad.items() if v}
    assert not bad, f"phonetic brackets leaked into IPA values: {bad}"


def test_no_greek_lookalikes_in_values():
    bad = {}
    for c in ALL:
        for k, v in load_rules(c).get("graphemes", {}).items():
            for ch in str(v or ""):
                name = unicodedata.name(ch, "")
                if name.startswith(("GREEK", "CYRILLIC")) and ch not in LEGIT_GREEK:
                    bad.setdefault(c, {})[k] = v
    assert not bad, f"non-IPA Greek/Cyrillic lookalikes in values: {bad}"


def test_orthographic_y_is_palatal_glide():
    """IPA y is a close front rounded vowel; <y> in these orthographies is /j/."""
    bad = {c: load_rules(c)["graphemes"]["y"]
           for c in ALL
           if load_rules(c).get("graphemes", {}).get("y") == "y"}
    assert not bad, f"<y> mapped to IPA y rather than j: {bad}"


def test_twi_unaffected_by_composed_matching():
    """Regression guard: languages without composed keys must be untouched."""
    assert G2P("twi", output="ipa").phonemes("Onyankopɔn") == [
        "o", "ɲ", "a", "n", "kʰ", "o", "pʰ", "ɔ", "n",
    ]


def test_tone_still_handled_as_suprasegmental():
    """Tone marks stay suffix-mapped; only keys the rules declare are matched whole."""
    assert G2P("gur", output="ipa").phonemes("á") == ["a"]


def test_no_uppercase_letters_in_values():
    """IPA has no uppercase letters.

    Capitals in the scanned charts were three different mistakes, not one: Ɂ/Ɩ standing
    in for ʔ/ɪ, an l/I OCR confusion, and "V" used as a metavariable meaning "any vowel"
    (``VV -> Vː`` states that doubled vowels are long — it is not a grapheme mapping, and
    as a key it matched literal "vv"). The small-capital IPA symbols (ɪ ʁ ɢ) are their own
    lowercase-category codepoints and are unaffected.
    """
    bad = {}
    for c in ALL:
        for k, v in load_rules(c).get("graphemes", {}).items():
            if v and any(ch.isupper() for ch in str(v)):
                bad.setdefault(c, {})[k] = v
    assert not bad, f"uppercase letters in IPA values: {bad}"


def test_glottal_stop_uses_ipa_codepoint():
    assert G2P("any", output="ipa").phonemes("m'ɔ") == ["m", "ʔ", "ɔ"]


def test_voiced_velar_stop_uses_ipa_codepoint():
    """IPA voiced velar stop is U+0261, not ASCII g.

    norm_ipa enforces this at build time, but the Ethiopic parser bypassed it and left 99
    entries across amh, byn, gez, tig and tir spelling the same sound the other way. In a
    shared phoneme vocabulary that silently splits /ɡ/ into two tokens.
    """
    bad = {
        c: {k: v for k, v in load_rules(c).get("graphemes", {}).items()
            if v and "g" in str(v)}
        for c in ALL
    }
    bad = {c: v for c, v in bad.items() if v}
    assert not bad, f"ASCII g in IPA values: {bad}"
