"""Python binding for the afrig2p C library (ctypes, no build step).

Use this — not the upstream africa_g2p package — to prepare training text, so
training and on-device inference run the *same* code and cannot drift apart.
The English-loanword skip is off: every word is converted.

    from afrig2p import Afrig2p
    g = Afrig2p("data/twi.afg2p")                  # finds libafrig2p automatically
    g.universal("Me din de Kwame.")                # 'me din de kwame.'
    g.universal("Onyankopɔn", sep=" ")             # 'o ny a n k o p o n'
    g.ipa("Ɛte sɛn?", sep=" ")
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

_LIB_NAMES = {"darwin": "libafrig2p.dylib", "win32": "afrig2p.dll"}


def _find_lib() -> str:
    env = os.environ.get("AFRIG2P_LIB")
    if env:
        return env
    name = _LIB_NAMES.get(sys.platform, "libafrig2p.so")
    here = Path(__file__).resolve().parent
    for cand in (here / name, here.parent / "build" / name):
        if cand.exists():
            return str(cand)
    return name  # let the dynamic loader search


class Afrig2p:
    _lib = None

    @classmethod
    def _load_lib(cls, path: str | None):
        if cls._lib is None or path:
            lib = ctypes.CDLL(path or _find_lib())
            lib.afrig2p_create_from_file.restype = ctypes.c_void_p
            lib.afrig2p_create_from_file.argtypes = [ctypes.c_char_p,
                                                     ctypes.POINTER(ctypes.c_void_p)]
            for fn in (lib.afrig2p_to_universal, lib.afrig2p_to_ipa):
                fn.restype = ctypes.c_void_p
                fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
            lib.afrig2p_free.argtypes = [ctypes.c_void_p]
            lib.afrig2p_destroy.argtypes = [ctypes.c_void_p]
            lib.afrig2p_version.restype = ctypes.c_char_p
            cls._lib = lib
        return cls._lib

    def __init__(self, data_path: str | os.PathLike, lib_path: str | None = None):
        self._l = self._load_lib(lib_path)
        err = ctypes.c_void_p()
        self._h = self._l.afrig2p_create_from_file(os.fsencode(data_path),
                                                   ctypes.byref(err))
        if not self._h:
            msg = ctypes.string_at(err.value).decode() if err.value else "load failed"
            if err.value:
                self._l.afrig2p_free(err)
            raise RuntimeError(msg)

    def _call(self, fn, text: str, sep: str) -> str:
        p = fn(self._h, text.encode("utf-8"), sep.encode("utf-8"))
        if not p:
            raise ValueError("afrig2p: invalid input")
        try:
            return ctypes.string_at(p).decode("utf-8")
        finally:
            self._l.afrig2p_free(p)

    def universal(self, text: str, sep: str = "") -> str:
        return self._call(self._l.afrig2p_to_universal, text, sep)

    def ipa(self, text: str, sep: str = "") -> str:
        return self._call(self._l.afrig2p_to_ipa, text, sep)

    @property
    def version(self) -> str:
        return self._l.afrig2p_version().decode()

    def close(self):
        if getattr(self, "_h", None):
            self._l.afrig2p_destroy(self._h)
            self._h = None

    __del__ = close
