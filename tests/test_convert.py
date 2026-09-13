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