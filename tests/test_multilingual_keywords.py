import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import extract_keywords


def test_extract_keywords_french():
    sentence = "La science et la technologie avancent rapidement."
    keywords = extract_keywords(sentence)
    assert 'la' not in keywords
    assert 'science' in keywords


def test_extract_keywords_chinese():
    sentence = "这是一个科学的研究。"
    keywords = extract_keywords(sentence)
    assert '的' not in keywords
    assert '是' not in keywords
    assert len(keywords) > 0
