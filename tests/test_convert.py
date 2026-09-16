import pytest

from africa_g2p import (
    UNIVERSAL,
    GraphemeConverter,
    convert_lang,
    convert_to_ipa,
)
from africa_g2p.g2p import G2P
from africa_g2p.loader import LanguageNotFoundError


# --- cross-language grapheme conversion ---

def test_same_phoneme_written_identically():
    # k͡p is written <kp> in both Jula and Ewe, so conversion is a no-op per unit
    assert convert_lang("kpako", "dyu", "ewe", sep=" ") == "kp a k o"


def test_roundtrip_ewe_dyu():
    assert convert_lang("kpako", "ewe", "dyu", sep=" ") == "kp a k o"
    assert convert_lang("nyini", "dyu", "ewe", sep=" ") == "ny i n i"


def test_to_universal():
    # ɲ -> ny is the majority grapheme, so universal output matches the source here
    assert convert_lang("nyini", "dyu", UNIVERSAL, sep=" ") == "ny i n i"


def test_converter_object_and_word():
    conv = GraphemeConverter("dyu", "ewe")
    assert conv.convert_word("kpako") == "kpako"
    assert conv.convert_word("kpako", sep=" ") == "kp a k o"
    assert conv.convert("kpako, nyini.") == "kpako, nyini."
    assert conv.convert("kpako, nyini.", sep=" ") == "kp a k o, ny i n i."


def test_text_output_preserves_word_boundaries():
    # default: words are kept whole (no separator between units), spacing/punct intact
    assert convert_lang("kpako sogo.", "dyu", "ewe") == "kpako sogo."
    assert convert_lang("kpako nyini", "ewe", UNIVERSAL) == "kpako nyini"


def test_unit_sequence_with_explicit_sep():
    assert convert_lang("kpako", "dyu", "ewe", sep=" ") == "kp a k o"


def test_punctuation_and_whitespace_preserved():
    assert convert_lang("Jakuma, sogo.", "dyu", "ewe", sep=" ") == "dy a k u m a, s o g o."


def test_aspiration_relaxed_to_universal():
    # these phones are the same for conversion purposes, so aspiration is dropped and
    # /kʰ/ /pʰ/ take the majority grapheme of plain /k/ /p/ (and /ɔ/ is written <o>)
    assert convert_lang("Onyankopɔn", "twi", UNIVERSAL, sep=" ") == "o ny a n k o p o n"


def test_aspiration_relaxed_for_target_without_aspiration():
    # Ewe does not mark aspiration, so Twi /kʰ/ writes with Ewe's /k/ grapheme
    assert convert_lang("Onyankopɔn", "twi", "ewe", sep=" ") == "o ny a n k o p ɔ n"


def test_target_exact_aspiration_still_wins():
    # Duruma marks aspiration (kʰ -> <k'>), so its exact reading beats the relaxed one
    assert convert_lang("ka", "twi", "dug", sep=" ") == "k' a"


def test_relax_aspiration_can_be_disabled():
    conv = GraphemeConverter("twi", "ewe", relax_aspiration=False)
    assert conv.convert_word("Onyankopɔn", sep=" ") == "o ny a n kh o ph ɔ n"


def test_universal_as_source():
    text = "kpako"
    assert convert_lang(text, UNIVERSAL, "ewe", sep=" ") == "kp a k o"


def test_convert_to_ipa_via_universal():
    # g2u2p: dyu "kpako" -> universal "kpako" -> IPA
    assert convert_to_ipa("kpako", "dyu", sep=" ") == "k͡p a k o"


def test_convert_to_ipa_text_preserves_boundaries():
    assert convert_to_ipa("kpako nyini.", "dyu") == "k͡pako ɲini."
    assert convert_to_ipa("kpako nyini.", "dyu", sep=" ") == "k͡p a k o ɲ i n i."


def test_convert_to_ipa_normalizes_through_universal():
    # /ɔ/ writes <o> in the universal set and is read back as the winner phoneme /o/.
    # The greedy reader also follows universal grapheme conventions (a long <aa>, a
    # prenasal <nk>), so round-trip IPA differs from the language's own chart IPA.
    assert convert_to_ipa("ɔfa", "twi", sep=" ") == "o f a"
    assert convert_to_ipa("Onyankopɔn", "twi", sep=" ") == "o ɲ a ᵑk o p o n"


def test_conversion_artificial_double_tripled():
    # Twi "dodoɔ" converted to universal: /ɔ/ -> <o> creates an artificial double,
    # which has its existing vowel replaced with its alternative 'u' and converted
    # vowel kept as universal 'o' to become "doduo".
    assert convert_lang("dodoɔ", "twi", UNIVERSAL) == "doduo"


def test_true_source_doubles_preserved():
    # True source long vowels (e.g. Twi "hyɛɛ") are not conversion collisions
    # and should stay double ("shee"), not be altered to single/alternative vowels.
    assert convert_lang("hyɛɛ", "twi", UNIVERSAL) == "shee"


def test_english_words_skipped():
    # English words found in text are passed through untouched.
    assert convert_lang("Google is great", "twi", UNIVERSAL) == "google is great"


def test_missing_language_raises():
    with pytest.raises(LanguageNotFoundError):
        GraphemeConverter("nope-not-a-lang", "ewe")
    with pytest.raises(LanguageNotFoundError):
        GraphemeConverter("dyu", "nope-not-a-lang")


# --- G2P.from_rules (used for the virtual universal language) ---

def test_from_rules_builds_engine():
    rules = {"code": "zz", "graphemes": {"kp": "k͡p", "k": "k", "a": "a", "o": "o"}}
    conv = G2P.from_rules(rules)
    assert conv.convert("kpako", sep=" ") == "k͡p a k o"
    assert conv.convert_word("kpako", sep=" ") == "k͡p a k o"

def test_universal_orthography_has_no_apostrophes():
    """Ejectives write as plain consonants: an apostrophe is punctuation to a TTS
    voice, which read Xhosa "uk'uba" with a break that is not in the language."""
    from africa_g2p.convert import _universal_tables

    forward, reverse = _universal_tables()
    apostrophes = set("'’ʼˀ")
    bad = [g for g in reverse.values() if apostrophes & set(g)]
    assert bad == [], f"universal graphemes still carrying apostrophes: {bad[:10]}"
    assert not [g for g in forward if apostrophes & set(g)]


def test_universal_ejectives_lose_only_the_mark():
    from africa_g2p import GraphemeConverter, UNIVERSAL

    out = GraphemeConverter("xho", UNIVERSAL).convert("ukuba nikwazi ukucalula")
    assert "'" not in out
    assert "ukuba" in out and "nikwazi" in out


def test_universal_drops_placeholders_and_null_phonemes():
    """"VV" is a "write the vowel twice" placeholder and ∅ is silence: neither is
    a spelling, and both reached transcripts as literal characters."""
    from africa_g2p.convert import _universal_tables

    _, reverse = _universal_tables()
    assert "VV" not in reverse.values()
    assert "ا" not in reverse.values()   # Arabic alef, the old ∅ winner
    for null in ("∅", "ʔ∅"):
        assert not reverse.get(null)


def test_universal_prefers_a_plain_latin_vote_when_the_winner_is_not_one():
    from africa_g2p.convert import _plain_latin_grapheme

    vai = {"grapheme": "ꕨ", "base_grapheme": "ꕨ", "votes": {"nyja": 1}}
    assert _plain_latin_grapheme(vai) == "nyja"
    hyphen = {"grapheme": "n-g", "base_grapheme": "ng", "votes": {"ng": 1}}
    assert _plain_latin_grapheme(hyphen) == "ng"


def test_non_alphabetic_universal_graphemes_are_listed_and_warned():
    """Clicks have no plain-Latin spelling, so they survive — but callers are told,
    and nothing that could have been spelled in letters is left in the list."""
    from africa_g2p.convert import _is_usable, universal_non_alphabetic

    remaining = universal_non_alphabetic()
    assert remaining, "expected the Khoisan clicks to remain"
    assert "\u0298" in "".join(remaining.values())          # bilabial click
    assert all(not _is_usable(g) for g in remaining.values())
    # Placeholders and punctuation are dropped, not merely reported.
    assert "VV" not in remaining.values()
    assert not any(":" in g or "-" in g for g in remaining.values())


def test_universal_keeps_letters_but_drops_punctuation():
    """A click letter is a phoneme worth keeping; "ː" falling back to ":" is a pause
    inserted into every transcript that used it."""
    from africa_g2p.convert import _universal_tables

    _, reverse = _universal_tables()
    assert ":" not in reverse.values()
    assert any("\u0298" in g for g in reverse.values())
