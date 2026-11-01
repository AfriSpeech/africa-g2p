#!/usr/bin/env python3
"""Print deterministic random text lines for sanitizer runs: python3 make_fuzz.py [N] [SEED]."""
import random
import sys

sys.path.insert(0, __import__("os").path.dirname(__file__))
from parity import EDGE_CASES, fuzz_lines  # same character pool as the parity test

n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
seed = int(sys.argv[2]) if len(sys.argv) > 2 else 7
for line in EDGE_CASES + fuzz_lines(n, seed):
    print(line.replace("\n", " "))
