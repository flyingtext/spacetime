import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, render_markdown


def test_parenthesized_latex_converted():
    with app.app_context():
        html, _ = render_markdown(r"Equation (\min\max_a) test")
    assert "$$\\min\\max_a$$" in html


def test_nested_parenthesized_latex_converted():
    with app.app_context():
        html, _ = render_markdown(
            r"Substitutes, (U(x_{1},x_{2})=a x_{1}+b x_{2}), test"
        )
    assert "$$U(x_{1},x_{2})=a x_{1}+b x_{2}$$" in html
