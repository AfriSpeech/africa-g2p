import unicodedata

import pytest

from africa_g2p import AfricaPipeline, G2P, available_languages, g2p


def test_language_available():
    assert "dyu" in available_languages()


def test_basic_multigraph_segmentation():
    conv = G2P("dyu")
    # 'ny' must be treated as one grapheme -> ɲ, not n + y
    assert conv.convert("nyini", sep=" ") == "ɲ i n i"


def test_digraph_kp_gb():
    conv = G2P("dyu")
    assert conv.convert("kpako", sep=" ") == "k͡p a k o"
    assert conv.convert("gbɛ", sep=" ") == "ɡ͡b ɛ"


def test_open_vowels():
    conv = G2P("dyu")
    assert conv.convert("sogo") == "soɡo"
    assert conv.convert("jɛgɛ") == "dʲɛɡɛ"


def test_high_tone_diacritic():
    conv = G2P("dyu")
    # acute accent on the vowel -> high-tone marker attached to that phoneme
    assert conv.convert("kú", sep=" ") == "k u˥"


def test_pipeline_api_and_punctuation():
    pipe = AfricaPipeline(lang="dyu")
    out = pipe.run("jakuma, sogo.")
    assert out == "dʲakuma, soɡo."


def test_batch():
    pipe = AfricaPipeline(lang="dyu")
    assert pipe.run(["sogo", "maro"]) == ["soɡo", "maro"]


def test_case_folding():
    assert g2p("Jakuma", "dyu") == "dʲakuma"


def test_unknown_passthrough_vs_drop():
    assert G2P("dyu", unknown="passthrough").convert("sox") == "sox"
    assert G2P("dyu", unknown="drop").convert("sox") == "so"


def test_examples_from_source_are_convertible():
    from africa_g2p.loader import load_rules

    conv = G2P("dyu")
    for ex in load_rules("dyu")["examples"]:
        out = conv.convert(ex["word"])
        assert out and "�" not in out


# --- library-wide regression guards over the extracted rule files ---

def test_library_size():
    assert len(available_languages()) >= 130


def test_all_rule_files_load_and_build():
    for code in available_languages():
        conv = G2P(code)
        assert conv.graphemes, f"{code} has an empty grapheme table"


def test_aggregate_example_roundtrip_rate():
    """At least 98% of the source's own example words convert with no unmapped char."""
    from africa_g2p.loader import load_rules

    total = bad = 0
    for code in available_languages():
        conv = G2P(code, unknown="mark")
        for ex in load_rules(code).get("examples", []):
            w = ex.get("word", "")
            if not w:
                continue
            total += 1
            if "�" in conv.convert(w):
                bad += 1
    assert total > 3000
    assert bad / total <= 0.02, f"{bad}/{total} example words had unmapped chars"


@pytest.mark.parametrize("code,word,expected", [
    ("gaa", "màŋ", "m a˩ ŋ"),      # Ga: low tone marker preserved on the vowel
    ("aka", "saw", "s a w"),        # Akan
    ("hau-niger", "ma'aikaci", "m a ʔ a i k a c i"),  # Hausa: apostrophe -> glottal stop
])
def test_specific_language_outputs(code, word, expected):
    if code not in available_languages():
        pytest.skip(f"{code} not extracted")
    assert G2P(code).convert(word, sep=" ") == expected
