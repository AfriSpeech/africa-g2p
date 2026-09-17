"""africa-g2p: rule-based grapheme-to-phoneme conversion for African languages."""
from .convert import (GraphemeConverter, UNIVERSAL, UniversalUnsupported,
                      convert_lang, convert_to_ipa, from_ipa, roundtrip,
                      universal_languages, universal_supported)
from .english import ENGLISH_CODES, EnglishG2P, EspeakUnavailable
from .g2p import G2P, g2p
from .pipeline import AfricaPipeline
from .loader import available_languages, registry, LanguageNotFoundError

# Single-sourced from the installed package metadata so it cannot drift from
# pyproject.toml again: this constant sat at 0.1.0 through the 0.1.1 and 0.2.0
# releases, and anything recording it — a dataset card, a provenance log — wrote
# down the wrong version.
try:  # pragma: no cover - trivial
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    __version__ = _pkg_version("africa-g2p")
except Exception:  # not installed (running from a source checkout)
    __version__ = "0.2.0"

__all__ = [
    "AfricaPipeline",
    "G2P",
    "g2p",
    "GraphemeConverter",
    "from_ipa",
    "roundtrip",
    "convert_lang",
    "convert_to_ipa",
    "UNIVERSAL",
    "UniversalUnsupported",
    "universal_supported",
    "universal_languages",
    "EnglishG2P",
    "EspeakUnavailable",
    "ENGLISH_CODES",
    "available_languages",
    "registry",
    "LanguageNotFoundError",
]
