"""Conventional readings for letters a rule set omits.

Alphabet charts are not always complete. Where a language's own orthography uses a letter
its chart left out, the phoneme was previously lost silently — the output still looked
plausible, which is worse than an error. These tests pin the recovery and, just as
importantly, that a language's own rules always win over the fallback.
"""
from __future__ import annotations

import pytest

from africa_g2p import G2P
from africa_g2p.fallback import FALLBACK_IPA, fallback_ipa
from africa_g2p.loader import available_languages, load_rules


def test_letter_missing_from_chart_is_recovered():
    """nko's chart has no r; Nkonya text uses it."""
    assert G2P("nko", output="ipa").phonemes("ara") == ["a", "ɾ", "a"]


def test_disabled_falls_back_to_the_old_behaviour():
    out = G2P("nko", output="ipa", fallback=False).phonemes("ara")
    assert "ɾ" not in out


def test_naw_missing_p():
    """The naw chart has no p at all, which made Nawuri largely unusable."""
    assert "p" in G2P("naw", output="ipa").phonemes("apa")


def test_language_rules_take_precedence():
    """The fallback is a last resort: a chart's own value for a letter always wins.

    dgd maps <c> to a palatal stop, not the affricate the fallback would supply.
    """
    own = load_rules("dgd")["graphemes"].get("c")
    if own:
        assert G2P("dgd", output="ipa").phonemes("c") == [own]


def test_grapheme_mode_untouched():
    """Native-orthography output must keep the written form, not an IPA substitution."""
    assert G2P("nko", output="grapheme").phonemes("ara") == ["a", "r", "a"]


def test_latin_mode_untouched():
    assert "ɾ" not in G2P("nko", output="latin").phonemes("ara")


@pytest.mark.parametrize("ch", sorted(FALLBACK_IPA))
def test_every_fallback_value_is_reachable(ch):
    """Each entry must actually be produced for some language that lacks the letter."""
    assert fallback_ipa(ch)


def test_uppercase_resolves():
    assert fallback_ipa("R") == fallback_ipa("r")


def test_no_language_regresses():
    """Adding the fallback must not change output where a chart already covers a letter."""
    probe = "abcdefghijklmnopqrstuvwxyz"
    for code in list(available_languages())[:40]:
        keys = {k.lower() for k in load_rules(code).get("graphemes", {})}
        covered = "".join(c for c in probe if c in keys)
        if not covered:
            continue
        on = G2P(code, output="ipa", fallback=True).phonemes(covered)
        off = G2P(code, output="ipa", fallback=False).phonemes(covered)
        assert on == off, code


# --------------------------------------------------------------- IPA-letter graphemes

@pytest.mark.parametrize("ch,ipa", [("ɛ", "ɛ"), ("ɔ", "ɔ"), ("ŋ", "ŋ"), ("ʋ", "ʋ"),
                                    ("ɓ", "ɓ"), ("ɗ", "ɗ"), ("ɖ", "ɖ"), ("ɩ", "ɪ")])
def test_ipa_letters_read_as_themselves(ch, ipa):
    """A chart that omits a borrowed IPA letter must not lose it: kiz has no ŋ, ɛ or ɔ."""
    assert G2P("kiz", output="ipa", unknown="mark").phonemes(ch) == [ipa]


def test_kisi_letters_no_longer_lost():
    assert "�" not in "".join(G2P("kiz", output="ipa", unknown="mark").phonemes("buŋgɛi pɛɛkɛi"))


# ------------------------------------------------------------------ dot-below letters

@pytest.mark.parametrize("word,expected", [("ọmọ", ["ɔ", "m", "ɔ"]),
                                           ("ẹgbẹ", ["ɛ", "k", "p", "ɛ"]),
                                           ("ṣe", ["ʃ", "ə"])])
def test_dot_below_is_segmental(word, expected):
    """Dot-below changes the vowel; dropping the mark silently gave the wrong phoneme."""
    assert G2P("kdx", output="ipa", unknown="mark").phonemes(word) == expected


def test_dot_below_keeps_tone():
    """Re-composing the base must not swallow marks the language does define."""
    assert G2P("yor", output="ipa").phonemes("ṣé") == ["ʃ", "e˥"]


def test_tone_marks_unaffected_by_recomposition():
    assert G2P("yor", output="ipa").phonemes("bàbá") == ["b", "ä˩", "b", "ä˥"]


def test_dot_below_respects_opt_out():
    assert G2P("kdx", output="ipa", fallback=False).phonemes("ẹ") == ["ə"]
