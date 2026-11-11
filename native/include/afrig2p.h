/*
 * afrig2p — native C port of africa-g2p (https://github.com/AfriSpeech/africa-g2p)
 *
 * Converts text in an African language orthography to
 *   - the "universal" orthography (GraphemeConverter(lang, "universal")), or
 *   - IPA (G2P(lang, output="ipa")),
 * producing byte-identical output to the Python package for the same data.
 *
 * Tables are not hard-coded: they are exported from the Python package by
 * tools/export_tables.py into one self-contained <lang>.afg2p file.
 *
 * Thread safety: a handle is immutable after creation (and after
 * afrig2p_set_english_words); conversion functions may be called concurrently.
 */
#ifndef AFRIG2P_H
#define AFRIG2P_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32) && defined(AFRIG2P_SHARED)
#  ifdef AFRIG2P_BUILDING
#    define AFRIG2P_API __declspec(dllexport)
#  else
#    define AFRIG2P_API __declspec(dllimport)
#  endif
#elif defined(__GNUC__)
#  define AFRIG2P_API __attribute__((visibility("default")))
#else
#  define AFRIG2P_API
#endif

typedef struct afrig2p afrig2p;

/* Library version string, e.g. "0.1.0". */
AFRIG2P_API const char *afrig2p_version(void);

/* Load a language from a .afg2p file / an in-memory copy of one (e.g. an
 * Android asset). On failure returns NULL and, if `error` is non-NULL, stores a
 * malloc'd message there (release with afrig2p_free). */
AFRIG2P_API afrig2p *afrig2p_create_from_file(const char *path, char **error);
AFRIG2P_API afrig2p *afrig2p_create_from_memory(const char *data, size_t len,
                                                char **error);
AFRIG2P_API void afrig2p_destroy(afrig2p *g);

/* ISO 639-3 code of the loaded language. */
AFRIG2P_API const char *afrig2p_language(const afrig2p *g);

/* 1 if the language has an IPA table. Plain-Latin languages declared without a
 * rule file support universal output only; afrig2p_to_ipa returns NULL for them. */
AFRIG2P_API int afrig2p_has_ipa(const afrig2p *g);

/* English-loanword skip for universal output, and code-switching dictionary for IPA output.
 *
 * Pass a TSV formatted list ("word\tipa\n...") or newline-separated word list ("word\n...").
 * In IPA mode (afrig2p_to_ipa), any word or phrase matching an entry with an IPA value is
 * replaced with its English IPA.
 * In universal mode (afrig2p_to_universal), words matching the list are left unconverted.
 * Pass NULL to disable (the default). Returns 0 on success. Not thread-safe w.r.t. conversions. */
AFRIG2P_API int afrig2p_set_english_words(afrig2p *g, const char *data, size_t len);

/* Convert UTF-8 text. `sep` (UTF-8, may be NULL meaning "") joins the units
 * inside a word, exactly like the Python `sep` argument; word boundaries
 * (spaces, punctuation) are always preserved. Returns a malloc'd UTF-8 string
 * (release with afrig2p_free), or NULL on invalid UTF-8 input (and, for
 * afrig2p_to_ipa, when the language has no IPA table). */
AFRIG2P_API char *afrig2p_to_universal(const afrig2p *g, const char *text,
                                       const char *sep);
AFRIG2P_API char *afrig2p_to_ipa(const afrig2p *g, const char *text,
                                 const char *sep);

AFRIG2P_API void afrig2p_free(void *p);

#ifdef __cplusplus
}
#endif

#endif /* AFRIG2P_H */
