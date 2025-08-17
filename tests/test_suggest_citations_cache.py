import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app


class DummyCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value


def test_suggest_citations_cache_hit_and_miss(monkeypatch):
    cache = DummyCache()
    monkeypatch.setattr(app, 'citation_cache', cache)

    counts = {'works': 0, 'get': 0}

    def fake_works(query, limit):
        counts['works'] += 1
        return {'message': {'items': [{'DOI': '10.1/abc'}]}}

    class DummyResp:
        status_code = 200
        text = '@article{test, title={Test}}'

    def fake_get(url, timeout):
        counts['get'] += 1
        return DummyResp()

    monkeypatch.setattr(app.cr, 'works', fake_works)
    monkeypatch.setattr(app.requests, 'get', fake_get)

    text1 = 'One sentence.'
    text2 = 'Another sentence.'

    first = app.suggest_citations(text1)
    second = app.suggest_citations(text1)
    third = app.suggest_citations(text2)

    assert first == second
    assert 'Another sentence.' in third
    assert counts['works'] == 2
    assert counts['get'] == 2


def test_suggest_citations_cache_failure(monkeypatch):
    class BrokenCache:
        def get(self, key):
            raise Exception('fail')

        def setex(self, key, ttl, value):
            raise Exception('fail')

    monkeypatch.setattr(app, 'citation_cache', BrokenCache())

    calls = {'works': 0}

    def fake_works(query, limit):
        calls['works'] += 1
        return {'message': {'items': [{'DOI': '10.2/xyz'}]}}

    class DummyResp:
        status_code = 200
        text = '@article{test2, title={Another}}'

    def fake_get(url, timeout):
        return DummyResp()

    monkeypatch.setattr(app.cr, 'works', fake_works)
    monkeypatch.setattr(app.requests, 'get', fake_get)

    text = 'Cache failure sentence.'
    first = app.suggest_citations(text)
    second = app.suggest_citations(text)

    assert first == second
    assert calls['works'] == 2
