"""IPA back into a language's own orthography.

The universal form is deliberately lossy -- ɔ and o both write as "o" -- so it
cannot be reversed. IPA keeps the distinction, so a language's own chart can map
it back. These tests pin that difference down.
"""
import pytest

from africa_g2p import (UNIVERSAL, GraphemeConverter, G2P, available_languages,
                        from_ipa, roundtrip)


def _skip_unless(code):
    if code not in available_languages():
        pytest.skip(f"{code} not built")


@pytest.mark.parametrize("lang,ipa,expected", [
    ("twi", "ɔdɔ", "ɔdɔ"),
    ("twi", "oɲankʰopʰɔn", "onyankopɔn"),
    ("bwu", "tɛŋka", "tɛŋka"),
])
def test_from_ipa_writes_the_language_orthography(lang, ipa, expected):
    _skip_unless(lang)
    assert from_ipa(ipa, lang) == expected


def test_from_ipa_preserves_word_boundaries_and_punctuation():
    _skip_unless("twi")
    assert from_ipa("ɔdɔ, ɔdɔ!", "twi") == "ɔdɔ, ɔdɔ!"


def test_from_ipa_unknown_phoneme_handling():
    _skip_unless("twi")
    assert from_ipa("ǂ", "twi", unknown="keep") == "ǂ"
    assert from_ipa("ǂ", "twi", unknown="drop") == ""
    assert from_ipa("ǂ", "twi", unknown="mark") == "?"


@pytest.mark.parametrize("lang,text", [
    ("twi", "Onyankopɔn adɔeɛ nyɛ"),
    ("dag", "Naawuni yuli"),
    ("bwu", "tɛŋka la"),
])
def test_roundtrip_through_ipa_is_faithful(lang, text):
    """A language's own chart round-trips; this is what universal cannot do."""
    _skip_unless(lang)
    assert roundtrip(text, lang) == text.lower()


def test_universal_is_lossy_by_design():
    """Regression guard: universal collapses ɔ onto o, so it cannot be reversed.

    If this ever starts passing, the universal inventory has changed and the
    docs claiming it is one-way need revisiting.
    """
    _skip_unless("twi")
    src = "Onyankopɔn"
    uni = GraphemeConverter("twi", UNIVERSAL).convert(src)
    back = GraphemeConverter(UNIVERSAL, "twi").convert(uni)
    assert uni == "onyankopon"
    assert back != src.lower()


def test_from_ipa_rejects_unknown_language():
    from africa_g2p import LanguageNotFoundError
    with pytest.raises((LanguageNotFoundError, KeyError)):
        from_ipa("ɔdɔ", "zzz")
