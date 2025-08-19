import re
from typing import List, Tuple
import yake


def _insert_tags(html_content: str, spans: List[Tuple[int, int]]) -> str:
    result: List[str] = []
    plain_idx = 0
    span_iter = iter(sorted(spans, key=lambda s: s[0]))
    current = next(span_iter, None)
    i = 0
    while i < len(html_content):
        if current and plain_idx == current[1]:
            result.append('</strong></u>')
            current = next(span_iter, None)
            continue
        if html_content[i] == '<':
            j = html_content.find('>', i) + 1
            result.append(html_content[i:j])
            i = j
            continue
        if current and plain_idx == current[0]:
            result.append('<u><strong>')
        result.append(html_content[i])
        plain_idx += 1
        i += 1
    if current and plain_idx == current[1]:
        result.append('</strong></u>')
    return ''.join(result)


def apply_keyword_highlight_plugin(html: str, language: str = 'en') -> str:
    extractor = None
    try:
        extractor = yake.KeywordExtractor(lan=language, n=1, top=1)
    except Exception:
        extractor = yake.KeywordExtractor(lan='en', n=1, top=1)

    def process(match: re.Match[str]) -> str:
        content = match.group(1)
        text = re.sub('<[^<]+?>', '', content)
        text = text.strip()
        if not text:
            return match.group(0)
        try:
            keyword = extractor.extract_keywords(text)[0][0]
        except Exception:
            return match.group(0)
        spans: List[Tuple[int, int]] = []
        for m in re.finditer(r'[^.!?]+[.!?]?', text):
            sent = m.group().strip()
            if keyword.lower() in sent.lower():
                spans.append((m.start(), m.end()))
        if not spans:
            new_content = f'[{keyword}] {content}'
            return f'<p>{new_content}</p>'
        highlighted = _insert_tags(content, spans)
        new_content = f'[{keyword}] {highlighted}'
        return f'<p>{new_content}</p>'

    return re.sub(r'<p>(.*?)</p>', process, html, flags=re.DOTALL)
