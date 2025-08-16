import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import render_markdown


def test_render_markdown_and_wikilink():
    html, toc = render_markdown('**bold** and [[Page|link]]')
    assert '<strong>bold</strong>' in html
    assert '<a href="/docs/Page">link</a>' in html
    assert toc == ''
