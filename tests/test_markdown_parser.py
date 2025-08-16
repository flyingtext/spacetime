import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, render_markdown


def test_render_markdown_and_wikilink():
    html, toc = render_markdown('**bold** and [[Page|link]]')
    assert '<strong>bold</strong>' in html
    assert '<a href="/docs/Page">link</a>' in html
    assert toc == ''


def test_render_markdown_wikilink_spaces():
    html, _ = render_markdown('[[My Page]]')
    assert '<a href="/docs/My%20Page">My Page</a>' in html


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_markdown_preview_language(client):
    resp = client.post('/markdown/preview', json={'text': '[[Page]]', 'language': 'es'})
    assert resp.get_json()['html'] == '<p><a href="/docs/es/Page">Page</a></p>'
