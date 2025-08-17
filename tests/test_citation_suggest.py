import os
import sys
import pytest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app


def test_suggest_citations_multiword(monkeypatch):
    sentence = "The quick brown fox jumps over the lazy dog"
    captured = {"calls": []}

    def fake_works(**kwargs):
        captured["calls"].append(kwargs)
        # Return no results when queried with the full sentence to trigger the
        # fallback behaviour.
        if kwargs["query_bibliographic"] == sentence:
            return {"message": {"items": []}}
        # The fallback query should use the longest unique words.
        assert kwargs["query_bibliographic"] == "quick brown jumps"
        return {"message": {"items": [{"DOI": "10.1234/abc"}]}}

    def fake_get(url, timeout=10):
        return SimpleNamespace(status_code=200, text="@article{a,title={T}}")

    monkeypatch.setattr(app.cr, "works", fake_works)
    monkeypatch.setattr(app.requests, "get", fake_get)

    results = app.suggest_citations(sentence)
    assert sentence in results
    # Ensure two calls were made: full sentence then fallback sample words
    assert captured["calls"][1]["query_bibliographic"] == "quick brown jumps"
    assert captured["calls"][1]["query_language"] == "en"


@pytest.mark.parametrize(
    "sentence,lang",
    [
        ("The quick brown fox jumps over the lazy dog.", "en"),
        ("빠른 갈색 여우가 게으른 개를 뛰어넘는다.", "ko"),
        ("素早い茶色の狐が怠惰な犬を飛び越える。", "ja"),
        ("La science avance rapidement.", "fr"),
        ("Der schnelle braune Fuchs springt über den faulen Hund.", "de"),
    ],
)
def test_suggest_citations_detects_language(monkeypatch, sentence, lang):
    captured = {}

    def fake_works(**kwargs):
        captured["kwargs"] = kwargs
        return {"message": {"items": []}}

    monkeypatch.setattr(app.cr, "works", fake_works)

    results = app.suggest_citations(sentence)
    assert results == {}
    assert captured["kwargs"]["query_language"] == lang


def test_suggest_citations_full_sentence_first(monkeypatch):
    sentence = "Deep learning for cats"
    captured = {"calls": []}

    def fake_works(**kwargs):
        captured["calls"].append(kwargs)
        if kwargs["query_bibliographic"] == sentence:
            # Simulate a successful lookup only when the full sentence is used
            return {"message": {"items": [{"DOI": "10.1234/xyz"}]}}
        return {"message": {"items": []}}

    def fake_get(url, timeout=10):
        return SimpleNamespace(status_code=200, text="@article{a,title={T}}")

    monkeypatch.setattr(app.cr, "works", fake_works)
    monkeypatch.setattr(app.requests, "get", fake_get)

    results = app.suggest_citations(sentence)
    # Ensure the first call used the full sentence
    assert captured["calls"][0]["query_bibliographic"] == sentence
    assert sentence in results


def test_suggest_citations_removes_stopwords(monkeypatch):
    sentence = "Because because because cat dog"
    captured = {"calls": []}

    def fake_works(**kwargs):
        captured["calls"].append(kwargs)
        return {"message": {"items": []}}

    monkeypatch.setattr(app.cr, "works", fake_works)

    results = app.suggest_citations(sentence)
    assert results == {}
    # Second call should remove the stopword "because" and only query with
    # meaningful terms.
    assert captured["calls"][1]["query_bibliographic"] == "cat dog"
