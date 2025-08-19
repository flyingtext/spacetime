import difflib
import json
import os
import re
import markdown
import math
from datetime import datetime, timezone, timedelta
from xml.etree.ElementTree import Element, SubElement, tostring, fromstring
from urllib.parse import urlparse, quote, urljoin

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    abort,
    jsonify,
    Response,
    session,
    current_app,
)
from flask_login import (
    LoginManager,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from flask_socketio import SocketIO
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.util import AtomicString
from markdown.blockprocessors import OListProcessor
from markupsafe import Markup, escape
import requests
from habanero import Crossref
import bibtexparser
from types import SimpleNamespace
from functools import lru_cache
import nltk
from nltk.corpus import wordnet as wn
from sqlalchemy import func, event, or_, text, inspect, select
from sqlalchemy.exc import NoSuchTableError
from flask_babel import Babel, _, get_locale
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
from geopy.distance import distance as geopy_distance
from langdetect import detect, DetectorFactory, LangDetectException
import zoneinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from search_utils import expand_with_synonyms

from models import (
    db,
    POST_EDITOR_ROLES,
    User,
    Post,
    Tag,
    PostTag,
    PostLink,
    PostWatch,
    PostView,
    PostMetadata,
    UserPostMetadata,
    Notification,
    RequestedPost,
    Redirect,
    Setting,
    PostCitation,
    UserPostCitation,
    Revision,
)

load_dotenv()
DetectorFactory.seed = 0

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'SQLALCHEMY_DATABASE_URI', 'sqlite:///wiki.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['BABEL_DEFAULT_LOCALE'] = os.getenv('BABEL_DEFAULT_LOCALE', 'en')
app.config['BABEL_DEFAULT_TIMEZONE'] = os.getenv('BABEL_DEFAULT_TIMEZONE', 'UTC')
app.config['LANGUAGES'] = [
    lang.strip() for lang in os.getenv('LANGUAGES', 'en,es').split(',')
]
app.config['BABEL_TRANSLATION_DIRECTORIES'] = os.getenv(
    'BABEL_TRANSLATION_DIRECTORIES', 'translations'
)

# Allow posts with very large bodies by disabling request size limits
app.config['MAX_CONTENT_LENGTH'] = None
app.config['MAX_FORM_MEMORY_SIZE'] = None

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

socketio = SocketIO(app)
cr = Crossref()

from api import api_bp

app.register_blueprint(api_bp)

# Basic stopword list used to filter out common grammatical words when
# constructing citation queries. This helps the "suggest citations" feature
# produce more meaningful search terms for internal wiki search.
STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'have', 'has', 'are',
    'was', 'were', 'be', 'to', 'of', 'in', 'on', 'at', 'a', 'an', 'is', 'it',
    'by', 'because', 'however', 'although', 'though', 'but',
    # French articles/conjunctions
    'la', 'le', 'les', 'des', 'du', 'de', 'un', 'une', 'et', 'en', 'que',
    # Spanish articles/conjunctions
    'el', 'los', 'las', 'por', 'con', 'para', 'y'
}

babel = Babel(app)

geolocator = Nominatim(user_agent="spacetime_app")

try:
    import redis  # type: ignore

    _cache_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    geocode_cache = redis.Redis.from_url(_cache_url, decode_responses=True)
except Exception:
    geocode_cache = None

GEOCODE_CACHE_TTL = int(os.getenv("GEOCODE_CACHE_TTL", 60 * 60 * 24))


def select_locale():
    if current_user.is_authenticated and current_user.locale:
        return current_user.locale
    return request.accept_languages.best_match(app.config['LANGUAGES'])


def select_timezone() -> str:
    return get_user_timezone()


babel.locale_selector_func = select_locale
babel.timezoneselector_func = select_timezone


def ensure_revision_comment_column() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        try:
            cols = [c["name"] for c in inspector.get_columns("revision")]
        except NoSuchTableError:
            return
        if "comment" not in cols:
            with db.engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE revision ADD COLUMN comment VARCHAR(200) DEFAULT ''")
                )


ensure_revision_comment_column()


def ensure_requested_post_comment_column() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        try:
            cols = [c["name"] for c in inspector.get_columns("requested_post")]
        except NoSuchTableError:
            return
        if "admin_comment" not in cols:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE requested_post ADD COLUMN admin_comment VARCHAR(200) DEFAULT ''"
                    )
                )


ensure_requested_post_comment_column()


def ensure_user_locale_timezone_columns() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        try:
            cols = [c["name"] for c in inspector.get_columns("user")]
        except NoSuchTableError:
            return
        with db.engine.begin() as conn:
            if "locale" not in cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN locale VARCHAR(8)"))
            if "timezone" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE user ADD COLUMN timezone VARCHAR(50) DEFAULT 'UTC'"
                    )
                )


ensure_user_locale_timezone_columns()


def ensure_user_tag_modal_new_tab_column() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        try:
            cols = [c["name"] for c in inspector.get_columns("user")]
        except NoSuchTableError:
            return
        if "tag_modal_new_tab" not in cols:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE user ADD COLUMN tag_modal_new_tab BOOLEAN DEFAULT 0"
                    )
                )


ensure_user_tag_modal_new_tab_column()


def ensure_post_created_at_column() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        try:
            cols = [c["name"] for c in inspector.get_columns("post")]
        except NoSuchTableError:
            return
        if "created_at" not in cols:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE post ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                    )
                )


ensure_post_created_at_column()


def fetch_bibtex_by_title(title: str) -> str | None:
    """Return raw BibTeX for the first work matching the given title."""
    if not title:
        return None
    try:
        result = cr.works(query_title=title, limit=1)
    except Exception:
        return None
    items = result.get('message', {}).get('items', [])
    if not items:
        return None
    doi = normalize_doi(items[0].get('DOI'))
    if not doi:
        return None
    url = f"https://api.crossref.org/works/{doi}/transform/application/x-bibtex"
    try:
        resp = requests.get(url, timeout=10)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return resp.text.strip()




def suggest_citations(markdown_text: str) -> dict[str, list[dict]]:
    """Split *markdown_text* into sentences and return wiki-based suggestions.

    For each sentence the longest unique words are used to query the internal
    full-text search index. Matching posts are returned as simple ``@misc``
    BibTeX entries containing the post title and URL so they can be stored as
    standard citations.
    """

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", markdown_text) if s.strip()]
    results: dict[str, list[dict]] = {}
    for sentence in sentences:
        lang = None
        try:
            lang = detect(sentence).split('-')[0]
        except LangDetectException:
            lang = None

        words = re.findall(r"\w+", sentence.lower())
        words = [w for w in words if w not in STOPWORDS]
        if not words:
            continue
        unique_words = list(dict.fromkeys(words))
        unique_words.sort(key=len, reverse=True)
        sample_words = unique_words[:3]
        query = " OR ".join(sample_words)

        ids = [
            row[0]
            for row in db.session.execute(
                text('SELECT rowid FROM post_fts WHERE post_fts MATCH :q'),
                {'q': query},
            )
        ]
        posts_query = Post.query.filter(Post.id.in_(ids)) if ids else Post.query.filter(False)
        if lang:
            posts_query = posts_query.filter(Post.language == lang)
        posts = posts_query.limit(3).all()

        candidates: list[dict] = []
        for post in posts:
            url = f"/{post.language}/{post.path}"
            entry = {'title': post.title, 'url': url}
            key = post.id
            bibtex = f"@misc{{{key},\n  title={{ {post.title} }},\n  url={{ {url} }}\n}}"
            candidates.append({'text': bibtex, 'part': entry})
        if candidates:
            results[sentence] = candidates
    return results


def fetch_open_graph(url: str) -> dict[str, str]:
    """Fetch basic Open Graph metadata for a URL."""
    if not url:
        return {}
    try:
        resp = requests.get(url, timeout=5)
    except Exception:
        return {}
    if resp.status_code != 200:
        return {}
    html = resp.text

    def _find(prop: str) -> str:
        pattern = (
            r"""<meta[^>]+property=['"]og:""" + re.escape(prop) +
            r"""['"][^>]+content=['"]([^'"]+)['"]"""
        )
        match = re.search(pattern, html, re.IGNORECASE)
        return match.group(1) if match else ''

    return {
        'title': _find('title'),
        'description': _find('description'),
        'image': _find('image'),
    }


def map_link(lat: float, lon: float) -> str:
    """Return an OpenStreetMap link for given coordinates."""
    return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=12/{lat}/{lon}"


def geocode_address(address: str) -> tuple[float, float] | None:
    """Return ``(latitude, longitude)`` for ``address`` using Nominatim.

    Results are cached in ``geocode_cache`` keyed by the address string. Cache
    failures are ignored so the geocoding still proceeds normally.
    """
    if not address:
        return None
    if geocode_cache:
        try:
            cached = geocode_cache.get(address)
            if cached:
                if isinstance(cached, bytes):
                    cached = cached.decode()
                lat_str, lon_str = cached.split(",")
                return float(lat_str), float(lon_str)
        except Exception:
            pass
    try:
        location = geolocator.geocode(address)
    except Exception:
        return None
    if not location:
        return None
    coords = location.latitude, location.longitude
    if geocode_cache:
        try:
            geocode_cache.setex(
                address, GEOCODE_CACHE_TTL, f"{coords[0]},{coords[1]}"
            )
        except Exception:
            pass
    return coords


def reverse_geocode_coords(lat: float, lon: float) -> str | None:
    """Return human-readable address for coordinates using Nominatim.

    Results are cached in ``geocode_cache`` keyed by ``"rev:lat,lon"``. Cache
    failures are ignored so the reverse geocoding still proceeds normally.
    """
    key = f"rev:{lat},{lon}"
    if geocode_cache:
        try:
            cached = geocode_cache.get(key)
            if cached:
                return cached
        except Exception:
            pass
    try:
        location = geolocator.reverse((lat, lon))
    except Exception:
        return None
    if not location:
        return None
    address = location.address
    if geocode_cache:
        try:
            geocode_cache.setex(key, GEOCODE_CACHE_TTL, address)
        except Exception:
            pass
    return address


COORD_OUT_OF_RANGE_MSG = 'Coordinates out of range'


def parse_geodata(value) -> list[dict]:
    """Return a list of GeoJSON features extracted from ``value``.

    ``value`` may be a dict with ``lat``/``lon`` keys, a GeoJSON object,
    a list of such objects, or a JSON string representing any of these.
    """

    def _parse(v) -> list[dict]:
        features: list[dict] = []
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                return []
        if isinstance(v, dict):
            lat = v.get('lat') or v.get('latitude')
            lon = v.get('lon') or v.get('lng') or v.get('longitude')
            if lat is not None and lon is not None:
                try:
                    lat_f = float(lat)
                    lon_f = float(lon)
                except (TypeError, ValueError):
                    return []
                if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
                    features.append(
                        {
                            'type': 'Feature',
                            'geometry': {
                                'type': 'Point',
                                'coordinates': [lon_f, lat_f],
                            },
                            'properties': {},
                        }
                    )
                return features
            gtype = v.get('type')
            if gtype == 'Feature':
                features.append(v)
            elif gtype == 'FeatureCollection':
                for feat in v.get('features', []):
                    features.extend(_parse(feat))
            elif gtype in {
                'Point',
                'LineString',
                'Polygon',
                'MultiPoint',
                'MultiLineString',
                'MultiPolygon',
            }:
                features.append({'type': 'Feature', 'geometry': v, 'properties': {}})
            return features
        if isinstance(v, list):
            for item in v:
                features.extend(_parse(item))
        return features

    return _parse(value)


def format_metadata_value(value):
    if isinstance(value, dict):
        lat = value.get('lat') or value.get('latitude')
        lon = value.get('lon') or value.get('lng') or value.get('longitude')
        if lat is not None and lon is not None:
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except (TypeError, ValueError):
                return Markup(escape(json.dumps(value)))
            if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
                address = reverse_geocode_coords(lat_f, lon_f)
                label = f"{lat_f}, {lon_f}"
                if address:
                    label += f" ({escape(address)})"
                return Markup(
                    f'<a href="{map_link(lat_f, lon_f)}">{label}</a>'
                )
            return Markup(_(COORD_OUT_OF_RANGE_MSG))
        features = parse_geodata(value)
        if features:
            return Markup(
                f'<a href="#map">{_("View on map")}</a>'
            )
        return Markup(escape(json.dumps(value)))
    if isinstance(value, list):
        features = parse_geodata(value)
        if features:
            return Markup(
                f'<a href="#map">{_("View on map")}</a>'
            )
        return Markup(escape(json.dumps(value)))
    if isinstance(value, str):
        features = parse_geodata(value)
        if features:
            return Markup(
                f'<a href="#map">{_("View on map")}</a>'
            )
        return Markup(escape(value))
    return Markup(escape(str(value)))


app.jinja_env.filters['format_metadata'] = format_metadata_value


def normalize_doi(doi: str | None) -> str | None:
    """Return DOI in canonical lowercase form without URL prefix."""
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi, flags=re.I)
    return doi.lower()


def is_url(text: str) -> bool:
    """Return True if text looks like an HTTP(S) URL."""
    try:
        result = urlparse(text)
        return result.scheme in ('http', 'https') and bool(result.netloc)
    except Exception:
        return False


def format_citation_mla(part: dict, doi: str | None = None) -> Markup:
    """Format citation metadata in MLA style with DOI link."""
    doi = normalize_doi(doi or part.get('doi'))
    authors = part.get('author')
    title = part.get('title')
    container = part.get('journal') or part.get('booktitle')
    publisher = part.get('publisher')
    year = part.get('year')
    volume = part.get('volume')
    number = part.get('number')
    pages = part.get('pages')

    pieces: list[str] = []
    if authors:
        pieces.append(str(escape(str(authors).rstrip('.'))))
    if title:
        pieces.append(f"\"{escape(str(title).rstrip('.'))}\"")
    if container:
        pieces.append(f"<em>{escape(str(container).rstrip('.'))}</em>")
    vol_issue: list[str] = []
    if volume:
        vol_issue.append(f"vol. {escape(str(volume))}")
    if number:
        vol_issue.append(f"no. {escape(str(number))}")
    if vol_issue:
        pieces.append(', '.join(vol_issue))
    if publisher:
        pieces.append(str(escape(str(publisher).rstrip('.'))))
    if year:
        pieces.append(str(escape(str(year).rstrip('.'))))
    if pages:
        pieces.append(f"pp. {escape(str(pages).rstrip('.'))}")
    if not pieces and part.get('url'):
        raw_url = str(part['url'])
        parsed = urlparse(raw_url)
        if not parsed.scheme:
            raw_url = urljoin(request.url_root, raw_url)
        url = escape(raw_url)
        return Markup(f'<a href="{url}">{url}</a>')
    citation = '. '.join(pieces)
    if doi:
        citation += f". <a href=\"https://doi.org/{doi}\">https://doi.org/{doi}</a>"
    elif part.get('url'):
        raw_url = str(part['url'])
        parsed = urlparse(raw_url)
        if not parsed.scheme:
            raw_url = urljoin(request.url_root, raw_url)
        url = escape(raw_url)
        citation += f". <a href=\"{url}\">{url}</a>"
    return Markup(citation)


app.jinja_env.filters['mla_citation'] = format_citation_mla


def extract_locations(meta: dict) -> tuple[list[dict], str | None]:
    """Extract all location dicts from metadata within valid range."""
    locations: list[dict] = []
    warning = None

    def add_location(lat, lon):
        nonlocal warning
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            return
        if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
            locations.append({'lat': lat_f, 'lon': lon_f})
        else:
            warning = COORD_OUT_OF_RANGE_MSG

    # Direct lat/lon fields
    lat = meta.get('lat') or meta.get('latitude')
    lon = meta.get('lon') or meta.get('lng') or meta.get('longitude')
    if lat is not None and lon is not None:
        add_location(lat, lon)

    # Values that may contain coordinates or GeoJSON
    for value in meta.values():
        for feat in parse_geodata(value):
            geom = feat.get('geometry', {})
            if geom.get('type') == 'Point':
                coords = geom.get('coordinates', [])
                if len(coords) == 2:
                    lon_f, lat_f = coords
                    locations.append({'lat': lat_f, 'lon': lon_f})

    return locations, warning


def extract_geodata(meta: dict) -> list[dict]:
    """Collect GeoJSON features from all metadata values."""
    geoms: list[dict] = []
    # Handle direct lat/lon pairs in ``meta``
    lat = meta.get('lat') or meta.get('latitude')
    lon = meta.get('lon') or meta.get('lng') or meta.get('longitude')
    if lat is not None and lon is not None:
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            pass
        else:
            if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
                geoms.append(
                    {
                        'type': 'Feature',
                        'geometry': {
                            'type': 'Point',
                            'coordinates': [lon_f, lat_f],
                        },
                        'properties': {},
                    }
                )

    for value in meta.values():
        geoms.extend(parse_geodata(value))
    return geoms


LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def update_post_links(post: "Post") -> None:
    """Update outgoing link records for ``post`` based on its body."""
    PostLink.query.filter_by(source_id=post.id).delete()
    targets = LINK_RE.findall(post.body or "")
    for target in targets:
        target = target.strip()
        target_post = Post.query.filter_by(path=target, language=post.language).first()
        if target_post and target_post.id != post.id:
            db.session.add(PostLink(source_id=post.id, target_id=target_post.id))


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
        target_url = f"{self.base_url}{quote(target, safe='/#')}"
        el = Element('a', {'href': target_url})
        el.text = text
        return el, m.start(0), m.end(0)


class WikiLinkExtension(Extension):
    def __init__(self, **kwargs):
        self.config = {'base_url': ['/', 'Base URL for wiki links']}
        super().__init__(**kwargs)

    def extendMarkdown(self, md):
        base_url = self.getConfig('base_url')
        md.inlinePatterns.register(
            WikiLinkInlineProcessor(r'\[\[([^\]]+)\]\]', base_url),
            'wikilink',
            75,
        )


class TagLinkInlineProcessor(InlineProcessor):
    """Inline processor to automatically link tag names."""

    def __init__(self, pattern: str, tag_map: dict[str, dict[str, str]]):
        super().__init__(pattern)
        # tag_map maps lowercase tag name to dict with url and tooltip JSON
        self.tag_map = tag_map

    def handleMatch(self, m, data):
        word = m.group(0)
        info = self.tag_map.get(word.lower())
        if not info:
            return None, m.start(0), m.end(0)
        el = Element(
            'a',
            {
                'href': info['url'],
                'class': 'tag-link',
                'data-tooltip': info['tooltip'],
            },
        )
        el.text = AtomicString(word)
        return el, m.start(0), m.end(0)


class TagLinkExtension(Extension):
    """Markdown extension that auto-links tag names with tooltips."""

    def __init__(self, tag_map: dict[str, dict[str, str]], **kwargs):
        self.tag_map = tag_map
        super().__init__(**kwargs)

    def extendMarkdown(self, md):
        if not self.tag_map:
            return
        pattern = r'(?i)\b(' + '|'.join(re.escape(t) for t in self.tag_map) + r')\b'
        md.inlinePatterns.register(
            TagLinkInlineProcessor(pattern, self.tag_map),
            'taglink',
            74,
        )


class PreserveOListProcessor(OListProcessor):
    """Ordered list processor that preserves explicit numbering."""

    def run(self, parent, blocks):
        items = self.get_items_with_numbers(blocks.pop(0))

        # If the list ends with a blank numbered item and there are no further
        # items, treat the whole block as an unordered list. This avoids
        # rendering stray list numbers when the source only contains a numbered
        # prefix with no following content.
        tag = self.TAG
        if items and not items[-1][1].strip():
            items = items[:-1]
            if items:
                tag = 'ul'
                items = [(None, text) for _, text in items]
            else:
                return

        sibling = self.lastChild(parent)

        if sibling is not None and sibling.tag in self.SIBLING_TAGS:
            lst = sibling
            if lst[-1].text:
                p = Element('p')
                p.text = lst[-1].text
                lst[-1].text = ''
                lst[-1].insert(0, p)
            lch = self.lastChild(lst[-1])
            if lch is not None and lch.tail:
                p = SubElement(lst[-1], 'p')
                p.text = lch.tail.lstrip()
                lch.tail = ''
            li = SubElement(lst, 'li')
            self.parser.state.set('looselist')
            num, firstitem = items.pop(0)
            if tag == 'ol' and num:
                li.set('value', num)
            self.parser.parseBlocks(li, [firstitem])
            self.parser.state.reset()
        elif parent.tag in ['ol', 'ul']:
            lst = parent
        else:
            lst = SubElement(parent, tag)
            if tag == 'ol' and not self.LAZY_OL and self.STARTSWITH != '1':
                lst.attrib['start'] = self.STARTSWITH

        self.parser.state.set('list')
        for num, item in items:
            if item.startswith(' ' * self.tab_length):
                self.parser.parseBlocks(lst[-1], [item])
            else:
                li = SubElement(lst, 'li')
                if tag == 'ol' and num:
                    li.set('value', num)
                self.parser.parseBlocks(li, [item])
        self.parser.state.reset()

    def get_items_with_numbers(self, block: str) -> list[tuple[str | None, str]]:
        items: list[tuple[str | None, str]] = []
        for line in block.split('\n'):
            m = self.CHILD_RE.match(line)
            if m:
                num_match = re.match(r'(\d+)', m.group(1))
                num = num_match.group(1) if num_match else None
                if not items and self.TAG == 'ol' and num:
                    self.STARTSWITH = num
                items.append((num, m.group(3)))
            elif self.INDENT_RE.match(line):
                if items[-1][1].startswith(' ' * self.tab_length):
                    items[-1] = (items[-1][0], f"{items[-1][1]}\n{line}")
                else:
                    items.append((None, line))
            else:
                items[-1] = (items[-1][0], f"{items[-1][1]}\n{line}")
        return items


class PreserveOrderedListExtension(Extension):
    """Markdown extension to preserve numbering in ordered lists."""

    def extendMarkdown(self, md):
        md.parser.blockprocessors.register(
            PreserveOListProcessor(md.parser), 'olist', 40
        )


# Utility to strip nested tag links inside regular hyperlinks
def sanitize_tag_links(html: str) -> str:
    try:
        root = fromstring(f'<root>{html}</root>')
    except Exception:
        return html
    for outer in root.iter('a'):
        for inner in list(outer):
            if inner.tag == 'a' and 'tag-link' in inner.get('class', '').split():
                idx = list(outer).index(inner)
                text = (inner.text or '') + (inner.tail or '')
                if idx == 0:
                    outer.text = (outer.text or '') + text
                else:
                    prev = list(outer)[idx - 1]
                    prev.tail = (prev.tail or '') + text
                outer.remove(inner)
    cleaned = ''.join(tostring(child, encoding='unicode') for child in root)

    def strip_links(match: re.Match) -> str:
        segment = match.group(0)
        return re.sub(
            r'<a[^>]*class="tag-link"[^>]*>(.*?)</a>',
            r'\1',
            segment,
            flags=re.DOTALL,
        )

    cleaned = re.sub(r'\$\$.*?\$\$', strip_links, cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'\\\(.*?\\\)', strip_links, cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'\\\[.*?\\\]', strip_links, cleaned, flags=re.DOTALL)
    return cleaned


def unwrap_math_blocks(html: str) -> str:
    """Remove paragraph wrappers around display-math blocks.

    Markdown wraps ``$$`` blocks in ``<p>`` tags which prevents MathJax from
    recognizing multi-line display formulas. Unwrap those paragraphs so that
    MathJax sees the raw ``$$`` delimiters.
    """
    return re.sub(r'<p>\s*(\$\$[\s\S]*?\$\$)\s*</p>', r'\1', html)


# Protect math expressions from Markdown processing
MATH_PATTERN = re.compile(r"\$\$[\s\S]*?\$\$|\\\(.*?\\\)|\\\[.*?\\\]", re.DOTALL)


def extract_math_segments(text: str) -> tuple[str, dict[str, str]]:
    """Replace math regions with placeholders before Markdown processing."""

    segments: dict[str, str] = {}

    def repl(match: re.Match) -> str:
        key = f"@@MATH{len(segments)}@@"
        segments[key] = match.group(0)
        return key

    return MATH_PATTERN.sub(repl, text), segments


def restore_math_segments(text: str, segments: dict[str, str]) -> str:
    """Restore previously extracted math regions."""

    for key, val in segments.items():
        text = text.replace(key, val)
    return text


def detect_latex_parens(text: str) -> str:
    """Convert parenthesized LaTeX expressions to ``$$`` blocks.

    Finds occurrences like ``(\min\max_a)`` and replaces the surrounding
    parentheses with ``$$`` so that MathJax treats them as math blocks.

    This detection is intentionally permissive – any parenthesized segment
    without newlines that contains common LaTeX markers such as ``\``, ``_``,
    ``{``, or ``}`` will be treated as LaTeX. Nested parentheses are supported so
    expressions like ``(U(x_{1},x_{2})=a x_{1}+b x_{2})`` are also converted.
    """

    def strip_outer_parentheses(s: str) -> str:
        """Remove pairs of outer parentheses that wrap the entire string.

        This is used to handle cases like ``((x_1))`` where multiple
        parentheses surround the LaTeX expression. Only balanced pairs that
        enclose the full string are stripped, leaving necessary inner
        parentheses intact.
        """

        while s.startswith('(') and s.endswith(')'):
            depth = 0
            balanced = True
            for idx, ch in enumerate(s):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0 and idx != len(s) - 1:
                        balanced = False
                        break
            if depth != 0:
                balanced = False
            if not balanced:
                break
            s = s[1:-1]
        return s

    out: list[str] = []
    i = 0
    in_math = False
    math_delim = ''
    while i < len(text):
        ch = text[i]
        if ch == '$':
            # Track math regions delimited by $ or $$ so we don't try to
            # auto-detect parentheses inside real LaTeX blocks.
            if in_math:
                if math_delim == '$$' and text.startswith('$$', i):
                    in_math = False
                    out.append('$$')
                    i += 2
                    continue
                if math_delim == '$' and text[i] == '$':
                    in_math = False
                    out.append('$')
                    i += 1
                    continue
            else:
                if text.startswith('$$', i):
                    in_math = True
                    math_delim = '$$'
                    out.append('$$')
                    i += 2
                    continue
                in_math = True
                math_delim = '$'
                out.append('$')
                i += 1
                continue
        if not in_math and ch == '(':
            j = i + 1
            depth = 1
            has_newline = False
            is_latex = False
            while j < len(text) and depth > 0:
                c = text[j]
                if c == '\n':
                    has_newline = True
                    break
                if c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
                    if depth == 0:
                        break
                if c in '\\_{}':
                    is_latex = True
                j += 1
            if depth == 0 and not has_newline and is_latex:
                content = strip_outer_parentheses(text[i + 1:j])
                out.append(f"\\({content}\\)")
                i = j + 1
                continue
        out.append(ch)
        i += 1
    return ''.join(out)


def convert_inline_dollars(text: str) -> str:
    """Replace inline ``$$`` math with ``\(\)`` delimiters.

    ``$$`` is traditionally used for display math, but some users include it
    within regular sentences. MathJax ignores display delimiters that are not
    on their own line, so convert those inline occurrences to ``\(\)`` so they
    are rendered properly.
    """

    def repl(match: re.Match) -> str:
        start, end = match.span()
        before = text[:start]
        after = text[end:]
        if before.strip() or after.strip():
            return f"\\({match.group(1)}\\)"
        return match.group(0)

    return re.sub(r'\$\$([^\n]*?)\$\$', repl, text)


# Markup rendering helpers
def render_markdown(text: str, base_url: str = '/', with_toc: bool = False) -> tuple[str, str]:
    """Return HTML and optional TOC from Markdown text with wiki links."""
    extensions: list[Extension | str] = [
        WikiLinkExtension(base_url=base_url),
        PreserveOrderedListExtension(),
        'tables',
        'pymdownx.arithmatex',
    ]
    extension_configs = {
        'pymdownx.arithmatex': {
            'generic': True,
        }
    }
    # Attempt to add automatic tag linking if tags are available
    try:
        tag_map: dict[str, dict[str, str]] = {}
        for tag in Tag.query.all():
            posts: list[dict[str, object]] = []
            for p in tag.posts:
                if not p.title or not p.body:
                    continue
                doc: dict[str, object] = {
                    'title': p.display_title,
                    'url': f"/{p.language}/{p.path}",
                    'snippet': (p.body.splitlines()[0] if p.body else ''),
                    'views': get_view_count(p),
                }
                lat = p.latitude
                lon = p.longitude
                if lat is None or lon is None:
                    meta = {m.key: m.value for m in p.metadata}
                    locs = meta.get('locations')
                    if isinstance(locs, list) and locs:
                        first = locs[0]
                        lat = first.get('lat')
                        lon = first.get('lon')
                    else:
                        lat = meta.get('lat') or meta.get('latitude')
                        lon = (
                            meta.get('lon')
                            or meta.get('longitude')
                            or meta.get('lng')
                        )
                if lat is not None and lon is not None:
                    try:
                        doc['lat'] = float(lat)
                        doc['lon'] = float(lon)
                    except (TypeError, ValueError):
                        pass
                posts.append(doc)
            if posts:
                info = {
                    'url': f"/tag/{quote(tag.name)}",
                    'tooltip': json.dumps(posts),
                }
                for syn in get_tag_synonyms(tag.name):
                    tag_map.setdefault(syn, info)
        if tag_map:
            extensions.append(TagLinkExtension(tag_map))
    except Exception:
        pass
    normalized = re.sub(r'(?m)^\s{3}([*+-]|\d+\.)', r' \1', text or '')
    normalized = detect_latex_parens(normalized)
    normalized = convert_inline_dollars(normalized)
    if with_toc:
        md = markdown.Markdown(
            extensions=extensions + ['toc'],
            extension_configs=extension_configs,
            tab_length=1,
        )
        html = md.convert(normalized)
        html = sanitize_tag_links(html)
        html = unwrap_math_blocks(html)
        if not getattr(md, 'toc_tokens', None):
            return Markup(html), Markup('')
        return Markup(html), Markup(md.toc)
    html = markdown.markdown(
        normalized,
        extensions=extensions,
        extension_configs=extension_configs,
        tab_length=1,
    )
    html = sanitize_tag_links(html)
    html = unwrap_math_blocks(html)
    return Markup(html), Markup('')


def get_setting(key: str, default: str = '') -> str:
    try:
        setting = Setting.query.filter_by(key=key).first()
    except Exception:
        return default
    return setting.value if setting else default


def get_category_tags(language: str | None = None) -> list[tuple[str, str]]:
    """Return list of category tag names and labels from settings.

    The ``post_categories`` setting stores a JSON object mapping canonical tag
    names to language-specific labels, e.g. ``{"news": {"en": "news", "es":
    "noticias"}}``.  This helper returns a list of ``(slug, label)`` tuples for
    the requested language. If no label exists for the language, the canonical
    slug is used as the label. Older comma separated lists are also supported
    and will return ``(tag, tag)`` tuples."""

    lang = language or str(get_locale())
    raw = get_setting('post_categories', '')
    if not raw:
        return []
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError:
        return [(t.strip(), t.strip()) for t in raw.split(',') if t.strip()]

    categories: list[tuple[str, str]] = []
    if isinstance(mapping, dict):
        for slug, translations in mapping.items():
            if isinstance(translations, dict):
                label = translations.get(lang) or slug
            else:
                label = slug
            categories.append((slug, label))
    return categories


@lru_cache(maxsize=None)
def get_tag_synonyms(name: str) -> set[str]:
    """Return a set of lowercase synonyms for a tag name, including itself."""
    try:
        synsets = wn.synsets(name)
    except LookupError:
        nltk.download('wordnet', quiet=True)
        synsets = wn.synsets(name)
    synonyms = {name.lower()}
    for syn in synsets:
        for lemma in syn.lemmas():
            synonyms.add(lemma.name().replace('_', ' ').lower())
    return synonyms


def resolve_tag(name: str) -> Tag | None:
    """Return tag object by canonical name or translated label.

    Performs a case-insensitive lookup against both stored tag names and any
    category labels defined in the ``post_categories`` setting. Returns ``None``
    if no matching tag is found."""

    # Direct lookup against existing tag names or synonyms
    tag = Tag.query.filter(func.lower(Tag.name) == name.lower()).first()
    if tag:
        return tag
    syns = get_tag_synonyms(name)
    tag = Tag.query.filter(func.lower(Tag.name).in_(syns)).first()
    if tag:
        return tag

    # Fallback to category translations defined in settings
    raw = get_setting('post_categories', '')
    if not raw:
        return None
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if isinstance(mapping, dict):
        lower_name = name.lower()
        for slug, translations in mapping.items():
            if slug.lower() == lower_name:
                return Tag.query.filter(func.lower(Tag.name) == slug.lower()).first()
            if isinstance(translations, dict):
                for label in translations.values():
                    if label.lower() == lower_name:
                        return Tag.query.filter(func.lower(Tag.name) == slug.lower()).first()
    return None


def get_user_timezone() -> str:
    if current_user.is_authenticated and current_user.timezone:
        return current_user.timezone
    tz = session.get('timezone')
    if tz:
        return tz
    return get_setting('timezone', 'UTC') or 'UTC'


def normalize_timezone(tz: str) -> str | None:
    """Return a canonical timezone name or ``None`` if invalid.

    Tries a direct lookup first and falls back to a case-insensitive match so
    that users can enter names like ``asia/seoul``.
    """
    tz = tz.strip()
    try:
        ZoneInfo(tz)
        return tz
    except ZoneInfoNotFoundError:
        for name in zoneinfo.available_timezones():
            if name.lower() == tz.lower():
                return name
    return None


@app.template_filter('format_datetime')
def format_datetime(value: datetime, fmt: str = '%Y-%m-%d %H:%M %Z') -> str:
    tz_name = get_user_timezone()
    try:
        tzinfo = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tzinfo = timezone.utc
        tz_name = 'UTC'
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(tzinfo)
    formatted = local_dt.strftime(fmt)
    abbr = local_dt.strftime('%Z')
    if '%Z' not in fmt:
        formatted = f"{formatted} {abbr}"
    if tz_name != abbr:
        formatted = f"{formatted} ({tz_name})"
    return formatted


@app.context_processor
def inject_settings():
    return {'get_setting': get_setting}


def get_view_count(post: Post) -> int:
    """Return total view count for a post."""
    meta = next((m for m in post.metadata if m.key == 'views'), None)
    return int(meta.value) if meta else 0


def increment_view_count(post: Post) -> int:
    """Increment and return the view count for a post and record the view."""
    meta = PostMetadata.query.filter_by(post_id=post.id, key='views').first()
    if meta:
        meta.value = int(meta.value) + 1
    else:
        meta = PostMetadata(post=post, key='views', value=1)
        db.session.add(meta)
    db.session.add(PostView(post=post, ip_address=request.remote_addr))
    db.session.commit()
    return int(meta.value)


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))


@app.route('/posts')
def all_posts():
    tag_name = request.args.get('tag', '').strip()
    page = request.args.get('page', 1, type=int)
    tag = None

    query = Post.query.filter(Post.title != '', Post.body != '')
    if tag_name:
        tag = resolve_tag(tag_name)
        if not tag:
            abort(404)
        syns = get_tag_synonyms(tag.name)
        query = query.join(Post.tags).filter(func.lower(Tag.name).in_(syns))

    pagination = (
        query.order_by(Post.id.desc()).paginate(page=page, per_page=20, error_out=False)
    )
    categories = get_category_tags()
    return render_template(
        'index.html', pagination=pagination, tag=tag, categories=categories
    )


@app.route('/')
def index():
    home_path = get_setting('home_page_path', '').strip().lstrip('/')
    if home_path:
        if '/' in home_path:
            language, doc_path = home_path.split('/', 1)
        else:
            language = select_locale() or app.config['BABEL_DEFAULT_LOCALE']
            doc_path = home_path
        post = Post.query.filter_by(language=language, path=doc_path).first()
        if post:
            return redirect(url_for('document', language=language, doc_path=doc_path))
    return all_posts()


@app.route('/rss.xml')
def rss_feed():
    if get_setting('rss_enabled', 'false').lower() not in (
        'true',
        '1',
        'yes',
        'on',
    ):
        abort(404)
    try:
        limit = int(get_setting('rss_limit', '20'))
    except ValueError:
        limit = 20
    posts = (
        Post.query.filter(Post.title != '')
        .order_by(Post.id.desc())
        .limit(limit)
        .all()
    )
    root = Element('rss', version='2.0')
    channel = SubElement(root, 'channel')
    title = get_setting('site_title', 'Spacetime')
    SubElement(channel, 'title').text = title
    SubElement(channel, 'link').text = request.url_root.rstrip('/')
    SubElement(channel, 'description').text = f'RSS feed for {title}'
    for post in posts:
        item = SubElement(channel, 'item')
        SubElement(item, 'title').text = post.display_title
        SubElement(item, 'link').text = url_for(
            'document', language=post.language, doc_path=post.path, _external=True
        )
        SubElement(item, 'guid').text = f"{post.language}:{post.path}"
        rev = (
            Revision.query.filter_by(post_id=post.id)
            .order_by(Revision.created_at.desc())
            .first()
        )
        if rev:
            pub = rev.created_at.replace(tzinfo=timezone.utc).strftime(
                '%a, %d %b %Y %H:%M:%S GMT'
            )
            SubElement(item, 'pubDate').text = pub
        SubElement(item, 'description').text = post.body
    xml = tostring(root, encoding='utf-8')
    return Response(xml, mimetype='application/rss+xml')


@app.route('/robots.txt')
def robots_txt():
    lines = [
        'User-agent: *',
        'Disallow:',
        f"Sitemap: {url_for('sitemap', _external=True)}",
    ]
    return Response("\n".join(lines), mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap():
    """Generate a basic XML sitemap of all posts."""
    posts = (
        Post.query.filter(Post.title != '')
        .order_by(Post.id.desc())
        .all()
    )
    root = Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
    for post in posts:
        url_el = SubElement(root, 'url')
        SubElement(url_el, 'loc').text = url_for(
            'document', language=post.language, doc_path=post.path, _external=True
        )
        rev = (
            Revision.query.filter_by(post_id=post.id)
            .order_by(Revision.created_at.desc())
            .first()
        )
        if rev:
            SubElement(url_el, 'lastmod').text = rev.created_at.date().isoformat()
    xml = tostring(root, encoding='utf-8')
    return Response(xml, mimetype='application/xml')


@app.route('/recent')
def recent_changes():
    revisions = (
        Revision.query.order_by(Revision.created_at.desc()).limit(20).all()
    )
    return render_template('recent.html', revisions=revisions)


@app.route('/timezone', methods=['GET', 'POST'])
def choose_timezone():
    tz = session.get('timezone', get_setting('timezone', 'UTC') or 'UTC')
    if request.method == 'POST':
        tz_input = request.form.get('timezone', '').strip() or 'UTC'
        tz_norm = normalize_timezone(tz_input)
        if tz_norm is None:
            flash(_('Invalid timezone'))
            return redirect(url_for('choose_timezone'))
        session['timezone'] = tz_norm
        flash(_('Timezone updated.'))
        return redirect(url_for('choose_timezone'))
    return render_template('timezone.html', timezone=tz)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash(_('Username already exists'))
            return redirect(url_for('register'))
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(_('Registration successful. Please log in.'))
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        flash(_('Invalid credentials'))
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/user/<username>', methods=['GET', 'POST'])
def profile(username: str):
    user = User.query.filter_by(username=username).first_or_404()
    posts = (
        Post.query.filter_by(author_id=user.id)
        .order_by(Post.id.desc())
        .limit(5)
        .all()
    )
    edited_revisions = (
        Revision.query.filter_by(user_id=user.id)
        .order_by(Revision.created_at.desc())
        .limit(5)
        .all()
    )
    edited_posts = []
    seen_post_ids = set()
    for rev in edited_revisions:
        if rev.post_id not in seen_post_ids:
            edited_posts.append(rev.post)
            seen_post_ids.add(rev.post_id)
    post_count = Post.query.filter_by(author_id=user.id).count()
    citation_count = (
        PostCitation.query.filter_by(user_id=user.id).count()
        + UserPostCitation.query.filter_by(user_id=user.id).count()
    )
    if request.method == 'POST':
        if not current_user.is_authenticated or current_user.id != user.id:
            abort(403)
        user.bio = request.form.get('bio', '').strip() or None
        locale = request.form.get('locale', '').strip()
        user.locale = locale if locale in app.config['LANGUAGES'] else None
        tz = request.form.get('timezone', '').strip() or 'UTC'
        tz_norm = normalize_timezone(tz)
        if tz_norm is None:
            flash(_('Invalid timezone'))
            return redirect(url_for('profile', username=user.username))
        user.timezone = tz_norm
        user.tag_modal_new_tab = request.form.get('tag_modal_new_tab') == 'on'
        db.session.commit()
        flash(_('Profile updated'))
        return redirect(url_for('profile', username=user.username))
    post_locations: list[dict[str, float | str]] = []
    seen_loc_ids: set[int] = set()
    for p in posts + edited_posts:
        if p.id in seen_loc_ids:
            continue
        seen_loc_ids.add(p.id)
        if p.latitude is not None and p.longitude is not None:
            post_locations.append(
                {
                    'title': p.display_title,
                    'lat': p.latitude,
                    'lon': p.longitude,
                    'url': url_for('document', language=p.language, doc_path=p.path),
                }
            )
    return render_template(
        'profile.html',
        user=user,
        posts=posts,
        edited_posts=edited_posts,
        post_count=post_count,
        citation_count=citation_count,
        post_locations=post_locations,
        post_locations_json=json.dumps(post_locations),
        languages=app.config['LANGUAGES'],
    )


@app.route('/notifications')
@login_required
def notifications():
    notes = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    for n in notes:
        if n.read_at is None:
            n.read_at = datetime.utcnow()
    db.session.commit()
    return render_template('notifications.html', notifications=notes)


@app.route('/post/request', methods=['GET', 'POST'])
@login_required
def request_post():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        req = RequestedPost(title=title, description=description, requester=current_user)
        db.session.add(req)
        db.session.commit()
        flash(_('Request submitted'))
        return redirect(url_for('requested_posts'))
    return render_template('request_form.html')


@app.route('/posts/requested')
def requested_posts():
    reqs = RequestedPost.query.order_by(RequestedPost.created_at.desc()).all()
    return render_template('requested_posts.html', requests=reqs)


@app.route('/admin/requested', methods=['GET', 'POST'])
@login_required
def admin_requested_posts():
    if not current_user.is_admin():
        abort(403)
    if request.method == 'POST':
        req_id = request.form.get('request_id', type=int)
        comment = request.form.get('comment', '').strip()
        req = RequestedPost.query.get_or_404(req_id)
        req.admin_comment = comment
        db.session.commit()
        flash(_('Comment updated'))
        return redirect(url_for('admin_requested_posts'))
    reqs = RequestedPost.query.order_by(RequestedPost.created_at.desc()).all()
    return render_template('admin/requested_posts.html', requests=reqs)


def _slugify(title: str) -> str:
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', title.strip().lower()).strip('-')
    return slug or 'post'


def generate_unique_path(title: str, language: str) -> str:
    base = _slugify(title)
    path = base
    counter = 1
    while Post.query.filter_by(path=path, language=language).first():
        path = f"{base}-{counter}"
        counter += 1
    return path


@app.route('/post/new', methods=['GET', 'POST'])
@login_required
def create_post():
    if not current_user.can_edit_posts():
        abort(403)
    if request.method == 'POST':
        title = request.form['title']
        body = request.form['body']
        path = request.form['path'].strip()
        language = request.form['language'].strip()
        comment = request.form.get('comment', '').strip()
        if language not in app.config['LANGUAGES']:
            try:
                language = detect(body)
            except LangDetectException:
                language = app.config['BABEL_DEFAULT_LOCALE']
            if language not in app.config['LANGUAGES']:
                language = app.config['BABEL_DEFAULT_LOCALE']
        if not path:
            path = generate_unique_path(title, language)
        elif Post.query.filter_by(path=path, language=language).first():
            flash(_('Path already exists'))
            return redirect(url_for('create_post'))
        tag_names = [t.strip() for t in request.form['tags'].split(',') if t.strip()]
        tags = []
        for name in dict.fromkeys(tag_names):
            tag = Tag.query.filter_by(name=name).first()
            if not tag:
                tag = Tag(name=name)
                db.session.add(tag)
            tags.append(tag)
        post = Post(title=title, body=body, path=path, language=language,
                    author=current_user, tags=tags)
        db.session.add(post)
        db.session.flush()

        metadata_json = request.form.get('metadata', '').strip()
        user_metadata_json = request.form.get('user_metadata', '').strip()

        meta_dict = {}
        if metadata_json:
            try:
                meta_dict = json.loads(metadata_json)
            except ValueError:
                flash(_('Invalid metadata JSON'))
                return redirect(url_for('create_post'))
            # Prevent manual setting of view counts via metadata
            meta_dict.pop('views', None)

        lat = request.form.get('lat')
        lon = request.form.get('lon')
        if lat and lon:
            meta_dict['lat'] = lat
            meta_dict['lon'] = lon
            locs = meta_dict.get('locations')
            if isinstance(locs, list):
                if locs:
                    locs[0]['lat'] = lat
                    locs[0]['lon'] = lon
                else:
                    meta_dict['locations'] = [{'lat': lat, 'lon': lon}]
            else:
                meta_dict['locations'] = [{'lat': lat, 'lon': lon}]
        else:
            meta_dict.pop('lat', None)
            meta_dict.pop('lon', None)
            meta_dict.pop('locations', None)

        lat_val = meta_dict.get('lat')
        lon_val = meta_dict.get('lon')
        if lat_val and lon_val:
            try:
                post.latitude = float(lat_val)
                post.longitude = float(lon_val)
            except ValueError:
                post.latitude = None
                post.longitude = None
        else:
            post.latitude = None
            post.longitude = None

        for key, value in meta_dict.items():
            db.session.add(PostMetadata(post=post, key=key, value=value))

        if user_metadata_json:
            try:
                user_meta_dict = json.loads(user_metadata_json)
            except ValueError:
                flash(_('Invalid user metadata JSON'))
                return redirect(url_for('create_post'))
            for key, value in user_meta_dict.items():
                db.session.add(
                    UserPostMetadata(post=post, user=current_user, key=key, value=value)
                )

        update_post_links(post)

        rev = Revision(post=post, user=current_user, title=title, body=body,
                       path=path, language=language, comment=comment,
                       byte_change=len(body))
        db.session.add(rev)

        req_id = request.form.get('request_id')
        if req_id:
            req = RequestedPost.query.get(int(req_id))
            if req:
                db.session.delete(req)

        db.session.commit()
        return redirect(url_for('document', language=post.language, doc_path=post.path))

    req_id = request.args.get('request_id')
    prefill_title = request.args.get('title')
    prefill_body = None
    prefill_path = request.args.get('path')
    prefill_language = request.args.get('language')
    if req_id:
        req = RequestedPost.query.get_or_404(req_id)
        prefill_title = req.title
        prefill_body = req.description
    return render_template(
        'post_form.html',
        action=_('Create'),
        metadata='',
        user_metadata='',
        prefill_title=prefill_title,
        prefill_body=prefill_body,
        prefill_path=prefill_path,
        prefill_language=prefill_language,
        request_id=req_id,
        lat=None,
        lon=None,
        languages=app.config['LANGUAGES'],
    )


@app.route('/post/<int:post_id>')
def post_detail(post_id: int):
    post = Post.query.get_or_404(post_id)
    views = increment_view_count(post)
    first_rev = (
        Revision.query.filter_by(post_id=post.id)
        .order_by(Revision.created_at.asc())
        .first()
    )
    created_at = first_rev.created_at if first_rev else None
    post_meta = {m.key: m.value for m in post.metadata}
    locations, warning = extract_locations(post_meta)
    post_lat = post.latitude
    post_lon = post.longitude
    address = None
    if post_lat is not None and post_lon is not None:
        address = reverse_geocode_coords(post_lat, post_lon)
        locations = [
            loc
            for loc in locations
            if not (
                loc['lat'] == post_lat and loc['lon'] == post_lon
            )
        ]
    location_list = []
    for loc in locations:
        name = reverse_geocode_coords(loc['lat'], loc['lon'])
        location_list.append({'lat': loc['lat'], 'lon': loc['lon'], 'name': name})
    geodata = extract_geodata(post_meta)
    if (
        post_lat is not None
        and post_lon is not None
        and not any(
            feat.get('geometry', {}).get('type') == 'Point'
            and feat.get('geometry', {}).get('coordinates') == [post_lon, post_lat]
            for feat in geodata
        )
    ):
        geodata.append(
            {
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [post_lon, post_lat]},
                'properties': {},
            }
        )
    meta_no_coords = post_meta.copy()
    for key in ('lat', 'lon', 'latitude', 'longitude', 'lng', 'locations'):
        meta_no_coords.pop(key, None)
    if warning:
        flash(_(warning))
    user_meta = {}
    citations = (
        PostCitation.query.filter_by(post_id=post.id)
        .order_by(PostCitation.created_at.desc())
        .all()
    )
    user_citations = []
    if current_user.is_authenticated:
        user_entries = UserPostMetadata.query.filter_by(
            post_id=post.id, user_id=current_user.id
        ).all()
        user_meta = {m.key: m.value for m in user_entries}
        user_citations = (
            UserPostCitation.query.filter_by(
                post_id=post.id, user_id=current_user.id
            )
            .order_by(UserPostCitation.created_at.desc())
            .all()
        )
    base = url_for('document', language=post.language, doc_path='')
    html_body, toc = render_markdown(post.body, base, with_toc=True)
    canonical_url = url_for('document', language=post.language, doc_path=post.path, _external=True)
    plain = re.sub('<[^<]+?>', '', html_body)
    meta_description = ' '.join(plain.split())[:160]
    year = created_at.year if created_at else datetime.utcnow().year
    key = re.sub(r'\W+', '', f"{post.author.username}{year}{post.id}")
    bibtex = (
        f"@misc{{{key}, title={{ {post.title} }}, author={{ {post.author.username} }}, "
        f"year={{ {year} }}, url={{ {canonical_url} }} }}"
    )
    return render_template(
        'post_detail.html',
        post=post,
        html_body=html_body,
        toc=toc,
        metadata=meta_no_coords,
        locations=location_list,
        geodata=geodata,
        lat=post_lat,
        lon=post_lon,
        user_metadata=user_meta,
        citations=citations,
        user_citations=user_citations,
        views=views,
        created_at=created_at,
        address=address,
        bibtex=bibtex,
        canonical_url=canonical_url,
        meta_description=meta_description,
    )


@app.route('/post/<int:post_id>/backlinks')
def post_backlinks(post_id: int):
    post = Post.query.get_or_404(post_id)
    backlinks = (
        PostLink.query.filter_by(target_id=post.id)
        .join(Post, PostLink.source_id == Post.id)
        .with_entities(Post)
        .order_by(Post.title)
        .all()
    )
    return render_template('backlinks.html', post=post, backlinks=backlinks)


@app.route('/post/<int:post_id>/watch', methods=['POST'])
@login_required
def watch_post(post_id: int):
    post = Post.query.get_or_404(post_id)
    existing = PostWatch.query.filter_by(post_id=post.id, user_id=current_user.id).first()
    if not existing:
        db.session.add(PostWatch(post_id=post.id, user_id=current_user.id))
        db.session.commit()
    return redirect(url_for('post_detail', post_id=post.id))


@app.route('/post/<int:post_id>/unwatch', methods=['POST'])
@login_required
def unwatch_post(post_id: int):
    post = Post.query.get_or_404(post_id)
    watch = PostWatch.query.filter_by(post_id=post.id, user_id=current_user.id).first()
    if watch:
        db.session.delete(watch)
        db.session.commit()
    return redirect(url_for('post_detail', post_id=post.id))


@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id: int):
    post = Post.query.get_or_404(post_id)
    if post.author_id != current_user.id and not current_user.is_admin():
        flash(_('Permission denied.'))
        return redirect(url_for('post_detail', post_id=post.id))
    rev = Revision(
        post=post,
        user=current_user,
        title=post.title,
        body=post.body,
        path=post.path,
        language=post.language,
        byte_change=-len(post.body),
    )
    db.session.add(rev)
    post.title = ''
    post.body = ''
    db.session.commit()
    flash(_('Post deleted.'))
    return redirect(url_for('index'))


@app.route('/<string:language>/<path:doc_path>')
def document(language: str, doc_path: str):
    if language not in app.config['LANGUAGES']:
        abort(404)
    post = Post.query.filter_by(language=language, path=doc_path).first()
    if not post:
        redirect_entry = Redirect.query.filter_by(
            language=language, old_path=doc_path
        ).first()
        if redirect_entry:
            return redirect(
                url_for('document', language=language, doc_path=redirect_entry.new_path)
            )
        title = doc_path.rsplit('/', 1)[-1]
        return redirect(
            url_for(
                'create_post',
                title=title,
                path=doc_path,
                language=language,
            )
        )
    views = increment_view_count(post)
    first_rev = (
        Revision.query.filter_by(post_id=post.id)
        .order_by(Revision.created_at.asc())
        .first()
    )
    created_at = first_rev.created_at if first_rev else None
    post_meta = {m.key: m.value for m in post.metadata}
    locations, warning = extract_locations(post_meta)
    post_lat = post.latitude
    post_lon = post.longitude
    address = None
    if post_lat is not None and post_lon is not None:
        address = reverse_geocode_coords(post_lat, post_lon)
        locations = [
            loc
            for loc in locations
            if not (
                loc['lat'] == post_lat and loc['lon'] == post_lon
            )
        ]
    location_list = []
    for loc in locations:
        name = reverse_geocode_coords(loc['lat'], loc['lon'])
        location_list.append({'lat': loc['lat'], 'lon': loc['lon'], 'name': name})
    geodata = extract_geodata(post_meta)
    if (
        post_lat is not None
        and post_lon is not None
        and not any(
            feat.get('geometry', {}).get('type') == 'Point'
            and feat.get('geometry', {}).get('coordinates') == [post_lon, post_lat]
            for feat in geodata
        )
    ):
        geodata.append(
            {
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [post_lon, post_lat]},
                'properties': {},
            }
        )
    meta_no_coords = post_meta.copy()
    for key in ('lat', 'lon', 'latitude', 'longitude', 'lng', 'locations'):
        meta_no_coords.pop(key, None)
    if warning:
        flash(_(warning))
    user_meta = {}
    citations = (
        PostCitation.query.filter_by(post_id=post.id)
        .order_by(PostCitation.created_at.desc())
        .all()
    )
    user_citations = []
    if current_user.is_authenticated:
        user_entries = UserPostMetadata.query.filter_by(
            post_id=post.id, user_id=current_user.id
        ).all()
        user_meta = {m.key: m.value for m in user_entries}
        user_citations = (
            UserPostCitation.query.filter_by(
                post_id=post.id, user_id=current_user.id
            )
            .order_by(UserPostCitation.created_at.desc())
            .all()
        )
    base = url_for('document', language=language, doc_path='')
    html_body, toc = render_markdown(post.body, base, with_toc=True)
    translations = Post.query.filter(
        Post.path == doc_path, Post.language != language
    ).all()
    return render_template(
        'post_detail.html',
        post=post,
        html_body=html_body,
        toc=toc,
        translations=translations,
        metadata=meta_no_coords,
        locations=location_list,
        geodata=geodata,
        lat=post_lat,
        lon=post_lon,
        user_metadata=user_meta,
        citations=citations,
        user_citations=user_citations,
        views=views,
        created_at=created_at,
        address=address,
    )


app.add_url_rule(
    '/docs/<string:language>/<path:doc_path>',
    view_func=document,
    endpoint='document_docs',
)


@app.route('/markdown/preview', methods=['POST'])
def markdown_preview():
    data = request.get_json() or {}
    text = data.get('text', '')
    language = data.get('language', 'en')
    base = url_for('document', language=language, doc_path='')
    html, _ = render_markdown(text, base)
    return {'html': str(Markup(html))}


@app.route('/og')
def og_preview():
    url = request.args.get('url', '').strip()
    return jsonify(fetch_open_graph(url))


@app.get('/geocode')
def geocode():
    address = request.args.get('address', '').strip()
    coords = geocode_address(address)
    if not coords:
        return jsonify({'error': _('Geocoding failed')}), 400
    lat, lon = coords
    return jsonify({'lat': lat, 'lon': lon})


@app.route('/citation/suggest', methods=['POST'])
def citation_suggest():
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    if not text:
        return {'error': _('Text is required')}, 400
    return {'results': suggest_citations(text)}


@app.route('/citation/suggest_line', methods=['POST'])
def citation_suggest_line():
    """Return citation suggestions for a single line of text.

    The client can call this endpoint repeatedly for each line so that
    suggestions are displayed incrementally instead of waiting for the entire
    body to be processed at once.
    """
    data = request.get_json() or {}
    line = data.get('line', '').strip()
    if not line:
        return {'error': _('Text is required')}, 400
    return {'results': suggest_citations(line)}


@app.route('/citation/fetch', methods=['POST'])
def fetch_citation():
    data = request.get_json() or {}
    title = data.get('title', '').strip()
    if not title:
        return {'error': _('Title is required')}, 400
    bibtex = fetch_bibtex_by_title(title)
    if not bibtex:
        return {'error': _('Citation not found')}, 404
    try:
        bib_db = bibtexparser.loads(bibtex)
        entry = bib_db.entries[0] if bib_db.entries else {}
    except Exception:
        return {'error': _('Failed to parse BibTeX')}, 500
    entry.pop('ID', None)
    entry.pop('ENTRYTYPE', None)
    doi = normalize_doi(entry.get('doi'))
    if doi:
        entry['doi'] = doi
    return {'part': entry, 'text': bibtex}


@app.route('/post/<int:post_id>/citation/new', methods=['POST'])
@login_required
def new_citation(post_id: int):
    post = Post.query.get_or_404(post_id)
    text = request.form.get('citation_text', '').strip()
    context = request.form.get('citation_context', '').strip()
    if not text:
        flash(_('Citation text is required.'))
        return redirect(url_for('post_detail', post_id=post.id))
    if is_url(text):
        entry = {'url': text}
        doi = None
    else:
        try:
            bib_db = bibtexparser.loads(text)
            entry = bib_db.entries[0] if bib_db.entries else {}
        except Exception:
            flash(_('Failed to parse BibTeX'))
            return redirect(url_for('post_detail', post_id=post.id))
        entry.pop('ID', None)
        entry.pop('ENTRYTYPE', None)
        doi = normalize_doi(entry.get('doi'))
        if doi:
            entry['doi'] = doi
    # Ensure uniqueness by DOI or citation text
    if doi:
        existing = PostCitation.query.filter_by(post_id=post.id, doi=doi).first()
        if not existing:
            existing = UserPostCitation.query.filter_by(post_id=post.id, doi=doi).first()
        if existing:
            flash(_('Citation with this DOI already exists.'))
            return redirect(url_for('post_detail', post_id=post.id))
    else:
        existing = PostCitation.query.filter_by(post_id=post.id, citation_text=text).first()
        if not existing:
            existing = UserPostCitation.query.filter_by(post_id=post.id, citation_text=text).first()
        if existing:
            flash(_('Citation with this text already exists.'))
            return redirect(url_for('post_detail', post_id=post.id))
    if current_user.id == post.author_id or current_user.is_admin():
        citation = PostCitation(
            post=post,
            user=current_user,
            citation_part=entry,
            citation_text=text,
            context=context,
            doi=doi,
            bibtex_raw=text,
            bibtex_fields=entry,
        )
    else:
        citation = UserPostCitation(
            post=post,
            user=current_user,
            citation_part=entry,
            citation_text=text,
            context=context,
            doi=doi,
            bibtex_raw=text,
            bibtex_fields=entry,
        )
    db.session.add(citation)
    watcher_ids = {
        w.user_id for w in PostWatch.query.filter_by(post_id=post.id).all()
    }
    watcher_ids.add(post.author_id)
    link = url_for('post_detail', post_id=post.id)
    for uid in watcher_ids:
        if uid != current_user.id:
            msg = _('Citation added to "%(title)s".', title=post.title)
            db.session.add(Notification(user_id=uid, message=msg, link=link))
    db.session.commit()
    return redirect(url_for('post_detail', post_id=post.id))


@app.route('/post/<int:post_id>/citation/<int:cid>/edit', methods=['GET', 'POST'])
@login_required
def edit_citation(post_id: int, cid: int):
    post = Post.query.get_or_404(post_id)
    citation = PostCitation.query.filter_by(id=cid, post_id=post.id).first()
    if citation is None:
        citation = UserPostCitation.query.filter_by(id=cid, post_id=post.id).first_or_404()
    if current_user.id != citation.user_id and not current_user.is_admin():
        flash(_('Permission denied.'))
        return redirect(url_for('post_detail', post_id=post.id))
    if request.method == 'POST':
        text = request.form.get('citation_text', '').strip()
        context = request.form.get('citation_context', '').strip()
        if not text:
            flash(_('Citation text is required.'))
            return redirect(url_for('edit_citation', post_id=post.id, cid=cid))
        if is_url(text):
            entry = {'url': text}
            doi = None
        else:
            try:
                bib_db = bibtexparser.loads(text)
                entry = bib_db.entries[0] if bib_db.entries else {}
            except Exception:
                flash(_('Failed to parse BibTeX'))
                return redirect(url_for('edit_citation', post_id=post.id, cid=cid))
            entry.pop('ID', None)
            entry.pop('ENTRYTYPE', None)
            doi = normalize_doi(entry.get('doi'))
            if doi:
                entry['doi'] = doi
                existing = (
                    PostCitation.query.filter(
                        PostCitation.post_id == post.id,
                        PostCitation.doi == doi,
                        PostCitation.id != citation.id,
                    ).first()
                    or UserPostCitation.query.filter(
                        UserPostCitation.post_id == post.id,
                        UserPostCitation.doi == doi,
                        UserPostCitation.id != citation.id,
                    ).first()
                )
                if existing:
                    flash(_('Citation with this DOI already exists.'))
                    return redirect(url_for('edit_citation', post_id=post.id, cid=cid))
        if doi is None:
            existing = (
                PostCitation.query.filter(
                    PostCitation.post_id == post.id,
                    PostCitation.citation_text == text,
                    PostCitation.id != citation.id,
                ).first()
                or UserPostCitation.query.filter(
                    UserPostCitation.post_id == post.id,
                    UserPostCitation.citation_text == text,
                    UserPostCitation.id != citation.id,
                ).first()
            )
            if existing:
                flash(_('Citation with this text already exists.'))
                return redirect(url_for('edit_citation', post_id=post.id, cid=cid))
        citation.citation_part = entry
        citation.citation_text = text
        citation.context = context
        citation.doi = doi
        citation.bibtex_raw = text
        citation.bibtex_fields = entry
        watcher_ids = {
            w.user_id for w in PostWatch.query.filter_by(post_id=post.id).all()
        }
        watcher_ids.add(post.author_id)
        link = url_for('post_detail', post_id=post.id)
        for uid in watcher_ids:
            if uid != current_user.id:
                msg = _('Citation updated on "%(title)s".', title=post.title)
                db.session.add(Notification(user_id=uid, message=msg, link=link))
        db.session.commit()
        return redirect(url_for('post_detail', post_id=post.id))
    part_json = json.dumps(citation.citation_part)
    return render_template('citation_form.html', action=_('Edit'), citation=citation,
                           citation_part=part_json, post=post)


@app.route('/post/<int:post_id>/citation/<int:cid>/delete', methods=['POST'])
@login_required
def delete_citation(post_id: int, cid: int):
    post = Post.query.get_or_404(post_id)
    citation = PostCitation.query.filter_by(id=cid, post_id=post.id).first()
    if citation is None:
        citation = UserPostCitation.query.filter_by(id=cid, post_id=post.id).first_or_404()
    if current_user.id != citation.user_id and not current_user.is_admin():
        flash(_('Permission denied.'))
        return redirect(url_for('post_detail', post_id=post.id))
    db.session.delete(citation)
    watcher_ids = {
        w.user_id for w in PostWatch.query.filter_by(post_id=post.id).all()
    }
    watcher_ids.add(post.author_id)
    link = url_for('post_detail', post_id=post.id)
    for uid in watcher_ids:
        if uid != current_user.id:
            msg = _('Citation deleted from "%(title)s".', title=post.title)
            db.session.add(Notification(user_id=uid, message=msg, link=link))
    db.session.commit()
    return redirect(url_for('post_detail', post_id=post.id))


@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id: int):
    post = Post.query.get_or_404(post_id)
    if not current_user.can_edit_posts():
        abort(403)
    if request.method == 'POST':
        old_path = post.path
        old_language = post.language
        old_body = post.body
        comment = request.form.get('comment', '').strip()
        rev = Revision(post=post, user=current_user, title=post.title,
                       body=old_body, path=post.path, language=post.language,
                       comment=comment)
        db.session.add(rev)
        post.title = request.form['title']
        post.body = request.form['body']
        new_path = request.form['path'].strip()
        new_language = request.form['language']
        if not new_path:
            new_path = generate_unique_path(post.title, new_language)
        elif (
            (new_path != old_path or new_language != old_language)
            and Post.query.filter_by(path=new_path, language=new_language)
            .filter(Post.id != post.id)
            .first()
        ):
            flash(_('Path already exists'))
            return redirect(url_for('edit_post', post_id=post.id))
        post.path = new_path
        post.language = new_language
        if post.path != old_path:
            db.session.add(
                Redirect(old_path=old_path, new_path=post.path, language=old_language)
            )
        tag_names = [t.strip() for t in request.form['tags'].split(',') if t.strip()]
        post.tags = []
        for name in dict.fromkeys(tag_names):
            tag = Tag.query.filter_by(name=name).first()
            if not tag:
                tag = Tag(name=name)
                db.session.add(tag)
            post.tags.append(tag)
        metadata_json = request.form.get('metadata', '').strip()
        user_metadata_json = request.form.get('user_metadata', '').strip()

        meta_dict = {}
        if metadata_json:
            try:
                meta_dict = json.loads(metadata_json)
            except ValueError:
                flash(_('Invalid metadata JSON'))
                return redirect(url_for('edit_post', post_id=post.id))
            # Prevent tampering with view counts through metadata
            meta_dict.pop('views', None)

        lat = request.form.get('lat')
        lon = request.form.get('lon')
        if lat and lon:
            meta_dict['lat'] = lat
            meta_dict['lon'] = lon
            locs = meta_dict.get('locations')
            if isinstance(locs, list):
                if locs:
                    locs[0]['lat'] = lat
                    locs[0]['lon'] = lon
                else:
                    meta_dict['locations'] = [{'lat': lat, 'lon': lon}]
            else:
                meta_dict['locations'] = [{'lat': lat, 'lon': lon}]
        else:
            meta_dict.pop('lat', None)
            meta_dict.pop('lon', None)
            meta_dict.pop('locations', None)

        lat_val = meta_dict.get('lat')
        lon_val = meta_dict.get('lon')
        if lat_val and lon_val:
            try:
                post.latitude = float(lat_val)
                post.longitude = float(lon_val)
            except ValueError:
                post.latitude = None
                post.longitude = None
        else:
            post.latitude = None
            post.longitude = None

        current_views = PostMetadata.query.filter_by(post_id=post.id, key='views').first()

        PostMetadata.query.filter(
            PostMetadata.post_id == post.id,
            PostMetadata.key != 'views',
        ).delete(synchronize_session=False)

        for key, value in meta_dict.items():
            db.session.add(PostMetadata(post=post, key=key, value=value))

        if not current_views:
            db.session.add(PostMetadata(post=post, key='views', value='0'))
        if user_metadata_json:
            try:
                user_meta_dict = json.loads(user_metadata_json)
            except ValueError:
                flash(_('Invalid user metadata JSON'))
                return redirect(url_for('edit_post', post_id=post.id))
            UserPostMetadata.query.filter_by(post_id=post.id, user_id=current_user.id).delete()
            for key, value in user_meta_dict.items():
                db.session.add(
                    UserPostMetadata(post=post, user=current_user, key=key, value=value)
                )
        else:
            UserPostMetadata.query.filter_by(post_id=post.id, user_id=current_user.id).delete()
        update_post_links(post)
        watcher_ids = {
            w.user_id for w in PostWatch.query.filter_by(post_id=post.id).all()
        }
        watcher_ids.add(post.author_id)
        link = url_for('post_detail', post_id=post.id)
        for uid in watcher_ids:
            if uid != current_user.id:
                msg = _('Post "%(title)s" was updated.', title=post.title)
                db.session.add(Notification(user_id=uid, message=msg, link=link))
        rev.byte_change = len(post.body) - len(old_body)
        db.session.commit()
        return redirect(url_for('document', language=post.language, doc_path=post.path))
    tags_str = ', '.join([t.name for t in post.tags])
    post_meta_dict = {m.key: m.value for m in post.metadata}
    post_meta = json.dumps(post_meta_dict) if post_meta_dict else ''
    lat = post_meta_dict.get('lat')
    lon = post_meta_dict.get('lon')
    user_entries = UserPostMetadata.query.filter_by(post_id=post.id, user_id=current_user.id).all()
    user_meta_dict = {m.key: m.value for m in user_entries}
    user_meta = json.dumps(user_meta_dict) if user_meta_dict else ''
    return render_template('post_form.html', action=_('Edit'), post=post, tags=tags_str,
                           metadata=post_meta, user_metadata=user_meta, lat=lat, lon=lon,
                           languages=app.config['LANGUAGES'])


@app.route('/post/<int:post_id>/history')
def history(post_id: int):
    post = Post.query.get_or_404(post_id)
    revisions = Revision.query.filter_by(post_id=post_id).order_by(Revision.created_at.desc()).all()
    return render_template('history.html', post=post, revisions=revisions)


@app.route('/post/<int:post_id>/diff/<int:rev_id>')
def revision_diff(post_id: int, rev_id: int):
    post = Post.query.get(post_id)
    revision = Revision.query.get_or_404(rev_id)
    if post and revision.post_id != post.id:
        abort(404)
    current_body = post.body if post else ''
    diff = difflib.unified_diff(
        revision.body.splitlines(),
        current_body.splitlines(),
        fromfile=f'rev {revision.id}',
        tofile='current',
        lineterm='',
    )
    post_exists = post is not None
    if not post_exists:
        post = SimpleNamespace(id=post_id, title=revision.title)
    return render_template(
        'diff.html',
        post=post,
        revision=revision,
        diff='\n'.join(diff),
        post_exists=post_exists,
    )


@app.route('/post/<int:post_id>/revert/<int:rev_id>', methods=['POST'])
@login_required
def revert_revision(post_id: int, rev_id: int):
    if not current_user.can_edit_posts():
        abort(403)
    post = Post.query.get_or_404(post_id)
    revision = Revision.query.get_or_404(rev_id)
    if revision.post_id != post.id:
        abort(404)

    # Save current state before reverting
    rev = Revision(
        post=post,
        user=current_user,
        title=post.title,
        body=post.body,
        path=post.path,
        language=post.language,
    )
    db.session.add(rev)

    # Overwrite post fields with the selected revision
    post.title = revision.title
    post.body = revision.body
    post.path = revision.path
    post.language = revision.language

    watcher_ids = {
        w.user_id for w in PostWatch.query.filter_by(post_id=post.id).all()
    }
    watcher_ids.add(post.author_id)
    link = url_for('post_detail', post_id=post.id)
    for uid in watcher_ids:
        if uid != current_user.id:
            msg = _('Post "%(title)s" was updated.', title=post.title)
            db.session.add(Notification(user_id=uid, message=msg, link=link))

    db.session.commit()
    flash(_('Post reverted.'))
    return redirect(url_for('document', language=post.language, doc_path=post.path))


@app.route('/admin/posts')
@login_required
def admin_posts():
    if not current_user.is_admin():
        abort(403)
    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '').strip()
    query = Post.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Post.title.ilike(like), Post.path.ilike(like)))
    pagination = query.order_by(Post.id.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/posts.html', pagination=pagination, q=q)


@app.route('/admin/stats')
@login_required
def admin_stats():
    if not current_user.is_admin():
        abort(403)
    stats = {
        'users': User.query.count(),
        'posts': Post.query.count(),
        'tags': Tag.query.count(),
        'citations': PostCitation.query.count(),
    }
    return render_template('admin/stats.html', stats=stats)


@app.route('/admin/db-status')
@login_required
def admin_db_status():
    if not current_user.is_admin():
        abort(403)
    inspector = inspect(db.engine)
    tables = []
    perf = {}
    with db.engine.connect() as conn:
        for name in inspector.get_table_names():
            try:
                count = conn.execute(text(f'SELECT COUNT(*) FROM {name}')).scalar() or 0
            except Exception:
                count = 0
            tables.append({'name': name, 'count': count})
        # Gather basic performance metrics for SQLite databases
        if db.engine.dialect.name == 'sqlite':
            for pragma in ['page_size', 'page_count', 'freelist_count', 'cache_size']:
                try:
                    perf[pragma] = conn.execute(text(f'PRAGMA {pragma}')).scalar()
                except Exception:
                    perf[pragma] = None
            try:
                size = (perf.get('page_size') or 0) * (perf.get('page_count') or 0)
                perf['database_size'] = size
            except Exception:
                perf['database_size'] = None
    db_url = str(db.engine.url)
    return render_template('admin/db_status.html', tables=tables, db_url=db_url, perf=perf)

@app.route('/admin/stats/posts_over_time')
@login_required
def admin_stats_posts_over_time():
    if not current_user.is_admin():
        abort(403)
    daily = (
        db.session.query(func.strftime('%Y-%m-%d', Post.created_at), func.count())
        .group_by(func.strftime('%Y-%m-%d', Post.created_at))
        .order_by(func.strftime('%Y-%m-%d', Post.created_at))
        .all()
    )
    weekly = (
        db.session.query(func.strftime('%Y-%W', Post.created_at), func.count())
        .group_by(func.strftime('%Y-%W', Post.created_at))
        .order_by(func.strftime('%Y-%W', Post.created_at))
        .all()
    )
    monthly = (
        db.session.query(func.strftime('%Y-%m', Post.created_at), func.count())
        .group_by(func.strftime('%Y-%m', Post.created_at))
        .order_by(func.strftime('%Y-%m', Post.created_at))
        .all()
    )
    yearly = (
        db.session.query(func.strftime('%Y', Post.created_at), func.count())
        .group_by(func.strftime('%Y', Post.created_at))
        .order_by(func.strftime('%Y', Post.created_at))
        .all()
    )
    result = {
        'daily': [{'period': d, 'count': c} for d, c in daily],
        'weekly': [{'period': w, 'count': c} for w, c in weekly],
        'monthly': [{'period': m, 'count': c} for m, c in monthly],
        'yearly': [{'period': y, 'count': c} for y, c in yearly],
    }
    return jsonify(result)


@app.route('/admin/view-stats')
@login_required
def admin_view_stats():
    if not current_user.is_admin():
        abort(403)
    total_views = PostView.query.count()
    total_visitors = db.session.query(func.count(func.distinct(PostView.ip_address))).scalar() or 0
    return render_template('admin/view_stats.html', total_views=total_views, total_visitors=total_visitors)


@app.route('/admin/view-stats/top_posts')
@login_required
def admin_view_stats_top_posts():
    if not current_user.is_admin():
        abort(403)
    now = datetime.utcnow()
    def top_since(delta):
        start = now - delta
        data = (
            db.session.query(Post.title, func.count(PostView.id).label('views'))
            .select_from(PostView)
            .join(Post)
            .filter(PostView.viewed_at >= start)
            .group_by(Post.id)
            .order_by(func.count(PostView.id).desc())
            .limit(5)
            .all()
        )
        return [{'title': title, 'views': views} for title, views in data]
    result = {
        'daily': top_since(timedelta(days=1)),
        'weekly': top_since(timedelta(days=7)),
        'monthly': top_since(timedelta(days=30)),
        'yearly': top_since(timedelta(days=365)),
    }
    return jsonify(result)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if not current_user.is_admin():
        abort(403)
    title = get_setting('site_title', '')
    title_style = get_setting('site_title_style', '')
    home_page = get_setting('home_page_path', '')
    timezone_value = get_setting('timezone', 'UTC')
    rss_enabled_val = get_setting('rss_enabled', 'false')
    rss_limit = get_setting('rss_limit', '20')
    head_tags = get_setting('head_tags', '')
    category_tags = get_setting('post_categories', '')
    breadcrumb_limit = get_setting('breadcrumb_limit', '10')
    if request.method == 'POST':

        title = request.form.get('site_title', title).strip()
        title_style = request.form.get('site_title_style', title_style).strip()
        home_page = request.form.get('home_page_path', home_page).strip()
        tz_input = request.form.get('timezone', timezone_value).strip() or 'UTC'
        tz_norm = normalize_timezone(tz_input)
        if tz_norm is None:
            flash(_('Invalid timezone'))
            return redirect(url_for('settings'))
        timezone_value = tz_norm
        rss_enabled_val = 'rss_enabled' in request.form
        rss_limit = request.form.get('rss_limit', rss_limit).strip() or '20'
        breadcrumb_limit = request.form.get('breadcrumb_limit', breadcrumb_limit).strip() or '10'
        head_tags_input = request.form.get('head_tags', head_tags)
        head_tags = "\n".join(line.strip() for line in head_tags_input.splitlines() if line.strip())
        category_tags = request.form.get('post_categories', category_tags).strip()
        # Validate category mapping JSON
        try:
            if category_tags:
                json.loads(category_tags)
        except json.JSONDecodeError:
            flash(_('Invalid category JSON'))
            return redirect(url_for('settings'))

        title_setting = Setting.query.filter_by(key='site_title').first()
        if title_setting:
            title_setting.value = title
        else:
            title_setting = Setting(key='site_title', value=title)
            db.session.add(title_setting)

        style_setting = Setting.query.filter_by(key='site_title_style').first()
        if style_setting:
            style_setting.value = title_style
        else:
            db.session.add(Setting(key='site_title_style', value=title_style))

        if 'home_page_path' in request.form:
            home_page = request.form['home_page_path'].strip()
            home_setting = Setting.query.filter_by(key='home_page_path').first()
            if home_setting:
                home_setting.value = home_page
            else:
                db.session.add(Setting(key='home_page_path', value=home_page))

        if 'timezone' in request.form:
            tz_setting = Setting.query.filter_by(key='timezone').first()
            if tz_setting:
                tz_setting.value = timezone_value
            else:
                db.session.add(Setting(key='timezone', value=timezone_value))

        rss_setting = Setting.query.filter_by(key='rss_enabled').first()
        rss_value = 'true' if rss_enabled_val else 'false'
        if rss_setting:
            rss_setting.value = rss_value
        else:
            db.session.add(Setting(key='rss_enabled', value=rss_value))

        limit_setting = Setting.query.filter_by(key='rss_limit').first()
        if limit_setting:
            limit_setting.value = rss_limit
        else:
            db.session.add(Setting(key='rss_limit', value=rss_limit))
        head_setting = Setting.query.filter_by(key='head_tags').first()
        if head_setting:
            head_setting.value = head_tags
        else:
            db.session.add(Setting(key='head_tags', value=head_tags))
        cat_setting = Setting.query.filter_by(key='post_categories').first()
        if cat_setting:
            cat_setting.value = category_tags
        else:
            db.session.add(Setting(key='post_categories', value=category_tags))
        breadcrumb_setting = Setting.query.filter_by(key='breadcrumb_limit').first()
        if breadcrumb_setting:
            breadcrumb_setting.value = breadcrumb_limit
        else:
            db.session.add(Setting(key='breadcrumb_limit', value=breadcrumb_limit))

        db.session.commit()
        flash(_('Settings updated.'))
        return redirect(url_for('settings'))
    return render_template(
        'settings.html',
        site_title=title,
        site_title_style=title_style,
        home_page_path=home_page,
        timezone=timezone_value,
        rss_enabled=rss_enabled_val.lower() in ['true', '1', 'yes', 'on'],
        rss_limit=rss_limit,
        head_tags=head_tags,
        post_categories=category_tags,
        breadcrumb_limit=breadcrumb_limit
    )


@app.route('/tags')
def tag_list():
    tags = (
        Tag.query.filter(~Tag.name.in_(['deleted', '[deleted]']))
        .order_by(Tag.name)
        .all()
    )
    tag_locations = []
    tag_posts_data = []
    location_counts = {}
    for tag in tags:
        coords = None
        # Sort posts by ID so that coordinate selection is deterministic
        for p in sorted(tag.posts, key=lambda p: p.id):
            if not p.title or not p.body:
                continue
            if p.latitude is not None and p.longitude is not None:
                coords = (p.latitude, p.longitude)
                break
            meta = {m.key: m.value for m in p.metadata}
            lat = meta.get('lat') or meta.get('latitude')
            lon = meta.get('lon') or meta.get('longitude')
            if lat is not None and lon is not None:
                try:
                    coords = (float(lat), float(lon))
                    break
                except ValueError:
                    continue
        if coords is not None:
            lat, lon = coords
            key = (round(lat, 4), round(lon, 4))
            count = location_counts.get(key, 0)
            if count:
                angle = (count - 1) * (2 * math.pi / 6)
                radius = 0.02 * ((count - 1) // 6 + 1)
                lat += radius * math.cos(angle)
                lon += radius * math.sin(angle) / max(math.cos(math.radians(lat)), 0.01)
            location_counts[key] = count + 1
            tag_locations.append(
                {
                    'name': tag.name,
                    'lat': lat,
                    'lon': lon,
                    'url': url_for('tag_filter', name=tag.name),
                }
            )
        def haversine(lat1, lon1, lat2, lon2):
            r = 6371
            p1 = math.radians(lat1)
            p2 = math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlambda = math.radians(lon2 - lon1)
            a = (
                math.sin(dphi / 2) ** 2
                + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
            )
            return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        scored_posts = []
        for p in tag.posts:
            if not p.title or not p.body:
                continue
            views = get_view_count(p)
            plat, plon = p.latitude, p.longitude
            if plat is None or plon is None:
                meta = {m.key: m.value for m in p.metadata}
                plat = meta.get('lat') or meta.get('latitude')
                plon = meta.get('lon') or meta.get('longitude')
                if plat is not None and plon is not None:
                    try:
                        plat = float(plat)
                        plon = float(plon)
                    except ValueError:
                        plat = plon = None
            distance = (
                haversine(lat, lon, plat, plon)
                if coords is not None and plat is not None and plon is not None
                else float('inf')
            )
            snippet = (p.body[:150] + '...') if len(p.body) > 150 else p.body
            scored_posts.append((distance, views, p, snippet))

        scored_posts.sort(key=lambda x: (0 if x[0] <= 100 else 1, -x[1], x[0]))
        posts_data = []
        for distance, views, p, snippet in scored_posts[:5]:
            posts_data.append(
                {
                    'title': p.display_title,
                    'url': url_for('document', language=p.language, doc_path=p.path),
                    'snippet': snippet,
                    'views': views,
                    'author': p.author.username,
                }
            )
        tag_posts_data.append({'tag': tag.name, 'posts': posts_data})
    tag_locations_json = json.dumps(tag_locations)
    tag_posts_json = json.dumps(tag_posts_data)
    return render_template(
        'tag_list.html',
        tag_locations_json=tag_locations_json,
        tag_posts_json=tag_posts_json,
        tag_modal_new_tab=(
            current_user.is_authenticated and current_user.tag_modal_new_tab
        ),
    )


@app.route('/tag/<string:name>')
def tag_filter(name: str):
    tag = resolve_tag(name)
    if not tag:
        abort(404)
    page = request.args.get('page', 1, type=int)
    categories = get_category_tags()
    syns = get_tag_synonyms(tag.name)
    query = (
        Post.query.join(Post.tags)
        .filter(func.lower(Tag.name).in_(syns), Post.title != '', Post.body != '')
    )
    pagination = query.order_by(Post.id.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template(
        'index.html', pagination=pagination, tag=tag, categories=categories
    )


@app.route('/search')
def search():
    q = request.args.get('q', '').strip()
    tags_raw = request.args.get('tags', '').strip()
    tag_names = [t for t in [s.strip() for s in tags_raw.split(',')] if t]
    key = request.args.get('key', '').strip()
    value_raw = request.args.get('value', '').strip()
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    radius = request.args.get('radius', type=float)
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('SEARCH_RESULTS_PER_PAGE', 20)

    # Gather distinct metadata keys for the dropdown and include title/path
    meta_keys = [k for (k,) in db.session.query(PostMetadata.key).distinct().all()]
    meta_keys = ['title', 'path'] + sorted(meta_keys)
    all_tags = [t.name for t in Tag.query.order_by(Tag.name).all()]

    posts_query = None
    examples = None
    if q:
        expanded_q = expand_with_synonyms(q)
        ids = [
            row[0]
            for row in db.session.execute(
                text('SELECT rowid FROM post_fts WHERE post_fts MATCH :q'),
                {'q': expanded_q},
            )
        ]
        posts_query = Post.query.filter(Post.id.in_(ids)) if ids else Post.query.filter(False)
    elif key and value_raw:
        try:
            value = json.loads(value_raw)
        except ValueError:
            value = value_raw
        if key == 'title':
            posts_query = Post.query.filter(Post.title.ilike(f'%{value}%'))
        elif key == 'path':
            posts_query = Post.query.filter(Post.path.ilike(f'%{value}%'))
        else:
            posts_query = Post.query.join(PostMetadata).filter(
                PostMetadata.key == key, PostMetadata.value == value
            )
    elif lat is not None and lon is not None and radius is not None:
        posts_query = Post.query
    else:
        # Provide example posts to illustrate expected input format
        examples = Post.query.limit(5).all()
    posts = None
    pagination = None
    if posts_query is not None:
        for name in tag_names:
            syns = get_tag_synonyms(name)
            posts_query = posts_query.filter(
                Post.tags.any(func.lower(Tag.name).in_(syns))
            )

        if lat is not None and lon is not None and radius is not None:
            all_posts = posts_query.all()
            filtered_posts = [
                p
                for p in all_posts
                if p.latitude is not None
                and p.longitude is not None
                and geopy_distance((lat, lon), (p.latitude, p.longitude)).km <= radius
            ]
            total = len(filtered_posts)
            start = (page - 1) * per_page
            end = start + per_page
            items = filtered_posts[start:end]
            pagination = SimpleNamespace(
                items=items,
                page=page,
                per_page=per_page,
                total=total,
                pages=math.ceil(total / per_page) if per_page else 0,
                has_prev=page > 1,
                has_next=page < math.ceil(total / per_page),
                prev_num=page - 1,
                next_num=page + 1,
            )
            posts = items
        else:
            posts_query = posts_query.order_by(Post.id.desc())
            pagination = posts_query.paginate(page=page, per_page=per_page, error_out=False)
            posts = pagination.items

    coords_json = (
        json.dumps([{'lat': p.latitude, 'lon': p.longitude} for p in posts])
        if posts
        else '[]'
    )

    return render_template(
        'search.html',
        posts=posts,
        pagination=pagination,
        q=q,
        tags=tags_raw,
        all_tags=all_tags,
        key=key,
        value=value_raw,
        keys=meta_keys,
        examples=examples,
        lat=lat,
        lon=lon,
        radius=radius,
        coords_json=coords_json,
    )


@app.route('/citations/stats')
def citation_stats():
    page = request.args.get('page', 1, type=int)
    all_citations = (
        db.session.query(
            PostCitation.doi.label('doi'),
            PostCitation.citation_text.label('citation_text'),
            PostCitation.post_id.label('post_id'),
        )
        .union_all(
            db.session.query(
                UserPostCitation.doi.label('doi'),
                UserPostCitation.citation_text.label('citation_text'),
                UserPostCitation.post_id.label('post_id'),
            )
        )
        .subquery()
    )

    query = (
        db.session.query(
            all_citations.c.doi,
            all_citations.c.citation_text,
            func.count().label('count'),
            func.group_concat(all_citations.c.post_id, ',').label('post_ids'),
        )
        .group_by(all_citations.c.doi, all_citations.c.citation_text)
        .order_by(func.count().desc())
    )

    pagination = query.paginate(page=page, per_page=20, error_out=False)
    rows = pagination.items

    post_ids = set()
    for row in rows:
        if row.post_ids:
            post_ids.update(row.post_ids.split(','))

    posts_by_id = {
        p.id: p for p in Post.query.filter(Post.id.in_(post_ids)).all()
    }

    stats = []
    for row in rows:
        ids = [int(pid) for pid in row.post_ids.split(',')] if row.post_ids else []
        posts_list = [posts_by_id[i] for i in ids if i in posts_by_id]
        stats.append(
            {
                'doi': row.doi,
                'citation_text': row.citation_text,
                'count': row.count,
                'posts': posts_list,
            }
        )

    return render_template('citation_stats.html', stats=stats, pagination=pagination)


@app.route('/citations/delete', methods=['POST'])
def delete_citation_everywhere():
    if not current_user.is_admin():
        flash(_('Permission denied.'))
        return redirect(url_for('citation_stats'))

    doi = request.form.get('doi')
    citation_text = request.form.get('citation_text')
    page = request.form.get('page', type=int)

    if citation_text is not None:
        citation_text = citation_text.replace('\r\n', '\n')

    query = PostCitation.query.filter_by(citation_text=citation_text)
    user_query = UserPostCitation.query.filter_by(citation_text=citation_text)
    if doi:
        query = query.filter_by(doi=doi)
        user_query = user_query.filter_by(doi=doi)
    else:
        query = query.filter(PostCitation.doi.is_(None))
        user_query = user_query.filter(UserPostCitation.doi.is_(None))

    query.delete(synchronize_session=False)
    user_query.delete(synchronize_session=False)
    db.session.commit()

    if page:
        return redirect(url_for('citation_stats', page=page))
    return redirect(url_for('citation_stats'))


@app.route('/admin/citations/delete-url', methods=['GET', 'POST'])
@login_required
def admin_delete_citation_url():
    if not current_user.is_admin():
        abort(403)
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if url:
            url = url.replace('\r\n', '\n')
            query = PostCitation.query.filter(
                or_(
                    PostCitation.citation_text == url,
                    PostCitation.citation_part.contains({'url': url}),
                )
            )
            user_query = UserPostCitation.query.filter(
                or_(
                    UserPostCitation.citation_text == url,
                    UserPostCitation.citation_part.contains({'url': url}),
                )
            )
            query.delete(synchronize_session=False)
            user_query.delete(synchronize_session=False)
            db.session.commit()
            flash(_('Citations deleted.'))
            return redirect(url_for('admin_delete_citation_url'))
    return render_template('admin/delete_citation_url.html')


if __name__ == '__main__':
    with app.app_context():
        PostWatch.__table__.create(bind=db.engine, checkfirst=True)
        Notification.__table__.create(bind=db.engine, checkfirst=True)
        PostMetadata.__table__.create(bind=db.engine, checkfirst=True)
        UserPostMetadata.__table__.create(bind=db.engine, checkfirst=True)
        PostCitation.__table__.create(bind=db.engine, checkfirst=True)
        UserPostCitation.__table__.create(bind=db.engine, checkfirst=True)
        RequestedPost.__table__.create(bind=db.engine, checkfirst=True)
        db.create_all()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 5000))
    ssl_cert = os.getenv("SSL_CERT_FILE")
    ssl_key = os.getenv("SSL_KEY_FILE")
    ssl_context = None
    if ssl_cert and ssl_key:
        ssl_context = (ssl_cert, ssl_key)
    elif ssl_cert:
        ssl_context = ssl_cert
    socketio.run(app, host=host, port=port, debug=True, ssl_context=ssl_context)
