import os
import sys

import pytest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, render_markdown, db, Tag, Post, User


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


def test_render_markdown_preserves_list_numbers():
    html, _ = render_markdown('1. one\n3. three')
    assert '<li value="1">one</li>' in html
    assert '<li value="3">three</li>' in html
    assert 'value="2"' not in html


def test_render_markdown_blank_numbered_item_becomes_unordered():
    html, _ = render_markdown('1. one\n2. two\n3. ')
    assert '<ol>' not in html
    assert '<ul>' in html
    assert '<li>one</li>' in html
    assert '<li>two</li>' in html
    assert '<li></li>' not in html


def test_render_markdown_preserves_mathjax_delimiters():
    html, _ = render_markdown('Euler formula $e^{i\\pi}+1=0$')
    assert '$e^{i\\pi}+1=0$' in html


def test_render_markdown_single_space_indented_list():
    """A single leading space should create a nested list."""
    html, _ = render_markdown('- a\n - b\n- c')
    root = ET.fromstring(f'<root>{html}</root>')
    outer = root.find('ul')
    assert len(list(outer)) == 2
    assert outer[0].find('ul') is not None


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_markdown_preview_language(client):
    resp = client.post('/markdown/preview', json={'text': '[[Page]]', 'language': 'es'})
    assert resp.get_json()['html'] == '<p><a href="/es/Page">Page</a></p>'


def test_markdown_preview_renders_html(client):
    resp = client.post('/markdown/preview', json={'text': '<b>bold</b>'})
    assert resp.get_json()['html'] == '<p><b>bold</b></p>'


@pytest.fixture
def app_ctx():
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        yield
        db.drop_all()


def test_render_markdown_auto_links_tag(app_ctx):
    with app.app_context():
        user = User(username='u', role='editor')
        user.set_password('pw')
        tag = Tag(name='python')
        post = Post(title='T', body='First line\nSecond', path='t', language='en', author=user)
        post.tags.append(tag)
        db.session.add_all([user, tag, post])
        db.session.commit()
        html, _ = render_markdown('Learning Python every day')
        assert 'href="/tag/python"' in html
        assert 'class="tag-link"' in html
        assert 'First line' in html
