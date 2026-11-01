/* afrig2p command-line tool: converts stdin line by line.
 *
 *   afrig2p -d data/twi.afg2p [-m universal|ipa] [-s SEP] [-e english.txt] < in.txt
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "afrig2p.h"

static char *read_file(const char *path, size_t *len) {
  FILE *f = fopen(path, "rb");
  if (!f) return NULL;
  fseek(f, 0, SEEK_END);
  long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  char *buf = malloc((size_t)n + 1);
  if (!buf || fread(buf, 1, (size_t)n, f) != (size_t)n) {
    fclose(f);
    free(buf);
    return NULL;
  }
  fclose(f);
  *len = (size_t)n;
  return buf;
}

static void usage(void) {
  fprintf(stderr,
          "usage: afrig2p -d LANG.afg2p [-m universal|ipa] [-s SEP] [-e WORDS]\n"
          "  reads UTF-8 lines on stdin, writes converted lines on stdout\n"
          "  -s SEP    separator between units inside a word (default: none)\n"
          "  -e WORDS  English word list: such words are left unconverted\n");
}

int main(int argc, char **argv) {
  const char *data = NULL, *mode = "universal", *sep = "", *eng = NULL;
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "-d") && i + 1 < argc) data = argv[++i];
    else if (!strcmp(argv[i], "-m") && i + 1 < argc) mode = argv[++i];
    else if (!strcmp(argv[i], "-s") && i + 1 < argc) sep = argv[++i];
    else if (!strcmp(argv[i], "-e") && i + 1 < argc) eng = argv[++i];
    else if (!strcmp(argv[i], "--version")) {
      printf("afrig2p %s\n", afrig2p_version());
      return 0;
    } else {
      usage();
      return 2;
    }
  }
  if (!data) {
    usage();
    return 2;
  }
  int ipa = !strcmp(mode, "ipa");
  if (!ipa && strcmp(mode, "universal")) {
    usage();
    return 2;
  }
  char *err = NULL;
  afrig2p *g = afrig2p_create_from_file(data, &err);
  if (!g) {
    fprintf(stderr, "%s\n", err ? err : "afrig2p: load failed");
    afrig2p_free(err);
    return 1;
  }
  if (ipa && !afrig2p_has_ipa(g)) {
    fprintf(stderr, "afrig2p: %s has no IPA table (universal output only)\n",
            afrig2p_language(g));
    afrig2p_destroy(g);
    return 3;
  }
  if (eng) {
    size_t n;
    char *w = read_file(eng, &n);
    if (!w) {
      fprintf(stderr, "afrig2p: cannot read %s\n", eng);
      return 1;
    }
    afrig2p_set_english_words(g, w, n);
    free(w);
  }
  char *line = NULL;
  size_t cap = 0, n = 0;
  int c, rc = 0;
  for (;;) {
    n = 0;
    while ((c = getchar()) != EOF && c != '\n') {
      if (n + 2 > cap) {
        cap = cap ? cap * 2 : 1024;
        line = realloc(line, cap);
        if (!line) abort();
      }
      line[n++] = (char)c;
    }
    if (c == EOF && n == 0) break;
    if (!line) {
      line = malloc(1);
      if (!line) abort();
    }
    line[n] = 0;
    char *out = ipa ? afrig2p_to_ipa(g, line, sep) : afrig2p_to_universal(g, line, sep);
    if (out) {
      fputs(out, stdout);
      afrig2p_free(out);
    } else {
      fprintf(stderr, "afrig2p: invalid UTF-8 input\n");
      rc = 1;
    }
    fputc('\n', stdout);
    if (c == EOF) break;
  }
  free(line);
  afrig2p_destroy(g);
  return rc;
}
