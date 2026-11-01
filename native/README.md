# afrig2p: native C library for africa-g2p

A C port of africa-g2p's conversion paths, for on-device use (e.g. next to
[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) on Android/iOS). No Python at runtime,
no dictionary, no GPL code.

| C function | Python equivalent |
|---|---|
| `afrig2p_to_universal(g, text, sep)` | `GraphemeConverter(lang, "universal").convert(text, sep=sep)` |
| `afrig2p_to_ipa(g, text, sep)` | `G2P(lang, output="ipa").convert(text, sep=sep)` |

Output is **byte-identical** to the Python package, for every language.

## How it stays in sync with the Python package

The C engine lives in this repository and is never maintained separately:

- **Tables are generated, never hand-copied.** `tools/export_tables.py` imports the Python
  package from `../src` and writes the finished runtime tables (per-language grapheme tables,
  the universal spelling table, fallbacks, normaliser constants) to `data/<lang>.afg2p`. Each
  file records the commit it was built from (`africa_g2p_commit`). Change a rule file or a
  universal spelling in Python, re-export, and the C side picks it up with no code change.
- **CI enforces parity on every pull request** (`.github/workflows/ci.yml`, job
  `native-parity`). It builds the C library, exports all ~870 languages from that commit, and
  checks that C output equals Python output for universal and IPA modes, both separators, on
  each language's showcase text, edge cases and random input. A sanitizer pass runs too. If a
  change to the Python *conversion logic* (not just data) alters output, this job fails until
  `src/afrig2p.c` is updated to match, so the two cannot drift apart.
- `data/` is a build product (git-ignored). CI uploads it as the `afrig2p-data` artifact.

Each static function in `src/afrig2p.c` names the Python function it mirrors, so a logic change
in `convert.py`, `g2p.py` or `normalizer.py` maps directly to the C function to update.

## Build

```bash
cmake -S native -B native/build && cmake --build native/build -j
python3 native/tools/export_tables.py --all          # or: twi fat ewe gaa dag
echo "Me din de Kwame. Ɛte sɛn?" | native/build/afrig2p -d native/data/twi.afg2p     # me din de kwame. ete sen?
echo "Onyankopɔn" | native/build/afrig2p -d native/data/twi.afg2p -s " "             # o ny a n k o p o n
echo "Ɛte sɛn?"   | native/build/afrig2p -d native/data/twi.afg2p -m ipa -s " "      # ɛ t e s ɛ n?
python3 native/tests/parity.py --all --fuzz 200      # what CI runs
```

**Android** (NDK):
```bash
cmake -S native -B native/build-android \
  -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-21 -DAFRIG2P_BUILD_CLI=OFF
cmake --build native/build-android
```
Ship the `.afg2p` file as an asset and load it with `afrig2p_create_from_memory`.

**iOS**:
```bash
cmake -S native -B native/build-ios -G Xcode -DCMAKE_SYSTEM_NAME=iOS \
  -DAFRIG2P_BUILD_SHARED=OFF -DAFRIG2P_BUILD_CLI=OFF
cmake --build native/build-ios --config Release
```

## C API

```c
#include "afrig2p.h"
char *err = NULL;
afrig2p *g = afrig2p_create_from_file("twi.afg2p", &err);
char *u = afrig2p_to_universal(g, "Ɛte sɛn?", "");   /* "ete sen?" */
afrig2p_free(u);
afrig2p_destroy(g);
```
Handles are read-only after creation, so conversions are thread-safe. About 120 plain-Latin
languages have no IPA table (`afrig2p_has_ipa` returns 0, `afrig2p_to_ipa` returns NULL). That
matches Python, where `G2P` raises for them.

## Python binding (preparing training data)

`python/afrig2p.py` calls the same C library through ctypes, so text prepared for training and
text converted on the device go through identical code:
```python
import sys; sys.path.insert(0, "native/python")
from afrig2p import Afrig2p
g = Afrig2p("native/data/twi.afg2p")
g.universal("Me din de Kwame.")        # 'me din de kwame.'
```

## Differences from the Python package, by design

- **English-loanword skip is off.** Python leaves a word unconverted when it appears in whatever
  English dictionary is installed on the machine (`pyspellchecker` or `/usr/share/dict/words`),
  so its output depends on the machine. Here every word is converted. An explicit list can be
  given with `afrig2p_set_english_words`, and the parity test pins both sides to the same rule.
- Python's context-dependent final-sigma lowercasing (Greek) is not reproduced.
- Unicode tables come from utf8proc 2.9.0 (Unicode 15.1), so only characters added after the
  running Python's Unicode version could behave differently.
- Out-of-memory aborts the process.

## Licensing

utf8proc: MIT (`third_party/utf8proc/LICENSE.md`). The generated tables are derived from this
repository's data; see `../DATA_LICENSE.md`.
