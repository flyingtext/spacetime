import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, render_markdown


def test_parenthesized_latex_converted():
    with app.app_context():
        html, _ = render_markdown(r"Equation (\min\max_a) test", enable_mathjax=True)
    assert "\\(\\min\\max_a\\)" in html


def test_nested_parenthesized_latex_converted():
    with app.app_context():
        html, _ = render_markdown(
            r"Substitutes, (U(x_{1},x_{2})=a x_{1}+b x_{2}), test",
            enable_mathjax=True,
        )
    assert "\\(U(x_{1},x_{2})=a x_{1}+b x_{2}\\)" in html


def test_double_parenthesized_latex_converted():
    """Ensure outer nested parentheses are fully stripped."""

    with app.app_context():
        html, _ = render_markdown(r"Coordinates ((x_{1}, x_{2})) test", enable_mathjax=True)
    assert "\\(x_{1}, x_{2}\\)" in html


def test_dollar_wrapped_latex_preserved():
    expr = r"$(\\text{GDP} = \\sum_{i}(\\text{GVA}_i) + \\text{Taxes} - \\text{Subsidies})$"
    with app.app_context():
        html, _ = render_markdown(expr, enable_mathjax=True)
    assert '<span class=\"arithmatex\">' in html
    assert '\\text{GDP}' in html
    assert '$$$' not in html


def test_caret_only_not_converted():
    """Expressions with only ``^`` should not trigger LaTeX conversion."""

    with app.app_context():
        html, _ = render_markdown(r"Power (x^2) test", enable_mathjax=True)
    assert "(x^2)" in html
    assert "$$x^2$$" not in html
