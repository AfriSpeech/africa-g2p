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


def test_universal_data_file_is_clean_at_the_source():
    """The constraint lives in the data, not in a filter applied on the way out —
    anything reading the JSON directly gets plain letters too."""
    import json

    from africa_g2p.convert import _UNIVERSAL_FILE, _is_usable

    data = json.loads(_UNIVERSAL_FILE.read_text(encoding="utf-8"))
    bad = {ipa: r["grapheme"] for ipa, r in data["phonemes"].items()
           if r.get("grapheme") and not _is_usable(r["grapheme"])}
    assert bad == {}, f"non plain-Latin graphemes in the data file: {list(bad.items())[:5]}"
    # Revised entries keep what they used to say, so the change is auditable.
    revised = [r for r in data["phonemes"].values() if "grapheme_original" in r]
    assert len(revised) > 200
    assert data["meta"]["revision"]["approximation_source"].startswith("gemini")


def test_universal_orthography_is_entirely_plain_letters():
    """The whole point of the universal set: a-z only, so a synthesiser reads it.

    Clicks with no attested Latin spelling were approximated rather than kept as
    ʘ or dropped — dropping deletes a phoneme, keeping it makes the voice skip.
    """
    from africa_g2p.convert import _is_usable, _universal_tables, universal_non_alphabetic

    forward, reverse = _universal_tables()
    assert universal_non_alphabetic() == {}
    assert all(_is_usable(g) for g in reverse.values() if g)
    # Deliberately unwritten phonemes map to "" rather than being absent, so the
    # converter writes nothing instead of falling through to the raw IPA symbol.
    assert reverse.get("\u0294") == ""
    assert all(_is_usable(g) for g in forward)
    assert "VV" not in reverse.values()
    assert ":" not in reverse.values()


def test_clicks_have_plain_letter_spellings():
    from africa_g2p.convert import _universal_tables

    _, reverse = _universal_tables()
    assert reverse["\u0298"] == "p"          # bilabial click
    assert "\u0298" not in "".join(reverse.values())


def test_a_dirty_table_warns_rather_than_reaching_the_audio():
    """The data is clean, so the guard must fire only if that regresses."""
    import warnings

    from africa_g2p.convert import _warn_non_alphabetic

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_non_alphabetic({"x": "ok"})
        assert not caught
        _warn_non_alphabetic({"\u0298": "\u0298"})
        assert len(caught) == 1
        assert "not plain a-z letters" in str(caught[0].message)


def test_universal_maps_tone_marked_and_modified_variants():
    """Source orthographies write tone on the vowel. The accented form is absent from
    the survey, so it used to pass through — and once normalisation stripped the
    accent, a bare ɔ or ɛ was left in the output, the very character universal
    exists to remove."""
    from africa_g2p import UNIVERSAL, GraphemeConverter

    out = GraphemeConverter("bza", UNIVERSAL).convert("lɔ́lɔndai ɣɛ́i")
    assert "ɔ" not in out and "ɛ" not in out
    assert "lolondai" in out

    # A phoneme carrying a secondary-articulation mark resolves to its base letter.
    out = GraphemeConverter("mnf", UNIVERSAL).convert("beˤtat leˤ")
    assert "ˤ" not in out and "betat" in out


def test_modifier_only_units_write_as_nothing():
    from africa_g2p.convert import _strip_combining

    assert _strip_combining("ɔ́") == "ɔ"
    assert _strip_combining("ɔ˥") == "ɔ"      # tone bar
    assert _strip_combining("əˤ") == "ə"      # pharyngealised
    assert _strip_combining("ˤ") == ""                  # nothing but a modifier


def test_universal_collision_alternatives_are_plain_letters():
    """Collision avoidance rewrites a vowel to a near neighbour. For universal that
    neighbour must be a-z: "a" -> "ə" put a schwa into output with no schwa in the
    source ("náań" -> "nəan")."""
    from africa_g2p import UNIVERSAL, GraphemeConverter
    from africa_g2p.convert import _UNIVERSAL_VOWEL_ALTERNATIVES, _is_plain_latin

    assert all(_is_plain_latin(v) for v in _UNIVERSAL_VOWEL_ALTERNATIVES.values())
    out = GraphemeConverter("bud", UNIVERSAL).convert("Unimbɔti nín kíĺ ki náań")
    assert "ə" not in out and "nean" in out


def test_universal_never_writes_apostrophes():
    """The universal orthography is plain a-z, so it writes no apostrophes.

    A word-initial apostrophe is punctuation to the tokenizer, so it used to
    pass through untouched -- Bijwa writes many ('jäa, 'ŋlë) and they survived
    into universal text, while the same mark ending a word was absorbed and
    dropped, which was not even consistent."""
    from africa_g2p.convert import _APOSTROPHES

    conv = GraphemeConverter("bjw", UNIVERSAL)
    for text in ("'jäa' 'ŋlëkayerü", "cɛtɛa' ‑gua'", "'na ‑fʋflʋlʋ"):
        out = conv.convert(text)
        assert not any(a in out for a in _APOSTROPHES), out
    assert not any(a in conv.convert_word("'jäa") for a in _APOSTROPHES)

    # plain-Latin languages already did this; they must keep doing it
    assert "'" not in convert_lang("ng'ombe", "swh", UNIVERSAL)


def test_universal_output_is_plain_latin():
    """Universal is a plain a-z orthography, so nothing else should reach it.

    Three ways non-a-z letters used to survive:
      - a language whose declared alphabet is plain a-z is passed through
        unchanged, and several write tone on top of it (Bokyi bé, Bwamu á)
      - the saltillo ꞌ is a letter, not punctuation, so it dodged the
        apostrophe check that Beja needed
      - confusables of letters the chart does have (Adioukrou writes ↄ for ɔ)
    """
    cases = [("bky", "bé mí"), ("bwo", "á"), ("bez", "kúu"),
             ("bej", "ꞌama"), ("adj", "ↄbↄ"), ("bsw", "ɂama")]
    for code, text in cases:
        out = convert_lang(text, code, UNIVERSAL)
        assert out == out.lower()
        bad = [c for c in out if c.isalpha() and not ("a" <= c <= "z")]
        assert not bad, f"{code}: {out!r} still has {bad}"


def test_passthrough_drops_tone_but_keeps_letters():
    """Dropping marks must not eat the letters they sit on."""
    assert convert_lang("bé mí", "bky", UNIVERSAL) == "be mi"
    assert convert_lang("kúu", "bez", UNIVERSAL) == "kuu"


def test_unlisted_letters_are_spelt_the_way_most_tables_spell_them():
    """A letter a language's own table omits used to survive into universal.

    Every other table is evidence for how to write it: ŋ is spelt ng by 346 of
    them, ɔ is spelt o by 295. Falling back on that consensus is what keeps
    universal plain a-z when a table has a gap."""
    from africa_g2p import universal_fallback

    assert universal_fallback("ŋ") == "ng"
    assert universal_fallback("ɔ") == "o"
    assert universal_fallback("ɛ") == "e"
    assert universal_fallback("ɓ") == "b"
    # length and modifier marks are not written at all
    assert universal_fallback("ː") == ""
    assert universal_fallback("ʰ") == ""
    # where the tables disagree the majority wins; where only one lists the
    # letter at all it is used anyway, since it is the only evidence there is.
    # Tifinagh rests entirely on one table, and rejecting it left Tuareg text
    # passing through unconverted.
    assert universal_fallback("\u2d4f") == "n"        # Tifinagh, from siz alone
    assert all(("a" <= c <= "z") for c in universal_fallback("\u00fe") or "a")


def test_latin_orthographies_of_arabic_script_languages_still_work():
    """These have a Latin table and a Latin orthography, and convert cleanly.

    They also have an Arabic-script corpus their table cannot read. Refusing the
    whole language over that was wrong -- it would have broken the orthography
    the table is actually for."""
    cases = [("rif", "Ɣarwem aḏ teggem"), ("shi", "ġ-uwssan-an isfld"),
             ("apd", "Kitaab miilaad"), ("fuv", "Gaɗa duuɓi ɗuɗɗi"),
             ("ttq", "Ǝntanay da esmawan")]
    for code, text in cases:
        out = convert_lang(text, code, UNIVERSAL)
        bad = [c for c in out if c.isalpha() and not ("a" <= c <= "z")]
        assert not bad, f"{code}: {out!r} has {bad}"


def test_universal_is_plain_a_z_even_with_table_gaps():
    for code, text in [("ary", "æ"), ("naq", "ǃgâbi"), ("yal", "ɔɛ"),
                       ("knf", "ŋŧ"), ("swb", "ɓɗ"), ("bwr", "ʒɬʃ")]:
        out = convert_lang(text, code, UNIVERSAL)
        bad = [c for c in out if c.isalpha() and not ("a" <= c <= "z")]
        assert not bad, f"{code}: {out!r} has {bad}"
