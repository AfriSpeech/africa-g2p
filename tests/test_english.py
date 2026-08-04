"""English G2P.

The rule tables cannot represent English: they map through/though/tough/thought to one
identical string. These tests pin the behaviour that makes English usable, and the symbol
conventions that keep it in the same phoneme space as the 400 rule-based languages.
"""
from __future__ import annotations

import pytest

from africa_g2p.english import EnglishG2P, EspeakUnavailable

try:
    _G = EnglishG2P()
    _G.convert("test")
    HAVE_ESPEAK = True
except EspeakUnavailable:
    HAVE_ESPEAK = False

pytestmark = pytest.mark.skipif(not HAVE_ESPEAK, reason="espeak-ng not installed")


@pytest.mark.parametrize("word,expected", [
    ("through", "θɹuː"), ("though", "ðoʊ"), ("tough", "tʌf"), ("thought", "θɔːt"),
])
def test_ough_words_are_distinct(word, expected):
    """The exact failure of the rule table: these four collapsed into one string."""
    assert EnglishG2P().convert(word) == expected


def test_silent_letters():
    assert EnglishG2P().convert("knight") == "naɪt"


def test_out_of_vocabulary_words():
    """African names and borrowings appear throughout African English speech.

    A dictionary-only approach returns nothing for these; espeak's letter-to-sound rules
    handle them.
    """
    for w in ("Akosua", "Kwabena", "obroni"):
        out = EnglishG2P().convert(w)
        assert out and not out.isspace(), w


# -- symbol conventions, shared with the rule-based languages ---------------

def test_affricates_use_tie_bars():
    """espeak writes tʃ as two characters; the rule tables use t͡ʃ as one unit."""
    units = EnglishG2P().phonemes("church judge")
    assert "t͡ʃ" in units and "d͡ʒ" in units
    assert "ʃ" not in units and "ʒ" not in units


def test_script_g_not_ascii_g():
    """IPA voiced velar stop is U+0261, as norm_ipa enforces at build time."""
    out = EnglishG2P().convert("go bag")
    assert "ɡ" in out
    assert "g" not in out


def test_diphthongs_are_single_units():
    assert EnglishG2P().phonemes("knight") == ["n", "aɪ", "t"]


def test_no_stress_marks():
    out = EnglishG2P().convert("photography computer")
    assert "ˈ" not in out and "ˌ" not in out


def test_empty_input():
    g = EnglishG2P()
    assert g.convert("") == "" and g.phonemes("") == []
    assert g.convert("   ") == ""


def test_grapheme_output_refused():
    """There is no rule table for English, so native-orthography units are meaningless."""
    with pytest.raises(ValueError):
        EnglishG2P(output="grapheme")
