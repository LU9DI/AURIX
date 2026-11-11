import os

import pytest

pytest.importorskip("numpy")

from aurix.providers.factory import create_provider
from aurix.providers.ngram import NgramModel, NgramProvider, collect_corpus

SNIPPET = (
    "def total_price(items):\n"
    "    total = 0\n"
    "    for item in items:\n"
    "        total += item.price * item.quantity\n"
    "    return total\n"
)


def _project(tmp_path):
    (tmp_path / "shop.py").write_text(SNIPPET * 3 + "\n\nclass Cart:\n    pass\n")
    return tmp_path


def test_continues_a_pattern_present_in_the_corpus(tmp_path):
    provider = NgramProvider(_project(tmp_path), order=12, max_output_bytes=200)
    out = provider.generate("def total_price(items):\n    total = 0\n    for item in items:\n")
    assert out.startswith("        total += item.price * item.quantity\n    return total")


def test_generation_is_deterministic_without_a_seed(tmp_path):
    provider = NgramProvider(_project(tmp_path), order=5)
    prompt = "def total_price("
    assert provider.generate(prompt) == provider.generate(prompt)


def test_seeded_sampling_is_reproducible(tmp_path):
    root = _project(tmp_path)
    a = NgramProvider(root, order=4, seed=7).generate("def ", system="ignored")
    b = NgramProvider(root, order=4, seed=7).generate("def ", system="ignored")
    assert a == b


def test_output_is_bounded(tmp_path):
    provider = NgramProvider(_project(tmp_path), max_output_bytes=10_000_000)
    assert provider.max_output_bytes == 4096
    assert len(NgramProvider(_project(tmp_path), max_output_bytes=5).generate("def")) <= 5


def test_corpus_does_not_follow_symlinks_or_read_skipped_dirs(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("SECRET = 'do-not-learn'\n")
    root = tmp_path / "project"
    root.mkdir()
    (root / "ok.py").write_text("print('ok')\n")
    (root / "linked.py").symlink_to(outside / "secret.py")
    (root / "linkdir").symlink_to(outside, target_is_directory=True)
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.js").write_text("module.exports = 1\n")
    corpus = collect_corpus(root)
    assert b"print('ok')" in corpus
    assert b"do-not-learn" not in corpus
    assert b"module.exports" not in corpus


def test_corpus_respects_size_caps_and_skips_non_utf8(tmp_path):
    (tmp_path / "big.py").write_text("x = 1\n" * 100_000)
    (tmp_path / "bin.py").write_bytes(b"\xff\xfe\x00bad")
    (tmp_path / "small.py").write_text("y = 2\n")
    corpus = collect_corpus(tmp_path, max_file_bytes=1000)
    assert corpus == b"y = 2\n"


def test_empty_workspace_fails_closed(tmp_path):
    with pytest.raises(RuntimeError, match="no readable source files"):
        NgramProvider(tmp_path).generate("x")


def test_model_rejects_bad_parameters():
    with pytest.raises(ValueError):
        NgramModel(b"")
    with pytest.raises(ValueError):
        NgramModel(b"abc", order=17)
    with pytest.raises(ValueError):
        NgramModel(b"abc", discount=1.5)


def test_bits_per_byte_is_lower_on_familiar_text_than_on_noise():
    model = NgramModel((SNIPPET * 20).encode(), order=5)
    familiar = model.bits_per_byte(SNIPPET.encode())
    noise = model.bits_per_byte(bytes(range(33, 123)) * 2)
    assert familiar < 1.0 < noise


def test_distribution_is_a_probability_vector():
    model = NgramModel((SNIPPET * 5).encode(), order=4)
    dist = model.next_distribution(b"def tot")
    assert dist.shape == (256,)
    assert abs(float(dist.sum()) - 1.0) < 1e-9
    assert bytes([int(dist.argmax())]) == b"a"


def test_factory_builds_the_cpu_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("AURIX_PROVIDER", "ngram")
    monkeypatch.setenv("AURIX_NGRAM_ROOT", str(tmp_path))
    assert isinstance(create_provider(), NgramProvider)
    assert os.getenv("AURIX_PROVIDER") == "ngram"


def test_long_contexts_use_hash_and_stay_consistent_between_paths():
    model = NgramModel((SNIPPET * 20).encode(), order=12)
    history = SNIPPET.encode()[:60]
    dist = model.next_distribution(history)
    assert abs(float(dist.sum()) - 1.0) < 1e-9
    # the scalar (generation) path and the vectorised (scoring) path must agree on contexts
    ctx_vec = model._contexts(__import__("numpy").frombuffer(history + b"x", dtype="uint8"), 12)[-1]
    assert int(ctx_vec) == model._context_value(history, 12)


def test_indentation_longer_than_the_context_is_resolved_by_long_orders(tmp_path):
    root = _project(tmp_path)
    low = NgramProvider(root, order=6, max_output_bytes=60).generate("for item in items:\n")
    high = NgramProvider(root, order=12, max_output_bytes=60).generate("for item in items:\n")
    assert high.lstrip(" ").startswith("total +=")
    assert len(low.strip()) == 0 or not low.lstrip(" ").startswith("total +=")


def test_hashed_contexts_do_not_collide_when_only_one_byte_differs():
    model = NgramModel(b"abcdefghij" * 50, order=10)
    for position in (0, 4, 9):  # vary the last, a middle and the first byte of the context
        ids = set()
        for value in range(256):
            ctx = bytearray(range(20, 30))
            ctx[position] = value
            ids.add(model._context_value(bytes(ctx), 10))
        assert len(ids) == 256



def test_corpus_skip_directory_policy_is_case_insensitive(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("SAFE = True\n")
    for dirname, filename, content in (
        (".GIT", "history.py", "LEAK_GIT = True\n"),
        ("Node_Modules", "dependency.js", "LEAK_DEP = True\n"),
        (".VENV", "installed.py", "LEAK_VENV = True\n"),
    ):
        folder = root / dirname
        folder.mkdir()
        (folder / filename).write_text(content)

    corpus = collect_corpus(root)

    assert b"SAFE = True" in corpus
    assert b"LEAK_GIT" not in corpus
    assert b"LEAK_DEP" not in corpus
    assert b"LEAK_VENV" not in corpus


def test_corpus_source_extension_matching_is_case_insensitive(tmp_path):
    (tmp_path / "UPPER.PY").write_text("def upper_case(): pass\n")
    assert b"upper_case" in collect_corpus(tmp_path)


def test_corpus_total_size_cap_includes_inter_file_separators(tmp_path):
    (tmp_path / "a.py").write_bytes(b"12345")
    (tmp_path / "b.py").write_bytes(b"67890")
    (tmp_path / "c.py").write_bytes(b"abcde")

    corpus = collect_corpus(tmp_path, max_file_bytes=100, max_total_bytes=12)

    assert corpus == b"12345"
    assert len(corpus) <= 12
