# Changelog

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
