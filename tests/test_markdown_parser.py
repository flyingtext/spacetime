import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, render_markdown


def test_render_markdown_and_wikilink():
    html, toc = render_markdown('**bold** and [[Page|link]]')
    assert '<strong>bold</strong>' in html
    assert '<a href="/Page">link</a>' in html
    assert toc == ''


def test_render_markdown_wikilink_spaces():
    html, _ = render_markdown('[[My Page]]')
    assert '<a href="/My%20Page">My Page</a>' in html


def test_render_markdown_with_toc_no_headings():
    html, toc = render_markdown('Just text', with_toc=True)
    assert '<p>Just text</p>' in html
    assert toc == ''


def test_render_markdown_with_toc_headings():
    html, toc = render_markdown('# Heading', with_toc=True)
    assert '<h1 id="heading">Heading</h1>' in html
    assert '<a href="#heading">Heading</a>' in toc


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_markdown_preview_language(client):
    resp = client.post('/markdown/preview', json={'text': '[[Page]]', 'language': 'es'})
    assert resp.get_json()['html'] == '<p><a href="/es/Page">Page</a></p>'
