"""Rule files marked "tts-reviewed" must follow docs/IPA_CONVENTION.md."""
import importlib.util
import json
from pathlib import Path

import pytest

from africa_g2p import G2P, UNIVERSAL, GraphemeConverter
from africa_g2p import convert as C

ROOT = Path(__file__).resolve().parent.parent
LANG_DIR = ROOT / "src" / "africa_g2p" / "languages"

_spec = importlib.util.spec_from_file_location(
    "validate_tts_convention", ROOT / "scripts" / "validate_tts_convention.py")
validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validator)

REVIEWED = sorted(
    p.stem for p in LANG_DIR.glob("*.json")
    if json.loads(p.read_text(encoding="utf-8")).get("confidence") == "tts-reviewed")


def test_ghanaian_languages_are_reviewed():
    assert {"twi", "fat", "ewe", "gaa", "dag"} <= set(REVIEWED)


@pytest.mark.parametrize("lang", REVIEWED)
def test_one_standard_phoneme_per_entry(lang):
    errs, _ = validator.check_file(LANG_DIR / f"{lang}.json")
    assert errs == []


@pytest.mark.parametrize("lang", REVIEWED)
def test_every_phoneme_has_a_plain_universal_spelling(lang):
    conv = GraphemeConverter(lang, UNIVERSAL)
    for grapheme, ipa in G2P(lang, output="ipa").graphemes.items():
        spelled, _ = conv._map(ipa)
        assert spelled.isascii() and (spelled == "" or spelled.isalpha()), (grapheme, ipa, spelled)


def test_same_phoneme_same_symbol_across_ghanaian_languages():
    tables = {l: json.loads((LANG_DIR / f"{l}.json").read_text(encoding="utf-8"))["graphemes"]
              for l in ("twi", "fat", "ewe", "gaa", "dag")}
    for grapheme, want in {"ny": "ɲ", "kp": "k͡p", "gb": "ɡ͡b", "ŋm": "ŋ͡m", "y": "j",
                           "g": "ɡ", "dz": "d͡z"}.items():
        got = {l: t[grapheme] for l, t in tables.items() if grapheme in t}
        assert set(got.values()) == {want}, (grapheme, got)


@pytest.mark.parametrize("lang,text,ipa", [
    # Fante: CV spellings used to swallow the vowel (no -> nʷ, tu -> tʷ).
    ("fat", "no", "n o"), ("fat", "so", "s o"), ("fat", "tu", "t u"),
    # Twi: broad transcription, no aspiration, written vowel value.
    ("twi", "kyerɛ", "t͡ɕ e ɾ ɛ"), ("twi", "pɛ", "p ɛ"), ("twi", "di", "d i"),
    ("twi", "dwuma", "d͡ʑʷ u m a"),
    # Ewe: no syllable units, standard IPA only.
    ("ewe", "si", "s i"), ("ewe", "tsi", "t͡s i"), ("ewe", "ʋu", "β u"),
    # Ga: tied affricates and doubly articulated stops.
    ("gaa", "tsɔ", "t͡ʃ ɔ"), ("gaa", "ŋmɛ", "ŋ͡m ɛ"),
    # Dagbani: single e/o are not long; doubled vowels read letter by letter.
    ("dag", "be", "b e"), ("dag", "maa", "m a a"),
    # Nasal vowels via the tilde rule, written in either composed or decomposed form.
    ("gaa", "ɔ̃", "ɔ̃"), ("ewe", "ẽ", "ẽ"),
])
def test_ipa_examples(lang, text, ipa):
    assert G2P(lang, output="ipa").convert(text, sep=" ") == ipa


def test_twi_dw_universal_is_ascii(monkeypatch):
    monkeypatch.setattr(C, "_is_english_word", lambda w: False)
    assert GraphemeConverter("twi", UNIVERSAL).convert("dwuma Kwadwo") == "jwuma kwajwo"


@pytest.mark.parametrize("lang", REVIEWED)
def test_alphabet_units_match_the_table(lang):
    """Grapheme output segments by `alphabet`; it must not keep units the table removed
    (Fante `no`/`tu` used to stay single units in grapheme mode after the IPA fix)."""
    rules = json.loads((LANG_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    assert set(rules["alphabet"]) == set(rules["graphemes"])
    assert set(rules["scripts"]["latin"]) == set(rules["graphemes"])


@pytest.mark.parametrize("lang,text,units", [
    ("fat", "Me no so tu", "m e n o s o t u"),
    ("twi", "Kwasia ao", "kw a s i a a o"),
    ("ewe", "si", "s i"),
    ("gaa", "ɔ̃", "ɔ̃"),
])
def test_grapheme_mode_examples(lang, text, units):
    assert G2P(lang).convert(text, sep=" ") == units
