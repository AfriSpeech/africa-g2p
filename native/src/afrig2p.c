/*
 * afrig2p — native C port of africa-g2p's runtime conversion paths:
 *   G2P(lang, output="ipa").convert(text, sep)              -> afrig2p_to_ipa
 *   GraphemeConverter(lang, "universal").convert(text, sep) -> afrig2p_to_universal
 *
 * Each static function below mirrors one Python function; the Python name is
 * given in the comment so the two can be reviewed side by side. Table-building
 * logic is NOT ported: tools/export_tables.py dumps the finished tables.
 *
 * Strings are handled as arrays of Unicode code points (Python str semantics:
 * len/index/compare are per code point). Unicode properties and normalisation
 * come from utf8proc.
 */
#define AFRIG2P_BUILDING
#include "afrig2p.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "utf8proc.h"

#define AFRIG2P_VERSION_STR "0.1.0"
#define TIE 0x0361 /* COMBINING DOUBLE INVERTED BREVE, the affricate tie bar */

/* ======================================================================== */
/* memory + code point strings                                              */
/* ======================================================================== */

/* Allocation failure on these small buffers is treated as fatal. */
static void *xrealloc(void *p, size_t n) {
  void *q = realloc(p, n ? n : 1);
  if (!q) abort();
  return q;
}

typedef struct {
  int32_t *v;
  size_t n, cap;
} cps;

static void cps_reserve(cps *s, size_t need) {
  if (need <= s->cap) return;
  size_t c = s->cap ? s->cap * 2 : 16;
  while (c < need) c *= 2;
  s->v = (int32_t *)xrealloc(s->v, c * sizeof(int32_t));
  s->cap = c;
}
static void cps_push(cps *s, int32_t c) {
  cps_reserve(s, s->n + 1);
  s->v[s->n++] = c;
}
static void cps_append(cps *s, const int32_t *v, size_t n) {
  if (!n) return;
  cps_reserve(s, s->n + n);
  memcpy(s->v + s->n, v, n * sizeof(int32_t));
  s->n += n;
}
static void cps_cat(cps *s, const cps *t) { cps_append(s, t->v, t->n); }
static void cps_free(cps *s) {
  free(s->v);
  s->v = NULL;
  s->n = s->cap = 0;
}
static cps cps_from(const int32_t *v, size_t n) {
  cps s = {0};
  cps_append(&s, v, n);
  return s;
}
static void cps_move(cps *dst, cps *src) { /* dst = src; src emptied */
  cps_free(dst);
  *dst = *src;
  src->v = NULL;
  src->n = src->cap = 0;
}
static int cps_eq(const int32_t *a, size_t an, const int32_t *b, size_t bn) {
  return an == bn && (an == 0 || memcmp(a, b, an * sizeof(int32_t)) == 0);
}

typedef struct {
  cps *v;
  size_t n, cap;
} cpslist;

static void list_push(cpslist *l, cps s) { /* takes ownership of s */
  if (l->n == l->cap) {
    l->cap = l->cap ? l->cap * 2 : 8;
    l->v = (cps *)xrealloc(l->v, l->cap * sizeof(cps));
  }
  l->v[l->n++] = s;
}
static void list_free(cpslist *l) {
  for (size_t i = 0; i < l->n; i++) cps_free(&l->v[i]);
  free(l->v);
  l->v = NULL;
  l->n = l->cap = 0;
}
/* sep.join(list) */
static cps list_join(const cpslist *l, const cps *sep) {
  cps out = {0};
  for (size_t i = 0; i < l->n; i++) {
    if (i) cps_cat(&out, sep);
    cps_cat(&out, &l->v[i]);
  }
  return out;
}

/* ======================================================================== */
/* UTF-8 + Unicode helpers (utf8proc)                                       */
/* ======================================================================== */

static int utf8_decode(const char *s, size_t len, cps *out) {
  const utf8proc_uint8_t *p = (const utf8proc_uint8_t *)s;
  size_t i = 0;
  while (i < len) {
    utf8proc_int32_t c;
    utf8proc_ssize_t k =
        utf8proc_iterate(p + i, (utf8proc_ssize_t)(len - i), &c);
    if (k <= 0) return -1;
    cps_push(out, c);
    i += (size_t)k;
  }
  return 0;
}

static char *utf8_encode(const int32_t *v, size_t n, size_t *outlen) {
  char *buf = (char *)xrealloc(NULL, n * 4 + 1);
  size_t k = 0;
  for (size_t i = 0; i < n; i++)
    k += (size_t)utf8proc_encode_char(v[i], (utf8proc_uint8_t *)buf + k);
  buf[k] = 0;
  if (outlen) *outlen = k;
  return buf;
}

/* unicodedata.normalize("NFC"/"NFD", s), in place */
static void normalize_form(cps *s, int nfc) {
  if (s->n == 0) return;
  size_t blen;
  char *b = utf8_encode(s->v, s->n, &blen);
  utf8proc_uint8_t *out = NULL;
  utf8proc_option_t opt = (utf8proc_option_t)(
      UTF8PROC_STABLE | (nfc ? UTF8PROC_COMPOSE : UTF8PROC_DECOMPOSE));
  utf8proc_ssize_t r =
      utf8proc_map((const utf8proc_uint8_t *)b, (utf8proc_ssize_t)blen, &out, opt);
  free(b);
  if (r < 0) abort(); /* input was produced from valid code points */
  s->n = 0;
  if (utf8_decode((const char *)out, (size_t)r, s) != 0) abort();
  free(out);
}
static cps nfd_of(const int32_t *v, size_t n) {
  cps s = cps_from(v, n);
  normalize_form(&s, 0);
  return s;
}
static cps nfc_of(const int32_t *v, size_t n) {
  cps s = cps_from(v, n);
  normalize_form(&s, 1);
  return s;
}

static int ucat(int32_t c) { return (int)utf8proc_category(c); }
/* unicodedata.combining(ch) != 0 */
static int is_combining(int32_t c) {
  return utf8proc_get_property(c)->combining_class != 0;
}
/* str.isalpha() for one char: categories Lu Ll Lt Lm Lo */
static int is_alpha(int32_t c) {
  switch (ucat(c)) {
    case UTF8PROC_CATEGORY_LU: case UTF8PROC_CATEGORY_LL:
    case UTF8PROC_CATEGORY_LT: case UTF8PROC_CATEGORY_LM:
    case UTF8PROC_CATEGORY_LO:
      return 1;
    default:
      return 0;
  }
}
/* re class [^\W\d_]: \w is isalnum()||'_' ; minus \d (Nd) and '_'
 * => letters plus non-decimal numerics (Nl, No). */
static int is_word_letter(int32_t c) {
  if (is_alpha(c)) return 1;
  int k = ucat(c);
  return k == UTF8PROC_CATEGORY_NL || k == UTF8PROC_CATEGORY_NO;
}
/* normalizer._WORD_RE joiner class: ' ’ ʼ plus every Mn/Mc in U+0300..U+FFFF */
static int is_joiner(int32_t c) {
  if (c == 0x27 || c == 0x2019 || c == 0x2BC) return 1;
  if (c >= 0x300 && c <= 0xFFFF) {
    int k = ucat(c);
    return k == UTF8PROC_CATEGORY_MN || k == UTF8PROC_CATEGORY_MC;
  }
  return 0;
}

/* str.lower(): full lowercase mapping. The only unconditional multi-char
 * mapping is U+0130; the context-dependent final sigma is not reproduced. */
static cps lower_of(const int32_t *v, size_t n) {
  cps out = {0};
  for (size_t i = 0; i < n; i++) {
    if (v[i] == 0x130) {
      cps_push(&out, 0x69);
      cps_push(&out, 0x307);
    } else {
      cps_push(&out, utf8proc_tolower(v[i]));
    }
  }
  return out;
}

/* ======================================================================== */
/* hash map: code point string -> code point string (also used as a set)    */
/* ======================================================================== */

typedef struct {
  int32_t *k, *val;
  uint32_t kn, vn;
  int used;
} entry;

typedef struct {
  entry *e;
  size_t cap, count, max_klen;
} map;

static uint64_t hash_cps(const int32_t *k, size_t n) {
  uint64_t h = 1469598103934665603ULL;
  for (size_t i = 0; i < n; i++) {
    h ^= (uint32_t)k[i];
    h *= 1099511628211ULL;
  }
  return h ^ (uint64_t)n;
}

static entry *map_slot(entry *e, size_t cap, const int32_t *k, size_t n) {
  size_t i = (size_t)hash_cps(k, n) & (cap - 1);
  while (e[i].used && !cps_eq(e[i].k, e[i].kn, k, n)) i = (i + 1) & (cap - 1);
  return &e[i];
}

static void map_grow(map *m) {
  size_t ncap = m->cap ? m->cap * 2 : 16;
  entry *ne = (entry *)calloc(ncap, sizeof(entry));
  if (!ne) abort();
  for (size_t i = 0; i < m->cap; i++)
    if (m->e[i].used) *map_slot(ne, ncap, m->e[i].k, m->e[i].kn) = m->e[i];
  free(m->e);
  m->e = ne;
  m->cap = ncap;
}

static void map_put(map *m, const int32_t *k, size_t kn, const int32_t *v, size_t vn) {
  if ((m->count + 1) * 2 > m->cap) map_grow(m);
  entry *s = map_slot(m->e, m->cap, k, kn);
  if (s->used) {
    free(s->val);
  } else {
    s->used = 1;
    s->k = (int32_t *)xrealloc(NULL, (kn ? kn : 1) * sizeof(int32_t));
    if (kn) memcpy(s->k, k, kn * sizeof(int32_t));
    s->kn = (uint32_t)kn;
    m->count++;
    if (kn > m->max_klen) m->max_klen = kn;
  }
  s->val = (int32_t *)xrealloc(NULL, (vn ? vn : 1) * sizeof(int32_t));
  if (vn) memcpy(s->val, v, vn * sizeof(int32_t));
  s->vn = (uint32_t)vn;
}

static const entry *map_get(const map *m, const int32_t *k, size_t kn) {
  if (!m->cap) return NULL;
  entry *s = map_slot(m->e, m->cap, k, kn);
  return s->used ? s : NULL;
}
static const entry *map_get1(const map *m, int32_t c) { return map_get(m, &c, 1); }

static void map_free(map *m) {
  for (size_t i = 0; i < m->cap; i++)
    if (m->e[i].used) {
      free(m->e[i].k);
      free(m->e[i].val);
    }
  free(m->e);
  memset(m, 0, sizeof(*m));
}

/* ======================================================================== */
/* handle                                                                    */
/* ======================================================================== */

struct afrig2p {
  char lang[64];
  int passthrough;
  int has_ipa; /* 0 for plain-Latin languages declared without a rule file */
  map graphemes, diacritics, source_spelling, universal_reverse;
  map fallback_spell, fallback_drop, fallback_ipa, spacing_tone, confusables;
  map accents, ascii_punct, apostrophes, vowels, vowel_alts, aspiration;
  cpslist lig_from, lig_to;   /* ordered */
  cpslist pair_a, pair_b;     /* ordered, each a single code point */
  map english;
  int has_english;
};

const char *afrig2p_version(void) { return AFRIG2P_VERSION_STR; }
const char *afrig2p_language(const afrig2p *g) { return g->lang; }
int afrig2p_has_ipa(const afrig2p *g) { return g->has_ipa; }
void afrig2p_free(void *p) { free(p); }

void afrig2p_destroy(afrig2p *g) {
  if (!g) return;
  map *maps[] = {&g->graphemes, &g->diacritics, &g->source_spelling,
                 &g->universal_reverse, &g->fallback_spell, &g->fallback_drop,
                 &g->fallback_ipa, &g->spacing_tone, &g->confusables,
                 &g->accents, &g->ascii_punct, &g->apostrophes, &g->vowels,
                 &g->vowel_alts, &g->aspiration, &g->english};
  for (size_t i = 0; i < sizeof(maps) / sizeof(maps[0]); i++) map_free(maps[i]);
  list_free(&g->lig_from);
  list_free(&g->lig_to);
  list_free(&g->pair_a);
  list_free(&g->pair_b);
  free(g);
}

/* ---------------------------------------------------------------- loader */

static char *dupstr(const char *s) {
  size_t n = strlen(s) + 1;
  char *d = (char *)xrealloc(NULL, n);
  memcpy(d, s, n);
  return d;
}

static void set_err(char **error, const char *msg, size_t line) {
  if (!error) return;
  char buf[256];
  if (line)
    snprintf(buf, sizeof buf, "afrig2p: %s (line %zu)", msg, line);
  else
    snprintf(buf, sizeof buf, "afrig2p: %s", msg);
  *error = dupstr(buf);
}

/* Undo tools/export_tables.py:esc() and decode UTF-8. */
static int unescape_field(const char *s, size_t n, cps *out) {
  char *buf = (char *)xrealloc(NULL, n + 1);
  size_t k = 0;
  for (size_t i = 0; i < n; i++) {
    if (s[i] == '\\' && i + 1 < n) {
      char c = s[++i];
      buf[k++] = c == 't' ? '\t' : c == 'n' ? '\n' : c == 'r' ? '\r' : c;
    } else {
      buf[k++] = s[i];
    }
  }
  int rc = utf8_decode(buf, k, out);
  free(buf);
  return rc;
}

typedef enum { SEC_NONE, SEC_META, SEC_MAP, SEC_LIST2, SEC_UNKNOWN } sec_kind;

afrig2p *afrig2p_create_from_memory(const char *data, size_t len, char **error) {
  if (error) *error = NULL;
  if (!data) {
    set_err(error, "no data", 0);
    return NULL;
  }
  afrig2p *g = (afrig2p *)calloc(1, sizeof(afrig2p));
  if (!g) abort();
  g->has_ipa = 1;

  struct {
    const char *name;
    map *m;
  } maps[] = {
      {"graphemes", &g->graphemes},
      {"diacritics", &g->diacritics},
      {"source_spelling", &g->source_spelling},
      {"universal_reverse", &g->universal_reverse},
      {"fallback_spell", &g->fallback_spell},
      {"fallback_drop", &g->fallback_drop},
      {"fallback_ipa", &g->fallback_ipa},
      {"spacing_tone", &g->spacing_tone},
      {"confusables", &g->confusables},
      {"orthographic_accents", &g->accents},
      {"ascii_punct", &g->ascii_punct},
      {"apostrophes", &g->apostrophes},
      {"vowels", &g->vowels},
      {"vowel_alternatives", &g->vowel_alts},
      {"aspiration", &g->aspiration},
  };
  const size_t nmaps = sizeof(maps) / sizeof(maps[0]);

  sec_kind kind = SEC_NONE;
  map *cur = NULL;
  cpslist *la = NULL, *lb = NULL;
  int have_magic = 0, have_graphemes = 0, have_universal = 0;
  size_t pos = 0, lineno = 0;

  while (pos < len) {
    size_t end = pos;
    while (end < len && data[end] != '\n') end++;
    const char *line = data + pos;
    size_t ln = end - pos;
    pos = end + 1;
    lineno++;
    if (ln && line[ln - 1] == '\r') ln--;
    if (!have_magic) {
      if (ln < 9 || memcmp(line, "afrig2p 1", 9) != 0) {
        set_err(error, "not an afrig2p v1 data file", lineno);
        goto fail;
      }
      have_magic = 1;
      continue;
    }
    if (ln == 0) continue;
    if (line[0] == '[' && line[ln - 1] == ']') {
      char name[64];
      size_t nn = ln - 2 < sizeof(name) - 1 ? ln - 2 : sizeof(name) - 1;
      memcpy(name, line + 1, nn);
      name[nn] = 0;
      cur = NULL;
      la = lb = NULL;
      kind = SEC_UNKNOWN; /* unknown sections are skipped (forward compat) */
      if (!strcmp(name, "meta")) {
        kind = SEC_META;
      } else if (!strcmp(name, "ligatures")) {
        kind = SEC_LIST2, la = &g->lig_from, lb = &g->lig_to;
      } else if (!strcmp(name, "affricate_pairs")) {
        kind = SEC_LIST2, la = &g->pair_a, lb = &g->pair_b;
      } else {
        for (size_t i = 0; i < nmaps; i++)
          if (!strcmp(name, maps[i].name)) {
            kind = SEC_MAP;
            cur = maps[i].m;
          }
        if (!strcmp(name, "graphemes")) have_graphemes = 1;
        if (!strcmp(name, "universal_reverse")) have_universal = 1;
      }
      continue;
    }
    if (kind == SEC_UNKNOWN) continue;
    if (kind == SEC_NONE) {
      set_err(error, "entry outside a section", lineno);
      goto fail;
    }
    const char *tab = memchr(line, '\t', ln);
    size_t kl = tab ? (size_t)(tab - line) : ln;
    cps k = {0}, v = {0};
    if (unescape_field(line, kl, &k) != 0 ||
        (tab && unescape_field(tab + 1, ln - kl - 1, &v) != 0)) {
      cps_free(&k);
      cps_free(&v);
      set_err(error, "invalid UTF-8", lineno);
      goto fail;
    }
    if (kind == SEC_META) {
      size_t ol;
      char *ks = utf8_encode(k.v, k.n, NULL);
      char *vs = utf8_encode(v.v, v.n, &ol);
      if (!strcmp(ks, "lang")) {
        snprintf(g->lang, sizeof g->lang, "%s", vs);
      } else if (!strcmp(ks, "passthrough")) {
        g->passthrough = (vs[0] == '1');
      } else if (!strcmp(ks, "ipa")) {
        g->has_ipa = (vs[0] == '1');
      }
      free(ks);
      free(vs);
      cps_free(&k);
      cps_free(&v);
    } else if (kind == SEC_MAP) {
      map_put(cur, k.v, k.n, v.v, v.n);
      cps_free(&k);
      cps_free(&v);
    } else { /* SEC_LIST2 */
      list_push(la, k);
      list_push(lb, v);
    }
  }
  if (!have_magic || !have_graphemes || !have_universal) {
    set_err(error, "data file is missing required sections", 0);
    goto fail;
  }
  for (size_t i = 0; i < g->pair_a.n; i++)
    if (g->pair_a.v[i].n != 1 || g->pair_b.v[i].n != 1) {
      set_err(error, "affricate pairs must be single characters", 0);
      goto fail;
    }
  return g;
fail:
  afrig2p_destroy(g);
  return NULL;
}

afrig2p *afrig2p_create_from_file(const char *path, char **error) {
  if (error) *error = NULL;
  FILE *f = fopen(path, "rb");
  if (!f) {
    set_err(error, "cannot open data file", 0);
    return NULL;
  }
  char *buf = NULL;
  size_t n = 0, cap = 0;
  for (;;) {
    if (n == cap) {
      cap = cap ? cap * 2 : 65536;
      buf = (char *)xrealloc(buf, cap);
    }
    size_t r = fread(buf + n, 1, cap - n, f);
    n += r;
    if (r == 0) break;
  }
  fclose(f);
  afrig2p *g = afrig2p_create_from_memory(buf, n, error);
  free(buf);
  return g;
}

/* Python str.strip() whitespace (enough for word-list lines). */
static int is_py_space(int32_t c) {
  if ((c >= 0x09 && c <= 0x0D) || (c >= 0x1C && c <= 0x20) || c == 0x85) return 1;
  int k = ucat(c);
  return k == UTF8PROC_CATEGORY_ZS || k == UTF8PROC_CATEGORY_ZL ||
         k == UTF8PROC_CATEGORY_ZP;
}

int afrig2p_set_english_words(afrig2p *g, const char *data, size_t len) {
  map_free(&g->english);
  g->has_english = 0;
  if (!data) return 0;
  size_t pos = 0;
  while (pos < len) {
    size_t end = pos;
    while (end < len && data[end] != '\n') end++;
    cps w = {0};
    if (utf8_decode(data + pos, end - pos, &w) == 0) {
      size_t a = 0, b = w.n;
      while (a < b && is_py_space(w.v[a])) a++;
      while (b > a && is_py_space(w.v[b - 1])) b--;
      if (b - a >= 3) { /* convert._load_system_dict keeps len >= 3 */
        cps lw = lower_of(w.v + a, b - a);
        map_put(&g->english, lw.v, lw.n, NULL, 0);
        cps_free(&lw);
      }
    }
    cps_free(&w);
    pos = end + 1;
  }
  g->has_english = 1;
  return 0;
}

/* ======================================================================== */
/* normalizer.py                                                             */
/* ======================================================================== */

/* normalize_text(text, lower) : NFC -> fold_confusables -> lower -> NFC */
static cps normalize_text(const afrig2p *g, const int32_t *v, size_t n, int lower) {
  cps t = nfc_of(v, n);
  cps u = {0};
  for (size_t i = 0; i < t.n; i++) {
    const entry *e = map_get1(&g->confusables, t.v[i]);
    if (e)
      cps_append(&u, e->val, e->vn);
    else
      cps_push(&u, t.v[i]);
  }
  cps_free(&t);
  if (lower) {
    cps l = lower_of(u.v, u.n);
    cps_move(&u, &l);
  }
  normalize_form(&u, 1);
  return u;
}

typedef struct {
  size_t start, end;
  int is_word;
} token;

typedef struct {
  token *v;
  size_t n, cap;
} tokens;

static void tok_push(tokens *t, size_t s, size_t e, int w) {
  if (t->n == t->cap) {
    t->cap = t->cap ? t->cap * 2 : 16;
    t->v = (token *)xrealloc(t->v, t->cap * sizeof(token));
  }
  t->v[t->n].start = s;
  t->v[t->n].end = e;
  t->v[t->n].is_word = w;
  t->n++;
}

/* tokenize(text): _WORD_RE = L+ (?:[J] L*)*  ; everything between is non-word */
static tokens tokenize(const cps *s) {
  tokens t = {0};
  size_t i = 0, pos = 0, n = s->n;
  while (i < n) {
    if (!is_word_letter(s->v[i])) {
      i++;
      continue;
    }
    size_t j = i + 1;
    while (j < n && is_word_letter(s->v[j])) j++;
    while (j < n && is_joiner(s->v[j])) {
      j++;
      while (j < n && is_word_letter(s->v[j])) j++;
    }
    if (i > pos) tok_push(&t, pos, i, 0);
    tok_push(&t, i, j, 1);
    pos = i = j;
  }
  if (pos < n) tok_push(&t, pos, n, 0);
  return t;
}

/* clean_ipa(text): NFD, drop orthographic accents, NFC */
static void clean_ipa(const afrig2p *g, cps *s) {
  normalize_form(s, 0);
  size_t k = 0;
  for (size_t i = 0; i < s->n; i++)
    if (!map_get1(&g->accents, s->v[i])) s->v[k++] = s->v[i];
  s->n = k;
  normalize_form(s, 1);
}

/* Replace every occurrence of `from` in s by `to` (str.replace). */
static void replace_all(cps *s, const cps *from, const cps *to) {
  if (from->n == 0 || s->n < from->n) return;
  cps out = {0};
  size_t i = 0;
  while (i < s->n) {
    if (i + from->n <= s->n && cps_eq(s->v + i, from->n, from->v, from->n)) {
      cps_cat(&out, to);
      i += from->n;
    } else {
      cps_push(&out, s->v[i++]);
    }
  }
  cps_move(s, &out);
}

static int in_tie_mark_range(int32_t c) { /* [̀-͢͠-ͯ] */
  return (c >= 0x300 && c <= 0x360) || (c >= 0x362 && c <= 0x36F);
}

/* tie_affricates(ipa) */
static cps tie_affricates(const afrig2p *g, const int32_t *v, size_t n) {
  cps s = cps_from(v, n);
  for (size_t i = 0; i < g->lig_from.n; i++)
    replace_all(&s, &g->lig_from.v[i], &g->lig_to.v[i]);
  for (size_t p = 0; p < g->pair_a.n; p++) {
    int32_t a = g->pair_a.v[p].v[0], b = g->pair_b.v[p].v[0];
    cps out = {0};
    size_t i = 0;
    while (i < s.n) {
      if (s.v[i] == a) {
        size_t j = i + 1;
        while (j < s.n && in_tie_mark_range(s.v[j])) j++;
        if (j < s.n && s.v[j] == b) {
          cps_append(&out, s.v + i, j - i); /* a + marks */
          cps_push(&out, TIE);
          cps_push(&out, b);
          i = j + 1;
          continue;
        }
      }
      cps_push(&out, s.v[i++]);
    }
    cps_move(&s, &out);
  }
  return s;
}

/* ======================================================================== */
/* fallback.py + g2p.py (output="ipa", clean=True, fallback=True,           */
/*                       unknown="passthrough")                             */
/* ======================================================================== */

/* fallback_ipa(char): FALLBACK_IPA.get(char) or FALLBACK_IPA.get(char.lower()) */
static const entry *fallback_ipa(const afrig2p *g, const int32_t *v, size_t n) {
  const entry *e = map_get(&g->fallback_ipa, v, n);
  if (e && e->vn > 0) return e; /* truthy */
  cps l = lower_of(v, n);
  e = map_get(&g->fallback_ipa, l.v, l.n);
  cps_free(&l);
  return e;
}

/* G2P._segment(word) */
static void segment(const afrig2p *g, const int32_t *w, size_t wn, cpslist *units) {
  cps t = nfd_of(w, wn);
  size_t n = t.n, i = 0;
  while (i < n) {
    /* _longest_base_match */
    const entry *m = NULL;
    size_t mlen = 0;
    if (!is_combining(t.v[i])) {
      size_t upper = g->graphemes.max_klen < n - i ? g->graphemes.max_klen : n - i;
      for (size_t L = upper; L >= 1; L--) {
        const entry *e = map_get(&g->graphemes, t.v + i, L);
        if (e) {
          m = e;
          mlen = L;
          break;
        }
      }
    }
    if (!m) {
      int32_t ch = t.v[i];
      if (map_get1(&g->spacing_tone, ch) && !map_get1(&g->graphemes, ch)) {
        i++;
        continue;
      }
      if (is_combining(ch)) {
        i++;
        continue;
      }
      const entry *sub = fallback_ipa(g, &ch, 1);
      list_push(units, sub ? cps_from(sub->val, sub->vn) : cps_from(&ch, 1));
      i++;
      continue;
    }
    size_t cstart = i;
    i += mlen;
    cps base = cps_from(m->val, m->vn);
    cps raw = {0};
    while (i < n && is_combining(t.v[i])) cps_push(&raw, t.v[i++]);

    cps stray = {0};
    for (size_t r = 0; r < raw.n; r++)
      if (!map_get1(&g->diacritics, raw.v[r])) cps_push(&stray, raw.v[r]);
    if (stray.n) {
      cps probe = cps_from(t.v + cstart, mlen);
      cps_cat(&probe, &stray);
      normalize_form(&probe, 1);
      const entry *sub = fallback_ipa(g, probe.v, probe.n);
      cps_free(&probe);
      if (sub) {
        cps nb = cps_from(sub->val, sub->vn);
        cps_move(&base, &nb);
        cps kept = {0};
        for (size_t r = 0; r < raw.n; r++)
          if (map_get1(&g->diacritics, raw.v[r])) cps_push(&kept, raw.v[r]);
        cps_move(&raw, &kept);
      }
    }
    cps_free(&stray);
    for (size_t r = 0; r < raw.n; r++) {
      const entry *d = map_get1(&g->diacritics, raw.v[r]);
      if (d) cps_append(&base, d->val, d->vn);
    }
    cps_free(&raw);
    clean_ipa(g, &base);
    list_push(units, base);
  }
  cps_free(&t);
}

/* ======================================================================== */
/* convert.py — GraphemeConverter(lang, "universal")                        */
/* ======================================================================== */

/* _non_latin_script(ch) */
static int non_latin_script(int32_t o) {
  return (0x1200 <= o && o <= 0x137F) || (0x0600 <= o && o <= 0x06FF) ||
         (0x0750 <= o && o <= 0x077F) || (0x08A0 <= o && o <= 0x08FF) ||
         (0xFB50 <= o && o <= 0xFDFF) || (0xFE70 <= o && o <= 0xFEFF) ||
         (0xA500 <= o && o <= 0xA63F) || (0x07C0 <= o && o <= 0x07FF) ||
         (0x2D30 <= o && o <= 0x2D7F) || (0x0400 <= o && o <= 0x04FF) ||
         (0x2C80 <= o && o <= 0x2CFF) || (0x1360 <= o && o <= 0x137F);
}

/* _romanise(text) */
static cps romanise(const afrig2p *g, const int32_t *v, size_t n) {
  cps out = {0};
  for (size_t i = 0; i < n; i++) {
    int32_t ch = v[i];
    if (map_get1(&g->fallback_drop, ch)) continue;
    if (non_latin_script(ch)) {
      const entry *e = map_get1(&g->fallback_spell, ch);
      if (e)
        cps_append(&out, e->val, e->vn);
      else
        cps_push(&out, ch);
    } else {
      cps_push(&out, ch);
    }
  }
  return out;
}

/* strip_apostrophes(text) */
static cps strip_apostrophes(const afrig2p *g, const cps *s) {
  cps out = {0};
  for (size_t i = 0; i < s->n; i++)
    if (!map_get1(&g->apostrophes, s->v[i])) cps_push(&out, s->v[i]);
  return out;
}

/* _drop_marks(text): NFD, drop combining, NFC */
static cps drop_marks(const cps *s) {
  cps t = nfd_of(s->v, s->n);
  size_t k = 0;
  for (size_t i = 0; i < t.n; i++)
    if (!is_combining(t.v[i])) t.v[k++] = t.v[i];
  t.n = k;
  normalize_form(&t, 1);
  return t;
}

/* _apply_fallback(text) */
static cps apply_fallback(const afrig2p *g, const cps *s) {
  if (g->fallback_spell.count == 0) return cps_from(s->v, s->n);
  cps out = {0};
  for (size_t i = 0; i < s->n; i++) {
    int32_t ch = s->v[i];
    const entry *e;
    if (map_get1(&g->fallback_drop, ch)) continue;
    if (ch < 128) {
      cps_push(&out, ch);
    } else if ((e = map_get1(&g->fallback_spell, ch)) != NULL) {
      cps_append(&out, e->val, e->vn);
    } else if ((e = map_get1(&g->ascii_punct, ch)) != NULL) {
      cps_append(&out, e->val, e->vn);
    } else if (!is_alpha(ch)) {
      continue;
    } else {
      cps_push(&out, ch);
    }
  }
  return out;
}

/* _is_english_word(word) with an explicit word list */
static int is_english_word(const afrig2p *g, const int32_t *v, size_t n) {
  if (!g->has_english || n < 3) return 0;
  for (size_t i = 0; i < n; i++)
    if (v[i] >= 128 || !is_alpha(v[i])) return 0; /* isascii() and isalpha() */
  cps l = lower_of(v, n);
  int hit = map_get(&g->english, l.v, l.n) != NULL;
  cps_free(&l);
  return hit;
}

/* _strip_combining(text): NFD, drop combining marks and Lm / Sk */
static cps strip_combining(const int32_t *v, size_t n) {
  cps t = nfd_of(v, n);
  size_t k = 0;
  for (size_t i = 0; i < t.n; i++) {
    int c = ucat(t.v[i]);
    if (!is_combining(t.v[i]) && c != UTF8PROC_CATEGORY_LM && c != UTF8PROC_CATEGORY_SK)
      t.v[k++] = t.v[i];
  }
  t.n = k;
  return t;
}

/* GraphemeConverter._map(ipa) for target == "universal". Returns grapheme in
 * *out (owned by caller) and sets *converted. */
static void map_unit(const afrig2p *g, const cps *ipa, cps *out, int *converted) {
  const map *rev = &g->universal_reverse;
  cps relaxed = {0}; /* _relax_aspiration */
  for (size_t i = 0; i < ipa->n; i++)
    if (!map_get1(&g->aspiration, ipa->v[i])) cps_push(&relaxed, ipa->v[i]);

  const entry *e = map_get(rev, relaxed.v, relaxed.n);
  if (!e) e = map_get(rev, ipa->v, ipa->n);
  if (!e) {
    cps base = strip_combining(ipa->v, ipa->n);
    if (ipa->n && !base.n) {
      cps_free(&base);
      cps_free(&relaxed);
      *out = (cps){0};
      *converted = 1;
      return;
    }
    if (base.n && !cps_eq(base.v, base.n, ipa->v, ipa->n)) {
      e = map_get(rev, base.v, base.n);
      if (!e) {
        cps b2 = strip_combining(relaxed.v, relaxed.n);
        e = map_get(rev, b2.v, b2.n);
        cps_free(&b2);
      }
    }
    cps_free(&base);
  }
  cps_free(&relaxed);
  if (!e) {
    *out = cps_from(ipa->v, ipa->n);
    *converted = 0;
    return;
  }
  *out = cps_from(e->val, e->vn);
  if (g->source_spelling.count == 0) {
    *converted = 0;
    return;
  }
  cps tied = tie_affricates(g, ipa->v, ipa->n);
  const entry *src = map_get(&g->source_spelling, tied.v, tied.n);
  cps_free(&tied);
  *converted = !(src && cps_eq(src->val, src->vn, e->val, e->vn));
}

/* alternatives.get(v, "u" if v in "oɔ" else "i") */
static int32_t vowel_alt(const afrig2p *g, int32_t v) {
  const entry *e = map_get1(&g->vowel_alts, v);
  if (e && e->vn == 1) return e->val[0];
  return (v == 'o' || v == 0x254) ? 'u' : 'i';
}

/* GraphemeConverter._map_units(units) */
static cpslist map_units(const afrig2p *g, const cpslist *units) {
  cpslist mapped = {0};
  cps prev_g = {0}, prev_ipa = {0};
  int have_prev = 0; /* prev_g is not None */
  for (size_t u = 0; u < units->n; u++) {
    const cps *ipa = &units->v[u];
    cps gr;
    int converted;
    map_unit(g, ipa, &gr, &converted);

    if (converted && gr.n >= 2 && map_get1(&g->vowels, gr.v[0])) {
      int same = 1; /* len(set(g)) == 1 */
      for (size_t i = 1; i < gr.n; i++)
        if (gr.v[i] != gr.v[0]) same = 0;
      if (same) {
        cps ng = {0};
        cps_push(&ng, vowel_alt(g, gr.v[0]));
        cps_push(&ng, gr.v[0]);
        cps_move(&gr, &ng);
      }
    }
    int collision = have_prev && cps_eq(gr.v, gr.n, prev_g.v, prev_g.n) &&
                    !cps_eq(ipa->v, ipa->n, prev_ipa.v, prev_ipa.n);
    if (collision && gr.n && map_get1(&g->vowels, gr.v[0])) {
      if (mapped.n) {
        cps *last = &mapped.v[mapped.n - 1];
        if (last->n && map_get1(&g->vowels, last->v[last->n - 1]))
          last->v[last->n - 1] = vowel_alt(g, last->v[last->n - 1]);
      }
      list_push(&mapped, gr);
    } else {
      if (!have_prev || !cps_eq(gr.v, gr.n, prev_g.v, prev_g.n)) {
        cps a = cps_from(gr.v, gr.n), b = cps_from(ipa->v, ipa->n);
        cps_move(&prev_g, &a);
        cps_move(&prev_ipa, &b);
        have_prev = 1;
      } else {
        cps b = cps_from(ipa->v, ipa->n);
        cps_move(&prev_ipa, &b);
      }
      list_push(&mapped, gr);
    }
  }
  cps_free(&prev_g);
  cps_free(&prev_ipa);
  return mapped;
}

/* self._forward.convert_word(word, sep=" ", lower=False).split(" ") */
static cpslist forward_units(const afrig2p *g, const int32_t *w, size_t n) {
  cps word = normalize_text(g, w, n, 0);
  cpslist seg = {0};
  segment(g, word.v, word.n, &seg);
  cps_free(&word);
  int32_t sp = ' ';
  cps space = {&sp, 1, 1};
  cps joined = list_join(&seg, &space);
  list_free(&seg);
  cpslist out = {0};
  size_t start = 0;
  for (size_t i = 0; i <= joined.n; i++)
    if (i == joined.n || joined.v[i] == ' ') {
      list_push(&out, cps_from(joined.v + start, i - start));
      start = i + 1;
    }
  cps_free(&joined);
  return out;
}

/* ======================================================================== */
/* public conversion API                                                     */
/* ======================================================================== */

static int decode_args(const char *text, const char *sep, cps *in, cps *sp) {
  if (!text) return -1;
  if (utf8_decode(text, strlen(text), in) != 0) return -1;
  if (sep && utf8_decode(sep, strlen(sep), sp) != 0) return -1;
  return 0;
}

static char *finish(cps *s) {
  char *r = utf8_encode(s->v, s->n, NULL);
  cps_free(s);
  return r;
}

/* GraphemeConverter(lang, "universal").convert(text, sep=sep) */
char *afrig2p_to_universal(const afrig2p *g, const char *text, const char *sep) {
  cps in = {0}, sp = {0};
  if (!g || decode_args(text, sep, &in, &sp) != 0) {
    cps_free(&in);
    cps_free(&sp);
    return NULL;
  }
  cps t = normalize_text(g, in.v, in.n, 1);
  cps_free(&in);

  if (g->passthrough) {
    cps a = drop_marks(&t);
    cps b = strip_apostrophes(g, &a);
    cps c = apply_fallback(g, &b);
    cps_free(&a);
    cps_free(&b);
    cps_free(&t);
    cps_free(&sp);
    return finish(&c);
  }

  cps out = {0};
  tokens toks = tokenize(&t);
  for (size_t k = 0; k < toks.n; k++) {
    const int32_t *v = t.v + toks.v[k].start;
    size_t n = toks.v[k].end - toks.v[k].start;
    if (!toks.v[k].is_word || is_english_word(g, v, n)) {
      cps_append(&out, v, n);
      continue;
    }
    int nonlatin = 0;
    for (size_t i = 0; i < n && !nonlatin; i++) nonlatin = non_latin_script(v[i]);
    if (nonlatin) {
      cps r = romanise(g, v, n);
      cps_cat(&out, &r);
      cps_free(&r);
      continue;
    }
    cpslist units = forward_units(g, v, n);
    cpslist mapped = map_units(g, &units);
    cps j = list_join(&mapped, &sp);
    cps_cat(&out, &j);
    cps_free(&j);
    list_free(&units);
    list_free(&mapped);
  }
  free(toks.v);
  cps_free(&t);
  cps_free(&sp);

  cps r = romanise(g, out.v, out.n);
  cps a = strip_apostrophes(g, &r);
  cps c = apply_fallback(g, &a);
  cps_free(&out);
  cps_free(&r);
  cps_free(&a);
  return finish(&c);
}

/* G2P(lang, output="ipa").convert(text, sep=sep) */
char *afrig2p_to_ipa(const afrig2p *g, const char *text, const char *sep) {
  cps in = {0}, sp = {0};
  if (!g || !g->has_ipa || decode_args(text, sep, &in, &sp) != 0) {
    cps_free(&in);
    cps_free(&sp);
    return NULL;
  }
  cps t = normalize_text(g, in.v, in.n, 1);
  cps_free(&in);
  cps out = {0};
  tokens toks = tokenize(&t);
  for (size_t k = 0; k < toks.n; k++) {
    const int32_t *v = t.v + toks.v[k].start;
    size_t n = toks.v[k].end - toks.v[k].start;
    if (!toks.v[k].is_word) {
      cps_append(&out, v, n);
      continue;
    }
    cpslist seg = {0};
    segment(g, v, n, &seg);
    cps j = list_join(&seg, &sp);
    cps_cat(&out, &j);
    cps_free(&j);
    list_free(&seg);
  }
  free(toks.v);
  cps_free(&t);
  cps_free(&sp);
  return finish(&out);
}
