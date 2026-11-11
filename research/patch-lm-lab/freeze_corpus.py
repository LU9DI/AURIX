"""Congela o corpus (arquivos lidos dos repositorios locais) em corpus_frozen.pkl, que corpus.split() usa
se existir. O pickle NAO e versionado (contem codigo privado); o hash serve de proveniencia.

Uso: python freeze_corpus.py
"""

import hashlib
import pickle

import corpus as C

fs = C.files()
h = hashlib.sha256()
for r, p, b in fs:
    h.update(r.encode() + p.encode() + b)
pickle.dump(fs, open("corpus_frozen.pkl", "wb"))
print(len(fs), "arquivos", sum(len(b) for _, _, b in fs), "bytes", h.hexdigest()[:16])
