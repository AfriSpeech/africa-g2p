# Changelog

## 0.3.2

### A mark no longer falls back on its own Unicode name

uroman returns a character's name when it has nothing phonetic to give, and
three Arabic marks took it:

    U+065C  ARABIC VOWEL SIGN DOT BELOW            -> "dot"
    U+0653  ARABIC MADDAH ABOVE                    -> "maddah"
    U+065B  ARABIC VOWEL SIGN INVERTED SMALL V     -> "v"

A Fulfulde sentence came out `asamanji dot ldotsdi`, so a TTS engine would read
"dot" aloud mid-sentence.

A mark is now rejected when its romanisation is a word from its own name --
exactly the wrong cases and none of the right ones, since fatha still gives
"a", damma "u" and kasra "i". The check is asserted over the whole table, so
regenerating cannot reintroduce the class.

It applies to marks only: for a letter, spelling a word from its own name is
usually correct, and applying it there would have rejected 729 good entries.

## 0.3.1

### Universal output is ASCII, not merely free of non-ASCII letters

An IPA unit the survey has no spelling for passes through whole, tie bar and
all, so `ntsaa` came out with a combining tie bar between every consonant. The
check meant to catch that asked `isalpha()`, and a tie bar is a mark rather
than a letter, so it went straight through -- as did punctuation, which is how
Ethiopic sentence marks and a hundred corpora's guillemets survived too.

Measured across 684 languages on real corpus text:

    non-ASCII characters in universal output   3076 -> 0
    languages affected                         100+ -> 0

- A tie bar, undertie, tone bar, modifier letter, invisible formatting
  character or private-use character is written as nothing.
- Typographic punctuation folds to its ASCII equivalent: guillemets to a
  quote, a non-breaking hyphen to `-`, an inverted question mark to `?`.
- A letter is still kept rather than dropped, so a gap in the tables shows up
  instead of silently deleting words.

Proxy escapes these instead of folding them, since it has to return exactly
what it was given; it had been passing non-ASCII punctuation through
unescaped, which broke its own a-z guarantee.

Reported from a downstream project, which found 123 clips across 11 languages
carrying the tie bar.

## 0.3.0

### `proxy`: write any orthography in plain a-z, and read it back exactly

`universal` spells a sound the way most languages spell it, which makes text
from different languages comparable and loses the difference between Twi `/o/`
and `/ɔ/`. The new `proxy` target keeps everything, by one rule that is the
same in every language: an a-z letter stands for itself, a literal `x` doubles
to `xx`, and anything else is written `x…x`.

```python
convert_lang("Onyankopɔn", "twi", PROXY)    # 'onyankopxoxn'
convert_lang("onyankopxoxn", PROXY, "twi")  # 'onyankopɔn'
```

Reading it back is a scan, so nothing can be misread: 565 of 565 languages
round-trip exactly, every character, measured on real corpus text. A character
with no table entry encodes from its codepoint, so even a letter no rule table
lists still comes back.

### Non-Latin scripts are romanised by uroman

Deriving a whole script letter by letter from our own tables produced a
romanisation nobody uses — Amharic `ክርስቶስ` came out `kirisitosi`. uroman is
context-free over these scripts, so its output is baked into a lookup table and
the library still installs with no dependencies.

```
0.2.4   ወንጌል ማቴዎስ ሦራ፣ ልጆች።  ->  wenugelu matewosi sora፣ lujochi።
0.3.0   ወንጌል ማቴዎስ ሦራ፣ ልጆች።  ->  wanegeele maateewose soraa, lejoche.
```

This also fixes Ethiopic punctuation passing through unconverted, and the
Arabic vowel points being dropped — `يَوْم` was `ywm`, now `yawm`. They are
vowels rather than tone marks, and uroman writes them as letters.

### `normalize_text` normalises last

It applied NFC first and then folded confusables and lowercased, either of
which can leave a string denormalised again, so two canonically identical
strings could compare unequal. This affects every caller.

## 0.2.4

### Collision avoidance no longer injects a schwa

When two different phonemes land on the same target vowel, the earlier one is
rewritten to a near neighbour so the pair stays distinguishable. The neighbour
for `a` was `ə`, which put a schwa into universal output where the source had
none:

```
0.2.3   Unimbɔti ... náań  ->  unimboti ... nəan
0.2.4   Unimbɔti ... náań  ->  unimboti ... nean
```

The universal target now uses a plain-letter neighbour table. Real-language
targets are unchanged: a language that writes `ə` should still get it.

## 0.2.3

### Tone-marked vowels reach the universal orthography

Source orthographies write tone on the vowel, and the marked form is absent from
the survey, so it fell through to passthrough — and once normalisation stripped
the accent, a bare `ɔ` or `ɛ` was left in universal output. Those are exactly the
characters universal exists to remove:

```
0.2.2   lɔ́lɔndai ... ɣɛ́i  ->  lɔlondai ... ghɛi
0.2.3   lɔ́lɔndai ... ɣɛ́i  ->  lolondai ... ghei
```

An unmapped phoneme now retries on its base letters, with combining marks, tone
bars (`˥ ˦ ˧`) and secondary-articulation modifiers (`ˤ ˠ`) removed — none of
which the universal orthography writes. A unit that is nothing but a modifier
writes as nothing.

Yoruba shows the size of it: `Ní ìbẹ̀rẹ̀, nígbà` was `ngi˥ i˩bɛ˩rɛ˩, ngi˥gbä˩` and
is now `ngi ibere, ngigba`.

Across 215 languages this cut stray non-letter characters in universal output
from 18 distinct to 4, the rest being genuine per-language chart gaps (Ethiopic
and Vai syllables with no rule).

## 0.2.2

### The glottal stop is written as nothing, not as `q`

0.2.1 banned apostrophes from the universal orthography, and the glottal stop `ʔ`
— attested in 114 languages, spelled with an apostrophe in 80 of its ~110 votes —
fell through to the next Latin vote, `q`, on 4 votes. But `q` already spells the
postalveolar click, so a glottal stop was written as a letter that reads as a
click or a uvular stop:

```
0.2.1   dunman'n  ->  dunmanqn
0.2.2   dunman'n  ->  dunmann
```

No a-z letter is realised as a glottal stop by a speech model, so it is left
unwritten. `ʔ`, `∅` and `ː` now map to the empty string rather than being absent
from the table: an absent phoneme falls through as unknown and the raw IPA symbol
lands in the text (`dunmanʔn`), which is worse than either.

## 0.2.1

### The universal orthography is plain letters again (#12)

238 of the 2,063 universal grapheme entries wrote a character that is not a plain
letter, and 214 of those were apostrophes marking ejectives and glottals. Speech
synthesisers read an apostrophe as a pause, so Xhosa came out wrong:

```
0.2.0   ukuba nikwazi ukucalula  ->  uk'uba nik'wazi uk'ucalula
0.2.1   ukuba nikwazi ukucalula  ->  ukuba nikwazi ukucalula
```

Also fixed at the source: non-Latin winners now use an attested Latin vote where
one existed (`n-g` -> `ng`, Vai `ꕨ ꔜ ꕁ ꖍ ꖲ` -> `nyja nyje nyji nyjo nyju`); the
`VV` placeholder and the Arabic alef that won the null phoneme `∅` are dropped;
and the 13 clicks with no attested Latin spelling were approximated in plain
letters (`ʘ` -> `p`, `ʘʰ` -> `ph`), the way Zulu and Xhosa orthographies write
clicks as `c`, `q`, `x`.

Ejectives and clicks now share a spelling with their plain consonant. That is the
cost of a plain-letter orthography; `output="ipa"` still carries every contrast.

Each revised entry keeps its previous value in `grapheme_original`, and
`africa_g2p.convert.universal_non_alphabetic()` reports anything that is not
plain letters (empty today, and warned about if a future table regresses).

### `__version__` is no longer stale

It read `0.1.0` through the 0.1.1 and 0.2.0 releases, so anything recording it —
a dataset card, a provenance log — wrote down the wrong version. It is now read
from the installed package metadata.

## 0.2.0

Output changes. Anyone pinning 0.1.1 will get different phonemes from the same input, so
this is a minor bump rather than a patch — every item below was producing plausible-looking
output that was wrong, which is why they survived this long.

### Punctuation is kept (#11)

`phonemes()` emitted word tokens only, so every mark was dropped:

```
0.1.1   ṣé o wà?  ->  ʃ e˥ o w ä˩
0.2.0   ṣé o wà?  ->  ʃ e˥ o w ä˩ ?
```

Forced alignment needs the marks to place pauses, TTS needs them for phrasing, and an ASR
model trained on stripped targets can never learn to emit them. Pass `punctuation=False`
for the old behaviour. Only Unicode punctuation is emitted — not digits, whitespace, or a
combining mark with no base. The apostrophe is unaffected: in these orthographies it is a
glottal stop, and the tokenizer already treats it as a letter.

### One spelling per affricate (#10)

126 of the 400 rule tables wrote `tʃ` where the rest wrote `t͡ʃ`, and a few carried the
ligature `ʧ`. Same sound, three symbols — measured over 141 languages, `t͡ʃ` and `tʃ`
appeared as separate units 134,581 and 70,142 times, splitting one phoneme's probability
mass across two model output classes. Values are normalised at load, so `tʃ`, `ʧ` and
`t͡ʃ` all yield `t͡ʃ`. Grapheme output is untouched.

### Kabuverdianu read letter names (#10)

Its Omniglot extraction captured the chart's alphabet-recitation column, so every consonant
carried its Portuguese *name*: `kaza` came out as `ˈkapɐ a ze a` rather than `kaza`.
Replaced with ALUPEC values. A sweep of all 400 tables found no other case — the eleven
others mapping single characters to CV syllables are genuine syllabaries.

### Clicks, tone bars and borrowed IPA letters (#8, #9)

- Orthographies borrow IPA letters to write those sounds, but charts list them only where
  they are phonemic for that language: 251 of 400 tables had no entry for `ɛ`, 214 none for
  `ŋ`. They now read as themselves.
- Khoekhoe, Nama and Damara write clicks with the IPA click letters. No Latin chart carries
  them, so every click language looked unphonemisable.
- Dot-below is segmental in Yoruba, Igbo and Edoid. Under NFD the base matched alone and
  the mark was discarded as decoration, so `ẹgbẹ` produced the wrong vowel twice over
  rather than an error.
- Kru orthographies mark tone with a raised bar beside the syllable. Being spacing
  characters they never attach to a base, so each counted as an unknown grapheme — tone
  notation alone put Attié at 0.86 coverage.

## 0.1.1

English G2P via espeak-ng, and fallback readings for letters a chart omits.
