from xml.etree.ElementTree import Element
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor


class WikiLinkInlineProcessor(InlineProcessor):
    def __init__(self, pattern, base_url):
        super().__init__(pattern)
        self.base_url = base_url

    def handleMatch(self, m, data):
        label = m.group(1)
        if '|' in label:
            target, text = label.split('|', 1)
        else:
            target = text = label
        el = Element('a', {'href': f'{self.base_url}{target}'})
        el.text = text
        return el, m.start(0), m.end(0)


class WikiLinkExtension(Extension):
    def __init__(self, **kwargs):
        self.config = {'base_url': ['/docs/', 'Base URL for wiki links']}
        super().__init__(**kwargs)

    def extendMarkdown(self, md):
        base_url = self.getConfig('base_url')
        md.inlinePatterns.register(
            WikiLinkInlineProcessor(r'\[\[([^\]]+)\]\]', base_url),
            'wikilink',
            75,
        )
