"""Core grapheme-to-phoneme engine.

The algorithm is greedy longest-match multigraph segmentation over a per-language
grapheme table, with trailing combining marks (tone, nasalization, length) mapped
separately as suprasegmentals. This suits the shallow, largely phonemic orthographies
documented in Hartell's *Alphabets of Africa* (UNESCO, 1993).
"""
from __future__ import annotations

import unicodedata
from typing import Dict, List, Optional

from .loader import load_rules
from .normalizer import clean_ipa, fold_confusables, normalize_text, tokenize


class G2P:
    """Grapheme-to-phoneme converter for a single language."""

    def __init__(self, code: str, *, output: str = "grapheme",
                 unknown: str = "passthrough", clean: bool = True,
                 strip_diacritics: bool = False):
        """
        Args:
            code: ISO 639-3 language code with a rule file.
            output: what each phoneme unit is rendered as —
                    "grapheme" (default): the language's own writing units, e.g. ``ny``,
                    ``kp``, ``ɔ`` — a phonemic segmentation in native orthography, which
                    trains TTS/ASR models better than IPA. For non-Latin scripts this
                    yields the Latin romanisation when one is available (falling back to
                    the native script otherwise). Or
                    "ipa": International Phonetic Alphabet transcription; or
                    "latin": romanise a non-Latin script to its Latin form (uses the
                    language's script→Latin map; Latin input passes through unchanged).
            unknown: how to treat a grapheme with no mapping —
                     "passthrough" (keep the character), "drop", or "mark" (�).
            clean: IPA mode only — if True (default), guarantee the output holds only
                   phoneme symbols and IPA diacritics (strips any leaked orthographic
                   tone/accent marks).
            strip_diacritics: grapheme mode only — if True, remove orthographic
                   tone/accent marks (acute, grave, circumflex, …) from the native
                   output while keeping segmental letters (ɔ, ɛ, ŋ, dot-below) and
                   nasalization. Default False (preserve the written form exactly).
        """
        if output not in ("ipa", "grapheme", "latin"):
            raise ValueError("output must be 'ipa', 'grapheme', or 'latin'")
        self.code = code
        self.rules = load_rules(code)
        self.output = output
        self.unknown = unknown
        self.clean = clean
        self.strip_diacritics = strip_diacritics

        def _norm(k):
            return unicodedata.normalize("NFD", fold_confusables(str(k).lower()))

        # Grapheme table: base letters (no combining marks) -> IPA string.
        # Grapheme keys are lowercased + confusable-folded to match normalized input.
        self.graphemes: Dict[str, str] = {
            _norm(g): ipa for g, ipa in self.rules["graphemes"].items()
        }
        # Romanization table: native-script unit -> Latin form (for output="latin").
        # Latin units map to themselves, so Latin input passes through unchanged.
        self.romanization: Dict[str, str] = {
            _norm(k): v for k, v in self.rules.get("romanization", {}).items()
        }
        # Segmentation inventory. For grapheme/latin output we also admit letters from
        # the ALPHABET row (and any romanization keys), so words segment fully even where
        # the phoneme table omitted a row. IPA output uses only mapped graphemes.
        self._keys = set(self.graphemes)
        if self.output in ("grapheme", "latin"):
            self._keys.update(self.romanization)
            for a in self.rules.get("alphabet", []):
                k = _norm(a)
                if k and not any(unicodedata.combining(c) for c in k):
                    self._keys.add(k)
        self._max_len = max((len(k) for k in self._keys), default=1)

        # Diacritic table: combining codepoint -> IPA suprasegmental suffix.
        self.diacritics: Dict[str, str] = dict(self.rules.get("diacritics", {}))

    # ------------------------------------------------------------------ public
    def convert(self, text: str, *, sep: str = "", lower: bool = True) -> str:
        """Convert a full text string to an IPA string."""
        text = normalize_text(text, lower=lower)
        out: List[str] = []
        for tok in tokenize(text):
            if tok.is_word:
                out.append(self._convert_word(tok.text, sep=sep))
            else:
                out.append(tok.text)
        return "".join(out)

    def convert_word(self, word: str, *, sep: str = "", lower: bool = True) -> str:
        """Convert a single word (no tokenization) to IPA."""
        word = normalize_text(word, lower=lower)
        return self._convert_word(word, sep=sep)

    def phonemes(self, text: str, *, lower: bool = True) -> List[str]:
        """Return a flat list of phoneme units for the text (words only)."""
        text = normalize_text(text, lower=lower)
        units: List[str] = []
        for tok in tokenize(text):
            if tok.is_word:
                units.extend(self._segment(tok.text))
        return units

    # ----------------------------------------------------------------- private
    def _convert_word(self, word: str, *, sep: str) -> str:
        return sep.join(self._segment(word))

    def _segment(self, word: str) -> List[str]:
        """Segment one word into a list of IPA units."""
        text = unicodedata.normalize("NFD", word)
        n = len(text)
        i = 0
        units: List[str] = []
        while i < n:
            match = self._longest_base_match(text, i, n)
            if match is None:
                ch = text[i]
                if unicodedata.combining(ch):
                    # stray combining mark with no base — attach or drop silently
                    i += 1
                    continue
                units.append(self._handle_unknown(ch))
                i += 1
                continue
            base_ipa, length = match
            chunk = text[i:i + length]
            i += length
            # collect trailing combining marks (tone / nasal / length)
            raw = ""
            while i < n and unicodedata.combining(text[i]):
                raw += text[i]
                i += 1
            if self.output == "ipa":
                suffix = "".join(self.diacritics.get(m, "") for m in raw)
                unit = base_ipa + suffix
                units.append(clean_ipa(unit) if self.clean else unit)
            elif self.output == "latin":
                # native-script unit -> Latin form (Latin input maps to itself)
                base = self.romanization.get(chunk, chunk)
                units.append(unicodedata.normalize("NFC", base + raw))
            else:  # grapheme: native writing units, but romanise non-Latin scripts
                # when a Latin mapping exists (Latin-script languages are unaffected).
                base = self.romanization.get(chunk, chunk)
                unit = unicodedata.normalize("NFC", base + raw)
                units.append(clean_ipa(unit) if self.strip_diacritics else unit)
        return units

    def _longest_base_match(self, text: str, i: int, n: int):
        """Longest matching grapheme key at position i.

        Keys may themselves contain combining marks (``ẽ``, ``ɛ̃``, ``e̱``). Those encode a
        *segmental* change that the base-letter + diacritic-suffix model cannot express —
        e.g. gur writes ``ẽ`` -> ``ɛ̃``, a different vowel quality under nasalization, and
        acz writes ``ä`` -> ``ə``. Because keys are stored NFD, such a key only matches if
        combining marks are allowed inside the chunk; skipping them made every one of those
        entries dead data. Longest-match then naturally prefers the composed key over the
        bare base letter, and any marks it consumes are not re-applied as suprasegmentals.

        A chunk may not *start* with a combining mark: that would attach a mark to the
        wrong base, and a stray leading mark is handled by the caller instead.
        """
        upper = min(self._max_len, n - i)
        for length in range(upper, 0, -1):
            chunk = text[i:i + length]
            if unicodedata.combining(chunk[0]):
                continue
            if chunk in self._keys:
                # IPA falls back to the written form for alphabet-only letters
                return self.graphemes.get(chunk, chunk), length
        return None

    def _handle_unknown(self, ch: str) -> str:
        if self.unknown == "drop":
            return ""
        if self.unknown == "mark":
            return "�"
        return ch


def g2p(text: str, lang: str, *, output: str = "grapheme",
        unknown: str = "passthrough", clean: bool = True,
        strip_diacritics: bool = False, **kwargs) -> str:
    """One-shot convenience wrapper: ``g2p("akwaaba", "aka")``.

    Constructor options (output/unknown/clean/strip_diacritics) are accepted here;
    remaining keyword arguments (sep, lower) are passed to ``convert``.
    """
    return G2P(lang, output=output, unknown=unknown, clean=clean,
               strip_diacritics=strip_diacritics).convert(text, **kwargs)
