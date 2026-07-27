import unicodedata

import pytest

from africa_g2p import AfricaPipeline, G2P, available_languages, g2p


def ipa(code, **kw):
    return G2P(code, output="ipa", **kw)


def test_language_available():
    assert "dyu" in available_languages()


# --- IPA output mode ---

def test_basic_multigraph_segmentation():
    # 'ny' must be treated as one grapheme -> ɲ, not n + y
    assert ipa("dyu").convert("nyini", sep=" ") == "ɲ i n i"


def test_digraph_kp_gb():
    assert ipa("dyu").convert("kpako", sep=" ") == "k͡p a k o"
    assert ipa("dyu").convert("gbɛ", sep=" ") == "ɡ͡b ɛ"


def test_open_vowels():
    assert ipa("dyu").convert("sogo") == "soɡo"
    assert ipa("dyu").convert("jɛgɛ") == "dʲɛɡɛ"


def test_high_tone_diacritic():
    # acute accent on the vowel -> high-tone marker attached to that phoneme
    assert ipa("dyu").convert("kú", sep=" ") == "k u˥"


def test_ipa_case_folding():
    assert g2p("Jakuma", "dyu", output="ipa") == "dʲakuma"


def test_clean_preserves_ipa_tie_bar():
    # the affricate tie bar is IPA and must survive cleaning
    assert ipa("dyu").convert("kp", sep=" ") == "k͡p"


# --- grapheme output mode (the default) ---

def test_grapheme_is_default():
    # default output is native orthography, not IPA
    assert G2P("dyu").convert("nyini", sep=" ") == "ny i n i"
    assert AfricaPipeline(lang="dyu").run("jakuma") == "jakuma"


def test_grapheme_multigraph_units():
    # kp / gb stay single native units, not their IPA form
    assert G2P("dyu").convert("kpako", sep=" ") == "kp a k o"
    assert G2P("dyu").convert("gbɛ", sep=" ") == "gb ɛ"


def test_grapheme_preserves_tone_marks():
    # native mode keeps diacritics as written (unit 'ú' = u + acute)
    assert G2P("dyu").convert("kú") == "kú"
    assert G2P("dyu").convert("kú", sep=" ") == "k ú"


def test_grapheme_preserves_special_letters():
    # ɔ, ɛ are native letters and must be kept verbatim
    assert G2P("dyu").convert("jɛgɛ", sep=" ") == "j ɛ g ɛ"


# --- shared behaviour ---

def test_pipeline_batch_and_punctuation():
    pipe = AfricaPipeline(lang="dyu")
    assert pipe.run("jakuma, sogo.") == "jakuma, sogo."
    assert pipe.run(["sogo", "maro"]) == ["sogo", "maro"]


def test_unknown_passthrough_vs_drop():
    assert G2P("dyu", unknown="passthrough").convert("sox") == "sox"
    assert G2P("dyu", unknown="drop").convert("sox") == "so"


def test_invalid_output_mode():
    with pytest.raises(ValueError):
        G2P("dyu", output="phonetic")


def test_strip_diacritics_option():
    assert g2p("bàbá", "dyu", sep=" ") == "b à b á"                       # kept by default
    assert g2p("bàbá", "dyu", sep=" ", strip_diacritics=True) == "b a b a"
    # segmental letters must survive stripping
    assert g2p("gbɛ", "dyu", sep=" ", strip_diacritics=True) == "gb ɛ"


def test_akan_digraphs_are_single_units():
    # palatalization/labial-palatalization digraphs restored from the source page
    assert G2P("aka").convert("gye nyansa hyɛ", sep=" ") == "gy e ny a n s a hy ɛ"
    assert G2P("aka", output="ipa").convert("gye", sep=" ") == "dʑ ɪ"


def test_vai_dual_script_if_present():
    if "vai" not in available_languages():
        pytest.skip("vai (omniglot) not built")
    ipa = G2P("vai", output="ipa")
    assert ipa.convert("ꕙꔤ") == ipa.convert("vai")  # native script == Latin phonemisation


# --- library-wide regression guards over the extracted rule files ---

def test_library_size():
    assert len(available_languages()) >= 130


def test_all_rule_files_load_and_build():
    for code in available_languages():
        assert G2P(code).graphemes, f"{code} has an empty grapheme table"


def test_examples_convert_in_both_modes():
    from africa_g2p.loader import load_rules

    for code in ["dyu", "aka", "gaa"]:
        if code not in available_languages():
            continue
        for mode in ("grapheme", "ipa"):
            conv = G2P(code, output=mode)
            for ex in load_rules(code).get("examples", []):
                out = conv.convert(ex["word"])
                assert out and "�" not in out


def test_grapheme_coverage_at_least_matches_ipa():
    """Grapheme mode (alphabet-augmented) covers example words at least as well as IPA."""
    from africa_g2p.loader import load_rules

    total = bad_g = 0
    for code in available_languages():
        gm = G2P(code, output="grapheme", unknown="mark")
        for ex in load_rules(code).get("examples", []):
            w = ex.get("word", "")
            if not w:
                continue
            total += 1
            if "�" in gm.convert(w):
                bad_g += 1
    assert total > 3000
    assert bad_g / total <= 0.02, f"{bad_g}/{total} example words had unmapped chars"


def test_ipa_output_has_no_orthographic_accents():
    """IPA output must never contain orthographic tone/accent combining marks."""
    from africa_g2p.normalizer import _ORTHOGRAPHIC_ACCENTS
    from africa_g2p.loader import load_rules

    for code in available_languages():
        conv = G2P(code, output="ipa")
        for ex in load_rules(code).get("examples", []):
            out = conv.convert(ex.get("word", ""))
            for ch in unicodedata.normalize("NFD", out):
                assert ord(ch) not in _ORTHOGRAPHIC_ACCENTS, f"{code}: {out!r} kept an accent"


@pytest.mark.parametrize("code,word,expected", [
    ("gaa", "màŋ", "m a˩ ŋ"),                          # Ga: low tone -> IPA tone mark
    ("hau-niger", "ma'aikaci", "m a ʔ a i k a c i"),   # Hausa: apostrophe -> glottal stop
])
def test_specific_ipa_outputs(code, word, expected):
    if code not in available_languages():
        pytest.skip(f"{code} not extracted")
    assert G2P(code, output="ipa").convert(word, sep=" ") == expected
