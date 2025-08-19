import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app as app_module
from app import app, render_markdown


def test_tag_links_skipped_inside_latex(monkeypatch):
    post = SimpleNamespace(
        title='foo',
        body='body',
        display_title='foo',
        language='en',
        path='foo',
        metadata=[],
        latitude=None,
        longitude=None,
    )

    class DummyQuery:
        def all(self):
            return [SimpleNamespace(name='foo', posts=[post])]

    monkeypatch.setattr(app_module, 'Tag', SimpleNamespace(query=DummyQuery()))
    monkeypatch.setattr(app_module, 'get_tag_synonyms', lambda name: {name})

    with app.app_context():
        html, _ = render_markdown('$$foo$$ and foo')

    assert 'class="tag-link"' in html
    assert '<span class="arithmatex">\\(foo\\)</span>' in html
    assert '<span class="arithmatex"><a' not in html


def test_tag_links_skipped_inside_detected_latex(monkeypatch):
    post = SimpleNamespace(
        title='foo',
        body='body',
        display_title='foo',
        language='en',
        path='foo',
        metadata=[],
        latitude=None,
        longitude=None,
    )

    class DummyQuery:
        def all(self):
            return [SimpleNamespace(name='foo', posts=[post])]

    monkeypatch.setattr(app_module, 'Tag', SimpleNamespace(query=DummyQuery()))
    monkeypatch.setattr(app_module, 'get_tag_synonyms', lambda name: {name})

    with app.app_context():
        html, _ = render_markdown('(foo(x_{1},x_{2})=a x_{1}+b x_{2}) and foo')

    assert 'class="tag-link"' in html
    assert '<span class="arithmatex">\\(foo(x_{1},x_{2})=a x_{1}+b x_{2}\\)</span>' in html
    assert '<span class="arithmatex"><a' not in html
