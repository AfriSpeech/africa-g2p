# Data sources & licensing

The **code** in this repository is licensed under Apache-2.0 (see `LICENSE`). The
**linguistic data** in `src/africa_g2p/languages/` is derived from third-party sources and
is provided for research and language-technology use. Please retain the attributions below.

## Sources

### Omniglot script charts — © Simon Ager
Language rule files with `"confidence": "omniglot"` are derived from the writing-system
charts published on [Omniglot](https://www.omniglot.com/) (© Simon Ager). Each such file
records its source chart in its `"source"` field. We extract only the factual
grapheme ↔ IPA ↔ romanisation correspondences (not Omniglot's prose, images, or page
layout). Omniglot content is copyrighted; this project uses these factual correspondences
with attribution and is not affiliated with or endorsed by Omniglot. If you are the
rights-holder and have any concern about this use, please open an issue and we will respond
promptly.

### Alphabets of Africa (Hartell, ed.) — © UNESCO 1993
Language rule files sourced from Rhonda L. Hartell (ed.), *Alphabets of Africa*
(UNESCO / SIL, Dakar, 1993). Recorded in each file's `"source"` field as "Hartell 1993".

### afriso — ISO 639-3 + Glottolog
Language metadata (canonical codes, families, regions, alternative names) via
[afriso](https://github.com/AfriSpeech/afriso), built from SIL ISO 639-3 tables and
Glottolog (CC-BY 4.0).

### africa-corpus — public Bible translations
Example sentences in the README showcase come from
[africa-corpus](https://github.com/AfriSpeech/africa-corpus-builder).

## Using the data

If you redistribute the language data, keep these attributions and this notice. For any
use beyond research/attention that the original rights-holders' terms may restrict, obtain
permission from the respective source.
