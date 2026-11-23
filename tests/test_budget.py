import pytest

from ariadne.budget import Chunk, condense, cost_usd, estimate_tokens, parse_budget, render


@pytest.mark.parametrize("raw,expected", [("20k", 20_000), ("1.5m", 1_500_000), ("8000", 8000), (" 12K ", 12_000)])
def test_parse_budget(raw, expected):
    assert parse_budget(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "10x", "500"])
def test_parse_budget_rejects(raw):
    with pytest.raises(ValueError):
        parse_budget(raw)


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 35) == 10


def test_condense_respects_budget_and_prefers_relevant():
    chunks = [Chunk(f"noise{i}.js", "x = 1\n" * 400) for i in range(30)]
    chunks.append(Chunk("src/auth.js", "function login() { checkToken() }\n" * 20))
    kept, dropped = condense(chunks, 2000, "how does login work?")
    assert kept[0].source == "src/auth.js"
    assert estimate_tokens(render(kept)) <= 2000
    assert dropped > 0


def test_condense_truncates_last_chunk_instead_of_wasting_room():
    big = Chunk("big.py", "y" * 100_000)
    kept, _ = condense([big], 3000, "q")
    assert len(kept) == 1 and kept[0].text.endswith("[cortado pelo budget]")
    assert estimate_tokens(render(kept)) <= 3000


def test_weight_breaks_ties():
    a, b = Chunk("a", "same text", 1.0), Chunk("b", "same text", 3.0)
    kept, _ = condense([a, b], 5000, "unrelated")
    assert kept[0].source == "b"


def test_cost():
    assert cost_usd("claude-sonnet-5-5", 1_000_000, 0) == pytest.approx(2.0)
    assert cost_usd("unknown-model", 10, 10) is None
