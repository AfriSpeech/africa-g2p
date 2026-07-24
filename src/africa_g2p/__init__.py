"""africa-g2p: rule-based grapheme-to-phoneme conversion for African languages."""
from .g2p import G2P, g2p
from .pipeline import AfricaPipeline
from .loader import available_languages, registry, LanguageNotFoundError

__version__ = "0.1.0"

__all__ = [
    "AfricaPipeline",
    "G2P",
    "g2p",
    "available_languages",
    "registry",
    "LanguageNotFoundError",
]
