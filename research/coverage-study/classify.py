"""Classifica cada hunk de um repo git em: determinavel (sem modelo) vs. logica nova.
Heuristicas conservadoras e auditaveis; sem modelo, sem GPU."""

import json
import re
import subprocess
import sys
from collections import Counter, defaultdict

CODE = (".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".sql", ".sh", ".css")
DATA = (".json", ".yml", ".yaml", ".toml", ".env", ".example", ".lock", ".txt")
DOC = (".md",)
IMPORT = re.compile(
    r"^\s*(import\b|from\s+\S+\s+import\b|export\s+\*|export\s*\{.*\}\s*from|(const|let|var)\s+.*=\s*require\(|use\s+\S+;|#include)"
)
COMMENT = re.compile(r"^\s*(//|#|\*|/\*|\*/|--)")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STR = re.compile(r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`[^`]*`)""")
NUM = re.compile(r"\b\d+(?:\.\d+)?\b")
KW = {
    "if",
    "else",
    "elif",
    "for",
    "while",
    "return",
    "def",
    "class",
    "import",
    "from",
    "as",
    "in",
    "is",
    "not",
    "and",
    "or",
    "try",
    "except",
    "finally",
    "with",
    "raise",
    "lambda",
    "yield",
    "await",
    "async",
    "function",
    "const",
    "let",
    "var",
    "new",
    "this",
    "throw",
    "catch",
    "switch",
    "case",
    "break",
    "continue",
    "export",
    "default",
    "fn",
    "pub",
    "use",
    "mod",
    "impl",
    "struct",
    "enum",
    "match",
}


def shape(line):
    s = STR.sub("S", line)
    s = NUM.sub("N", s)
    s = IDENT.sub(lambda m: m.group(0) if m.group(0) in KW or m.group(0) in "SN" else "I", s)
    return re.sub(r"\s+", "", s)


def classify(path, dele, add):
    if path.endswith(DOC):
        return "docs"
    if path.endswith(DATA) or "/migrations/" in path:
        return "config_dados"
    if not path.endswith(CODE):
        return "outro"
    d = [x for x in dele if x.strip()]
    a = [x for x in add if x.strip()]
    if not d and not a:
        return "formatacao"
    if "".join("".join(d).split()) == "".join("".join(a).split()):
        return "formatacao"
    ch = d + a
    if all(COMMENT.match(x) for x in ch):
        return "comentario"
    if all(IMPORT.match(x) for x in ch):
        return "import"
    if d and not a:
        return "remocao_pura"
    if d and len(d) == len(a) and [shape(x) for x in d] == [shape(x) for x in a]:
        return "renomear_ou_ajustar_literal"
    if "test" in path.lower() or "spec" in path.lower():
        return "teste_novo"
    return "logica_nova"


DETERMINISTIC = {
    "formatacao",
    "comentario",
    "import",
    "remocao_pura",
    "renomear_ou_ajustar_literal",
}


def hunks(repo):
    cmd = ["git", "-C", repo, "log", "--no-merges", "-p", "-U0", "--format=@@C %H\t%s"]
    out = subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=True).stdout
    commit = msg = path = None
    add = []
    dele = []
    old_path = None

    def flush():
        nonlocal add, dele
        if commit and path and (add or dele):
            r = (commit, msg, path, dele, add)
        else:
            r = None
        add, dele = [], []
        return r

    for line in out.splitlines():
        if line.startswith("@@C "):
            r = flush()
            if r:
                yield r
            commit, msg = line[4:].split("\t", 1)
            path = None
        elif line.startswith("--- "):
            r = flush()
            if r:
                yield r
            old_path = line[6:] if line.startswith("--- a/") else None
        elif line.startswith("+++ "):
            r = flush()
            if r:
                yield r
            if line.startswith("+++ b/"):
                path = line[6:]
            elif line == "+++ /dev/null":
                # Deleted files have no new path; retain the old path.
                path = old_path
            else:
                path = None
        elif line.startswith("@@ "):
            r = flush()
            if r:
                yield r
        elif path and line.startswith("+") and not line.startswith("+++"):
            add.append(line[1:])
        elif path and line.startswith("-") and not line.startswith("---"):
            dele.append(line[1:])
    r = flush()
    if r:
        yield r


def main(repo):
    hk = Counter()
    lines = Counter()
    percommit = defaultdict(set)
    msgs = {}
    for commit, msg, path, dele, add in hunks(repo):
        k = classify(path, dele, add)
        hk[k] += 1
        lines[k] += len(add) + len(dele)
        percommit[commit].add(k)
        msgs[commit] = msg
    th = sum(hk.values())
    tl = sum(lines.values())
    code_h = {k: v for k, v in hk.items() if k not in ("docs", "config_dados", "outro")}
    ch = sum(code_h.values())
    det = sum(v for k, v in code_h.items() if k in DETERMINISTIC)
    ncommit = len(percommit)
    codec = [c for c, ks in percommit.items() if ks & (set(code_h))]
    fullcode = sum(1 for c in codec if percommit[c] & set(code_h) <= DETERMINISTIC)
    print(
        json.dumps(
            {
                "repo": repo.split("/")[-1],
                "commits": ncommit,
                "hunks": th,
                "linhas": tl,
                "hunks_por_tipo": dict(hk),
                "linhas_por_tipo": dict(lines),
                "hunks_codigo": ch,
                "hunks_codigo_deterministicos": det,
                "pct_hunks_codigo_det": round(100 * det / max(ch, 1), 1),
                "pct_linhas_codigo_det": round(
                    100
                    * sum(v for k, v in lines.items() if k in DETERMINISTIC)
                    / max(
                        sum(
                            v
                            for k, v in lines.items()
                            if k not in ("docs", "config_dados", "outro")
                        ),
                        1,
                    ),
                    1,
                ),
                "commits_com_codigo": len(codec),
                "commits_codigo_100pct_det": fullcode,
                "pct_commits_codigo_100pct_det": round(100 * fullcode / max(len(codec), 1), 1),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: classify.py REPO")
    main(sys.argv[1])
