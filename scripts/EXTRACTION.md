# Vision extraction contract

The source PDF (`Alphabets of Africa`, Hartell 1993) is a scanned document. Its text
layer is unusable for the phoneme tables (`pdftotext` turns `/p/` into `Ipl`), so each
language page is read from its **rendered PNG** (`extraction/pages/p-NNN.png`) by a
vision model and written as one JSON file in `extraction/raw/p-NNN.json`.

## Page layout (per language)

```
COUNTRY                                    LANGUAGE NAME   (FAMILY)
PHONEMES AND ORTHOGRAPHIC SYMBOLS                          EXAMPLES
  /p/   p     /m/  m    /f/  f              a  jakuma  cat
  /b/   b     ...       ...                 b  bamuso  mother
  ...                                       ...
Tones: ...
ALPHABET
a b c d e ɛ f g gb h ...                   number of graphemes  30
```

- The **left block** is `/phoneme/ → orthographic symbol(s)` pairs. The orthographic
  symbol is the **grapheme**; the value between slashes is the phoneme. Invert to get the
  G2P mapping (grapheme → phoneme).
- Multigraphs matter: `kp`, `gb`, `ny`, `ŋ`, `gh`, `sh`, etc.
- Tones/nasalization/length appear as diacritics or as a `Tones:` note.
- The **ALPHABET** row lists the canonical ordered alphabet.
- **EXAMPLES** column: grapheme word + English gloss.

## Output JSON schema (one object per page)

```json
{
  "page": 40,
  "is_language_page": true,
  "language": "Dioula (Jula)",
  "iso639_3": "dyu",
  "country": "Côte d'Ivoire",
  "family": "Mande",
  "graphemes": [
    {"phoneme": "p",  "grapheme": "p"},
    {"phoneme": "ɲ",  "grapheme": "ny"},
    {"phoneme": "k͡p", "grapheme": "kp"}
  ],
  "diacritics": [
    {"mark": "U+0301", "role": "high tone", "ipa": "˥"}
  ],
  "tones": {"high": "acute (first syllable only)", "low": "unmarked"},
  "alphabet": ["a","b","c","d","e","ɛ","f","g","gb","h","..."],
  "examples": [{"word": "jakuma", "gloss": "cat"}],
  "num_graphemes": 30,
  "confidence": "high|medium|low",
  "notes": "free text: ambiguities, unreadable cells, contextual rules"
}
```

Rules for the extractor:
- `phoneme` MUST be a valid IPA rendering (convert Hartell's `/ty/`, `/dy/`, `/Ṽ/`
  notations to IPA; note the choice in `notes` when ambiguous).
- If the page is a divider / TOC / continuation with no phoneme table, set
  `is_language_page: false` and leave the rest empty.
- Propose the ISO 639-3 code in `iso639_3`; if unsure, best guess + note it.
- Never invent rows you cannot read — lower `confidence` and add a `notes` entry instead.

`scripts/build_rules.py` compiles these raw files into validated language rule files.
