# africa-g2p

Rule-based **grapheme-to-phoneme (G2P)** conversion for African languages — text in,
[IPA](https://en.wikipedia.org/wiki/International_Phonetic_Alphabet) out — for use in
text-to-speech, pronunciation lexicons, and linguistic tooling.

Inspired by [sea-g2p](https://github.com/pnnbao97/sea-g2p) (Southeast Asian languages),
but pure Python and driven by per-language rule files. The phoneme/orthography data is
sourced from Rhonda L. Hartell's **_Alphabets of Africa_** (UNESCO/BREDA, 1993), which
documents the orthographies of ~120 African languages.

## Why rule-based?

The orthographies in Hartell are largely **shallow (phonemic)** — spelling maps to sound
fairly directly. So G2P is well handled by:

1. Unicode normalization + tokenization
2. Greedy **longest-match multigraph** segmentation (`kp`, `gb`, `ny`, `gh` …)
3. A per-language **grapheme → IPA** table
4. Combining marks (tone, nasalization, length) mapped as suprasegmentals

No neural model, no training data, deterministic output.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```python
from africa_g2p import AfricaPipeline

pipe = AfricaPipeline(lang="dyu")      # Dioula / Jula
pipe.run("jakuma bɛ sogo dun")         # -> IPA string

# one-shot
from africa_g2p import g2p
g2p("nyini", "dyu", sep=" ")           # 'ɲ i n i'
```

CLI:

```bash
africa-g2p --list                       # list supported languages
africa-g2p dyu "jakuma sogo"            # convert
```

## Language rule files

Each language is one JSON file in `src/africa_g2p/languages/<iso639-3>.json`:

```json
{
  "code": "dyu",
  "name": "Dioula (Jula)",
  "country": "Côte d'Ivoire",
  "family": "Mande",
  "source": "Hartell 1993, p. 30",
  "confidence": "hand-verified",
  "graphemes": { "kp": "k͡p", "ny": "ɲ", "c": "tʲ", "…": "…" },
  "diacritics": { "́": "˥" },
  "tones": { "high": "acute", "low": "unmarked" },
  "alphabet": ["a", "b", "c", "…"],
  "examples": [{ "word": "jakuma", "gloss": "cat" }]
}
```

`confidence` is one of `hand-verified`, `extracted` (vision-extracted, unreviewed), or
`draft`.

## Building the data (extraction pipeline)

The source PDF is a scanned document; its text layer is unusable for the phoneme tables
(`pdftotext` turns `/p/` into `Ipl`), so data is **vision-extracted** from page images:

```bash
python scripts/render_pages.py                 # PDF -> extraction/pages/*.png

export GEMINI_API_KEY=...                       # never commit this
python scripts/gemini_extract.py                # pages -> extraction/raw/*.json (Gemini vision)

python scripts/build_rules.py                   # raw JSON -> validated language rule files
python scripts/qa.py                            # validate: IPA sanity, counts, example round-trips
```

The extractor follows `scripts/EXTRACTION.md` and emits one JSON object per page. Pages
that are covers/TOC/dividers are auto-skipped (`is_language_page: false`). Each extraction
was validated against a hand-verified page (Dioula) — 27/30 graphemes identical, the rest
equivalent IPA choices.

## Status

**138 languages** extracted from Hartell and compiled into rule files (136 high-confidence,
1 hand-verified, 1 medium). **98.5%** of the source's own ~4,200 example words round-trip
through the engine with no unmapped characters; the remainder are flagged by `scripts/qa.py`
for review (mostly individual phoneme rows the 1993 source page omitted). Engine, pipeline,
CLI, and 16 tests are in place.

Coverage reflects Hartell's UNESCO/BREDA (Dakar) volume — strong on West, Central, and East
African orthographies (Akan, Yoruba, Hausa, Ga, Dagbani, Wolof, Luganda, Dioula, …). Southern
African languages (e.g. Zulu) are outside its scope.

Run `africa-g2p --list` for the full language inventory.

## License

Apache-2.0. Source data © UNESCO 1993 (Hartell, *Alphabets of Africa*).
