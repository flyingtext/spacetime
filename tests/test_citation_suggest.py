import os
import sys
import pytest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app


def test_suggest_citations_multiword(monkeypatch):
    sentence = "The quick brown fox jumps over the lazy dog"
    captured = {}

    def fake_works(**kwargs):
        captured['kwargs'] = kwargs
        return {'message': {'items': [{'DOI': '10.1234/abc'}]}}

    def fake_get(url, timeout=10):
        return SimpleNamespace(status_code=200, text='@article{a,title={T}}')

    monkeypatch.setattr(app.cr, 'works', fake_works)
    monkeypatch.setattr(app.requests, 'get', fake_get)

    results = app.suggest_citations(sentence)
    assert sentence in results
    assert captured['kwargs']['query_bibliographic'] == sentence
    assert captured['kwargs']['query_language'] == 'en'


def test_suggest_citations_multilingual(monkeypatch):
    sentence = "La science avance rapidement."
    captured = {}

    def fake_works(**kwargs):
        captured['kwargs'] = kwargs
        return {'message': {'items': []}}

    monkeypatch.setattr(app.cr, 'works', fake_works)

    results = app.suggest_citations(sentence)
    assert results == {}
    assert captured['kwargs']['query_bibliographic'] == sentence
    assert captured['kwargs']['query_language'] == 'fr'
