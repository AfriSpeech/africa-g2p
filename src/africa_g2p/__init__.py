"""africa-g2p: rule-based grapheme-to-phoneme conversion for African languages."""
from .english import ENGLISH_CODES, EnglishG2P, EspeakUnavailable
from .g2p import G2P, g2p
from .pipeline import AfricaPipeline
from .loader import available_languages, registry, LanguageNotFoundError

__version__ = "0.1.0"

__all__ = [
    "AfricaPipeline",
    "G2P",
    "g2p",
    "EnglishG2P",
    "EspeakUnavailable",
    "ENGLISH_CODES",
    "available_languages",
    "registry",
    "LanguageNotFoundError",
]
