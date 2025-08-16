import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest

import app
from app import (
    format_metadata_value,
    extract_location,
    extract_geodata,
    COORD_OUT_OF_RANGE_MSG,
)


def test_format_metadata_value_valid(monkeypatch):
    monkeypatch.setattr(app, 'reverse_geocode_coords', lambda lat, lon: None)
    value = {'lat': 10, 'lon': 20}
    result = format_metadata_value(value)
    assert 'href' in result
    assert '10.0' in result and '20.0' in result


def test_format_metadata_value_invalid():
    value = {'lat': 95, 'lon': 200}
    result = format_metadata_value(value)
    assert COORD_OUT_OF_RANGE_MSG in str(result)


def test_format_metadata_value_geojson_string():
    value = '{"type":"Point","coordinates":[20,10]}'
    result = format_metadata_value(value)
    assert '#map' in result


def test_format_metadata_value_list_points():
    value = [{'lat': 10, 'lon': 20}, {'lat': 30, 'lon': 40}]
    result = format_metadata_value(value)
    assert '#map' in result


def test_extract_location_valid():
    meta = {'location': {'lat': '45', 'lon': '-75'}}
    loc, warning = extract_location(meta)
    assert loc == {'lat': 45.0, 'lon': -75.0}
    assert warning is None


def test_extract_location_invalid():
    meta = {'lat': '100', 'lon': '50'}
    loc, warning = extract_location(meta)
    assert loc is None
    assert warning == COORD_OUT_OF_RANGE_MSG


def test_extract_geodata_from_list():
    meta = {'points': [{'lat': 10, 'lon': 20}, {'lat': 30, 'lon': 40}]}
    geoms = extract_geodata(meta)
    assert len(geoms) == 2
    assert all(g['geometry']['type'] == 'Point' for g in geoms)
