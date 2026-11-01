# afrig2p TTS phoneme convention (v1)

Rule files marked `"confidence": "tts-reviewed"` follow this one convention, so every
language produces phonemes in the same format for a single multilingual TTS model.
`scripts/validate_tts_convention.py` and `tests/test_tts_convention.py` enforce the
machine-checkable parts.

## 1. One table value = one phoneme
- Every value in `graphemes` is exactly **one phoneme** (one segment), never a syllable,
  diphthong or sequence. `si → ʃi`, `ia → ia`, `oa → ʷia` are not allowed.
- A grapheme whose reading would be several phonemes is **removed** from the table, so its
  letters are read one by one. Allophonic, context-dependent spellings (e.g. Ewe `si`/`tsi`
  palatalisation) are removed for the same reason: they are handled by the model, not the table.
- **Vowel sequences and doubled vowels** are not table entries. `aa`, `ii`, `oo`, `ia`, `ue` ...
  are removed and read letter by letter (`aa → a a`). This keeps length consistent across languages.

## 2. Broad (phonemic) transcription
- Transcribe the **phoneme**, not its phonetic realisation. No aspiration (`ʰ`), no
  allophonic detail, no syllabic marks, no stress, no tone letters.
- **Vowels** take the value of the written vowel letter. ATR / vowel-harmony distinctions
  the orthography does not write are not invented: `i → i`, `u → u`, `e → e`, `o → o`,
  `ɛ → ɛ`, `ɔ → ɔ`, `a → a` (not `ɪ`, `ʊ`, `eː` ...).
- **Tone is not written** (the orthographies do not mark it). Tone diacritics in input text
  are dropped.

## 3. Symbols
- Unicode IPA only, NFC. No orthographic letters standing in for IPA (`y` is `j`, `ƒ` is `ɸ`).
- Voiced velar stop is `ɡ` (U+0261), never ASCII `g`.
- Affricates and doubly articulated stops use the tie bar U+0361:
  `t͡s d͡z t͡ʃ d͡ʒ t͡ɕ d͡ʑ k͡p ɡ͡b ŋ͡m`. No ligatures (`ʧ ʤ ʦ ʣ ʨ ʥ`), no untied pairs.
- Secondary articulation is a single modifier after the consonant: labialised `ʷ`,
  palatalised `ʲ`. Nothing before the consonant, at most one modifier.
- Nasal vowels: vowel + combining tilde U+0303 (`ã ẽ ĩ õ ũ ɛ̃ ɔ̃`). A nasalisation mark
  written in the orthography maps to U+0303 in `diacritics`.
- Rhotics: use the symbol the language's phonology uses (`r` trill or `ɾ` tap), the same one
  for every entry in that language.

## 4. Same sound, same symbol, in every language
If two languages have the same phoneme, both tables use the identical symbol string.
Reviewed cross-language choices:

| sound | symbol |
|---|---|
| palatal nasal (`ny`) | `ɲ` |
| velar nasal (`ŋ`, `ng`) | `ŋ` |
| labial-velar stops (`kp`, `gb`) | `k͡p`, `ɡ͡b` |
| labial-velar nasal (`ŋm`) | `ŋ͡m` |
| alveolar affricates (`ts`, `dz`) | `t͡s`, `d͡z` |
| postalveolar affricates | `t͡ʃ`, `d͡ʒ` |
| alveolo-palatal (Akan `ky`, `gy`) | `t͡ɕ`, `d͡ʑ` |
| Ewe `ʋ` | `β` |
| Ewe `ƒ` | `ɸ` |
| `y` | `j` |

## 5. Coverage
Every letter and multigraph of the language's standard orthography that denotes a single
phoneme has an entry; nothing in the alphabet is left to fallbacks.
