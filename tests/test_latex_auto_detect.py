import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, render_markdown


def test_parenthesized_latex_converted():
    with app.app_context():
        html, _ = render_markdown(r"Equation (\min\max_a) test")
    assert "$$\\min\\max_a$$" in html
