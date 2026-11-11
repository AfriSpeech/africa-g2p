import pytest
from africa_g2p import g2p, G2P, load_codeswitch_dict


def test_codeswitch_single_word():
    text = "Mepɛ sɛ mekɔ school."
    ipa = g2p(text, "twi", output="ipa", codeswitch=True)
    assert "skuːl" in ipa
    assert "mepɛ" in ipa


def test_codeswitch_multi_word_phrase():
    text = "Mepɛ sɛ mekɔ high school wɔ regional hospital no nkyɛn."
    ipa = g2p(text, "twi", output="ipa", codeswitch=True)
    assert "haɪ skuːl" in ipa
    assert "ɹiːd͡ʒənəl hɑːspɪɾəl" in ipa


def test_codeswitch_custom_dict():
    custom = {"supermarket": "suːpɚmɑːɹkɪt"}
    text = "Mekɔ supermarket no."
    ipa = g2p(text, "twi", output="ipa", codeswitch=custom)
    assert "suːpɚmɑːɹkɪt" in ipa


def test_codeswitch_disabled_by_default():
    text = "Mepɛ sɛ mekɔ school."
    ipa = g2p(text, "twi", output="ipa", codeswitch=False)
    assert "skuːl" not in ipa
