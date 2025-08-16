from app import format_citation_mla, normalize_doi

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
