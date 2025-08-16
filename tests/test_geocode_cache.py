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


def test_geocode_address_uses_cache(monkeypatch):
    cache = DummyCache()
    monkeypatch.setattr(app, 'geocode_cache', cache)

    calls = {'count': 0}

    class DummyLocation:
        latitude = 1.0
        longitude = 2.0

    def fake_geocode(_):
        calls['count'] += 1
        return DummyLocation()

    monkeypatch.setattr(app.geolocator, 'geocode', fake_geocode)

    addr = 'test address'
    first = app.geocode_address(addr)
    second = app.geocode_address(addr)

    assert first == (1.0, 2.0)
    assert second == (1.0, 2.0)
    assert calls['count'] == 1


def test_geocode_cache_failure(monkeypatch):
    class BrokenCache:
        def get(self, key):
            raise Exception('fail')
        def setex(self, key, ttl, value):
            raise Exception('fail')

    monkeypatch.setattr(app, 'geocode_cache', BrokenCache())

    calls = {'count': 0}

    class DummyLocation:
        latitude = 5.0
        longitude = 6.0

    def fake_geocode(_):
        calls['count'] += 1
        return DummyLocation()

    monkeypatch.setattr(app.geolocator, 'geocode', fake_geocode)

    result = app.geocode_address('another address')
    assert result == (5.0, 6.0)
    assert calls['count'] == 1


def test_geocode_address_cache_bytes(monkeypatch):
    cache = DummyCache()
    cache.setex('byte addr', 60, b'3.0,4.0')
    monkeypatch.setattr(app, 'geocode_cache', cache)

    calls = {'count': 0}

    def fake_geocode(_):
        calls['count'] += 1
        return None

    monkeypatch.setattr(app.geolocator, 'geocode', fake_geocode)

    result = app.geocode_address('byte addr')
    assert result == (3.0, 4.0)
    assert calls['count'] == 0
