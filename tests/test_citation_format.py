from app import format_citation_mla, normalize_doi, app as flask_app

def test_normalize_doi():
    assert normalize_doi('https://doi.org/10.1000/XYZ') == '10.1000/xyz'
    assert normalize_doi('10.1000/xyz') == '10.1000/xyz'
    assert normalize_doi(None) is None

def test_format_citation_mla_basic():
    part = {
        'author': 'Mercati, Flavio',
        'title': 'Relativity Without Relativity',
        'journal': 'Oxford Scholarship Online',
        'publisher': 'Oxford University Press',
        'year': '2018'
    }
    result = format_citation_mla(part, '10.1093/oso/9780198789475.003.0007')
    result_str = str(result)
    assert 'Mercati, Flavio' in result_str
    assert '"Relativity Without Relativity"' in result_str
    assert '<em>Oxford Scholarship Online</em>' in result_str
    assert 'Oxford University Press' in result_str
    assert '2018' in result_str
    assert 'https://doi.org/10.1093/oso/9780198789475.003.0007' in result_str


def test_format_citation_mla_url_only():
    part = {'url': 'https://example.com'}
    result = format_citation_mla(part, None)
    assert str(result) == '<a href="https://example.com">https://example.com</a>'


def test_format_citation_mla_relative_url():
    part = {'url': '/foo'}
    with flask_app.test_request_context('/'):
        result = format_citation_mla(part, None)
    assert str(result) == '<a href="http://localhost/foo">http://localhost/foo</a>'
