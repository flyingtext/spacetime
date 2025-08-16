import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import format_metadata_value, extract_location, COORD_OUT_OF_RANGE_MSG


def test_format_metadata_value_valid():
    value = {'lat': 10, 'lon': 20}
    result = format_metadata_value(value)
    assert 'href' in result
    assert '10.0' in result and '20.0' in result


def test_format_metadata_value_invalid():
    value = {'lat': 95, 'lon': 200}
    result = format_metadata_value(value)
    assert COORD_OUT_OF_RANGE_MSG in str(result)


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
