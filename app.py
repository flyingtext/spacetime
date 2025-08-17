import difflib
import json
import os
import re
import markdown
from collections import Counter
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring
from urllib.parse import urlparse, quote

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
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, login_user, login_required,
                         logout_user, current_user, UserMixin)
from flask_socketio import SocketIO
from werkzeug.security import generate_password_hash, check_password_hash
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markupsafe import Markup, escape
import requests
from habanero import Crossref
import bibtexparser
from types import SimpleNamespace
from sqlalchemy import func, event, or_, text, inspect
from sqlalchemy.exc import NoSuchTableError
from flask_babel import Babel, _, get_locale
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
from geopy.distance import distance as geopy_distance
from langdetect import detect, DetectorFactory, LangDetectException
import zoneinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

socketio = SocketIO(app)
cr = Crossref()

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


STOPWORDS: dict[str, set[str]] = {
    'en': {
        'the', 'and', 'or', 'for', 'with', 'to', 'of', 'a', 'an', 'in', 'on',
        'at', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'that', 'this', 'it', 'as', 'we', 'you', 'he', 'she', 'they', 'them',
        'his', 'her', 'its', 'our', 'their', 'have', 'has', 'had', 'do', 'does',
        'did'
    },
    'fr': {
        'le', 'la', 'les', 'un', 'une', 'et', 'ou', 'pour', 'avec', 'à', 'de',
        'des', 'du', 'est', 'sont', 'il', 'elle', 'nous', 'vous', 'ce', 'ces'
    },
    'de': {
        'der', 'die', 'das', 'und', 'oder', 'für', 'mit', 'zu', 'auf', 'ein',
        'eine', 'ist', 'sind', 'es', 'ich', 'du', 'er', 'sie', 'wir', 'ihr'
    },
    'ko': {
        '그리고', '또는', '그러나', '그래서', '은', '는', '이', '가', '을', '를',
        '에', '에서', '에게', '과', '와', '도', '로', '으로', '의'
    },
    'ja': {
        'そして', 'または', 'しかし', 'で', 'は', 'が', 'を', 'に', 'へ', 'と',
        'も', 'の', 'から', 'まで'
    },
    'zh': {
        '和', '或', '但是', '在', '是', '的', '了', '與', '及', '而且'
    },
}


def extract_keywords(sentence: str, max_words: int = 5) -> list[str]:
    """Return up to ``max_words`` keywords from *sentence*.

    Detects the sentence language and removes language-specific stopwords
    before calculating word frequency.
    """

    try:
        lang = detect(sentence)
    except LangDetectException:
        lang = 'en'
    lang = lang.split('-')[0]
    stopwords = STOPWORDS.get(lang, STOPWORDS['en'])
    if lang in {'ja', 'zh'}:
        words = [c for c in sentence if re.match(r"\w", c)]
    else:
        words = re.findall(r"\b\w+\b", sentence.lower())
    words = [w.lower() for w in words if w.lower() not in stopwords]
    if not words:
        return []
    freq = Counter(words)
    return [w for w, _ in freq.most_common(max_words)]


def suggest_citations(markdown_text: str) -> dict[str, list[dict]]:
    """Split markdown text into sentences and return BibTeX suggestions.

    Each sentence is queried against Crossref sequentially. For every result
    the BibTeX is fetched and parsed into a dict with ``text`` and ``part``
    (fields without ID/ENTRYTYPE). Sentences with no suggestions are skipped.

    The query to Crossref is built from high‑frequency words within each
    sentence rather than the full sentence text.
    """

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", markdown_text) if s.strip()]
    results: dict[str, list[dict]] = {}
    for sentence in sentences:
        keywords = extract_keywords(sentence)
        if not keywords:
            continue
        query = " ".join(keywords)
        try:
            query_res = cr.works(query=query, limit=3)
        except Exception:
            continue
        items = query_res.get("message", {}).get("items", [])
        candidates: list[dict] = []
        for item in items:
            doi = normalize_doi(item.get("DOI"))
            if not doi:
                continue
            url = f"https://api.crossref.org/works/{doi}/transform/application/x-bibtex"
            try:
                resp = requests.get(url, timeout=10)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            bibtex = resp.text.strip()
            try:
                bib_db = bibtexparser.loads(bibtex)
                entry = bib_db.entries[0] if bib_db.entries else {}
            except Exception:
                entry = {}
            entry.pop("ID", None)
            entry.pop("ENTRYTYPE", None)
            entry['doi'] = doi
            candidates.append({"text": bibtex, "part": entry, "doi": doi})
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
        url = escape(str(part['url']))
        return Markup(f'<a href="{url}">{url}</a>')
    citation = '. '.join(pieces)
    if doi:
        citation += f". <a href=\"https://doi.org/{doi}\">https://doi.org/{doi}</a>"
    elif part.get('url'):
        url = escape(str(part['url']))
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


# Markup rendering helpers
def render_markdown(text: str, base_url: str = '/', with_toc: bool = False) -> tuple[str, str]:
    """Return HTML and optional TOC from Markdown text with wiki links."""
    extensions: list[Extension | str] = [WikiLinkExtension(base_url=base_url)]
    if with_toc:
        md = markdown.Markdown(extensions=extensions + ['toc'])
        html = md.convert(text or '')
        if not getattr(md, 'toc_tokens', None):
            return html, ''
        return html, md.toc
    html = markdown.markdown(text or '', extensions=extensions)
    return html, ''


# Roles allowed to create or edit posts
POST_EDITOR_ROLES = {'editor', 'admin'}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user')
    bio = db.Column(db.Text)
    locale = db.Column(db.String(8))
    timezone = db.Column(db.String(50), default='UTC')

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def is_admin(self) -> bool:
        return self.role == 'admin'

    def can_edit_posts(self) -> bool:
        return self.role in POST_EDITOR_ROLES


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    path = db.Column(db.String(200), nullable=False)
    language = db.Column(db.String(8), nullable=False, default='en')
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    author = db.relationship('User', backref='posts')
    tags = db.relationship('Tag', secondary='post_tag', backref='posts')
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    __table_args__ = (db.UniqueConstraint('path', 'language', name='uix_path_language'),)

    @property
    def display_title(self) -> str:
        """Return title or a placeholder if the post was deleted."""
        return self.title or _('[deleted]')


@event.listens_for(Post.__table__, 'after_create')
def create_post_fts(target, connection, **kw):
    """Create FTS5 table and triggers for Post.body."""
    connection.execute(
        text(
            'CREATE VIRTUAL TABLE IF NOT EXISTS post_fts '
            'USING fts5(body, content="post", content_rowid="id")'
        )
    )
    connection.execute(
        text(
            'CREATE TRIGGER post_fts_ai AFTER INSERT ON post BEGIN '
            'INSERT INTO post_fts(rowid, body) VALUES (new.id, new.body); '
            'END;'
        )
    )
    connection.execute(
        text(
            'CREATE TRIGGER post_fts_ad AFTER DELETE ON post BEGIN '
            "INSERT INTO post_fts(post_fts, rowid, body) VALUES('delete', old.id, old.body); "
            'END;'
        )
    )
    connection.execute(
        text(
            'CREATE TRIGGER post_fts_au AFTER UPDATE ON post BEGIN '
            "INSERT INTO post_fts(post_fts, rowid, body) VALUES('delete', old.id, old.body); "
            'INSERT INTO post_fts(rowid, body) VALUES (new.id, new.body); '
            'END;'
        )
    )


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)


class PostTag(db.Model):
    __tablename__ = 'post_tag'
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tag.id'), primary_key=True)


class PostLink(db.Model):
    __tablename__ = 'post_link'
    source_id = db.Column(db.Integer, db.ForeignKey('post.id'), primary_key=True)
    target_id = db.Column(db.Integer, db.ForeignKey('post.id'), primary_key=True)

    source = db.relationship(
        'Post', foreign_keys=[source_id], backref='outgoing_links'
    )
    target = db.relationship(
        'Post', foreign_keys=[target_id], backref='incoming_links'
    )


class PostWatch(db.Model):
    __tablename__ = 'post_watch'
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)

    post = db.relationship(
        'Post', backref=db.backref('watchers', cascade='all, delete-orphan')
    )
    user = db.relationship('User', backref='watched_posts')


class PostMetadata(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    key = db.Column(db.String(50), nullable=False)
    value = db.Column(db.JSON, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('post_id', 'key', name='uix_post_metadata_key'),
    )

    post = db.relationship(
        'Post', backref=db.backref('metadata', cascade='all, delete-orphan')
    )


class UserPostMetadata(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    key = db.Column(db.String(50), nullable=False)
    value = db.Column(db.JSON, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('post_id', 'user_id', 'key', name='uix_post_user_metadata_key'),
    )

    post = db.relationship('Post', backref='user_metadata')
    user = db.relationship('User')


def get_view_count(post: Post) -> int:
    """Return total view count for a post."""
    meta = next((m for m in post.metadata if m.key == 'views'), None)
    return int(meta.value) if meta else 0


def increment_view_count(post: Post) -> int:
    """Increment and return the view count for a post."""
    meta = PostMetadata.query.filter_by(post_id=post.id, key='views').first()
    if meta:
        meta.value = int(meta.value) + 1
    else:
        meta = PostMetadata(post=post, key='views', value=1)
        db.session.add(meta)
    db.session.commit()
    return int(meta.value)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(200), nullable=False)
    link = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref='notifications')


class RequestedPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    admin_comment = db.Column(db.String(200), default='')

    requester = db.relationship('User', backref='requested_posts')


class Redirect(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    old_path = db.Column(db.String(200), nullable=False)
    new_path = db.Column(db.String(200), nullable=False)
    language = db.Column(db.String(8), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('old_path', 'language', name='uix_redirect_oldpath_language'),
    )


class Setting(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, nullable=True)

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
    and will return ``(tag, tag)`` tuples.
    """

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
def format_datetime(value: datetime, fmt: str = '%Y-%m-%d %H:%M') -> str:
    tz_name = get_user_timezone()
    try:
        tzinfo = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tzinfo = timezone.utc
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tzinfo).strftime(fmt)


@app.context_processor
def inject_settings():
    return {'get_setting': get_setting}

@event.listens_for(Post, 'after_insert')
def emit_new_post(mapper, connection, target):
    socketio.emit(
        'new_post',
        {
            'id': target.id,
            'title': target.title,
            'language': target.language,
            'path': target.path,
        },
    )


@event.listens_for(Notification, 'after_insert')
def emit_new_notification(mapper, connection, target):
    socketio.emit(
        'new_notification', {'user_id': target.user_id, 'message': target.message}
    )


class PostCitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    citation_part = db.Column(db.JSON, nullable=False)
    citation_text = db.Column(db.Text, nullable=False)
    context = db.Column(db.Text)
    doi = db.Column(db.String, nullable=True)
    bibtex_raw = db.Column(db.Text, nullable=False)
    bibtex_fields = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship(
        'Post', backref=db.backref('citations', cascade='all, delete-orphan')
    )
    user = db.relationship('User')


class UserPostCitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    citation_part = db.Column(db.JSON, nullable=False)
    citation_text = db.Column(db.Text, nullable=False)
    context = db.Column(db.Text)
    doi = db.Column(db.String, nullable=True)
    bibtex_raw = db.Column(db.Text, nullable=False)
    bibtex_fields = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship('Post', backref='user_citations')
    user = db.relationship('User')


db.Index('ix_post_metadata_key_post', PostMetadata.key, PostMetadata.post_id)
db.Index('ix_user_post_metadata_key_post_user',
          UserPostMetadata.key,
          UserPostMetadata.post_id,
          UserPostMetadata.user_id)
db.Index('ix_post_citation_post_id', PostCitation.post_id)
db.Index('ix_post_citation_user_id', PostCitation.user_id)
db.Index('ix_user_post_citation_post_id', UserPostCitation.post_id)
db.Index('ix_user_post_citation_user_id', UserPostCitation.user_id)
db.Index('uq_post_citation_doi', PostCitation.post_id, PostCitation.doi,
         unique=True, sqlite_where=db.text('doi IS NOT NULL'))
db.Index('uq_post_citation_text', PostCitation.post_id, PostCitation.citation_text,
         unique=True, sqlite_where=db.text('doi IS NULL'))
db.Index('uq_user_post_citation_doi', UserPostCitation.post_id, UserPostCitation.doi,
         unique=True, sqlite_where=db.text('doi IS NOT NULL'))
db.Index('uq_user_post_citation_text', UserPostCitation.post_id,
         UserPostCitation.citation_text,
         unique=True, sqlite_where=db.text('doi IS NULL'))


class Revision(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    path = db.Column(db.String(200), nullable=False)
    language = db.Column(db.String(8), nullable=False, default='en')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    comment = db.Column(db.String(200), default='')
    byte_change = db.Column(db.Integer, default=0)

    user = db.relationship('User')
    post = db.relationship('Post', backref='revisions')


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))


@app.route('/posts')
def all_posts():
    tag_name = request.args.get('tag', '').strip()
    tag = None
    if tag_name:
        tag = Tag.query.filter_by(name=tag_name).first_or_404()
        posts = (
            Post.query.join(Post.tags)
            .filter(Tag.id == tag.id, Post.title != '', Post.body != '')
            .order_by(Post.id.desc())
            .all()
        )
    else:
        posts = (
            Post.query.filter(Post.title != '', Post.body != '')
            .order_by(Post.id.desc())
            .all()
        )
    categories = get_category_tags()
    return render_template('index.html', posts=posts, tag=tag, categories=categories)


@app.route('/')
def index():
    home_path = get_setting('home_page_path', '').strip()
    if home_path:
        language = select_locale() or app.config['BABEL_DEFAULT_LOCALE']
        post = Post.query.filter_by(language=language, path=home_path).first()
        if post:
            return redirect(
                url_for('document_docs', language=language, doc_path=home_path)
            )
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
        for name in tag_names:
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


@app.route('/api/posts', methods=['POST'])
@login_required
def api_create_post():
    if not current_user.can_edit_posts():
        return jsonify({'error': 'forbidden'}), 403
    if not request.is_json:
        return jsonify({'error': 'invalid JSON'}), 400
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    path = (data.get('path') or '').strip()
    language = (data.get('language') or '').strip()
    address = (data.get('address') or '').strip()
    lat_val = data.get('lat')
    lon_val = data.get('lon')
    lat = lon = None
    if address and lat_val is None and lon_val is None:
        coords = geocode_address(address)
        if not coords:
            return jsonify({'error': 'invalid address'}), 400
        lat_val, lon_val = coords
    if lat_val is not None and lon_val is not None:
        try:
            lat = float(lat_val)
            lon = float(lon_val)
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid coordinates'}), 400
    elif lat_val is not None or lon_val is not None:
        return jsonify({'error': 'lat and lon required'}), 400
    if not title or not body:
        return jsonify({'error': 'title and body required'}), 400
    if language not in app.config['LANGUAGES']:
        try:
            language = detect(body)
        except LangDetectException:
            language = app.config['BABEL_DEFAULT_LOCALE']
        if language not in app.config['LANGUAGES']:
            language = app.config['BABEL_DEFAULT_LOCALE']
    if not path or Post.query.filter_by(path=path, language=language).first():
        path = generate_unique_path(title, language)
    tags_input = data.get('tags', [])
    if isinstance(tags_input, str):
        tag_names = [t.strip() for t in tags_input.split(',') if t.strip()]
    else:
        tag_names = [
            t.strip() for t in tags_input if isinstance(t, str) and t.strip()
        ]
    tags = []
    for name in tag_names:
        tag = Tag.query.filter_by(name=name).first()
        if not tag:
            tag = Tag(name=name)
            db.session.add(tag)
        tags.append(tag)
    post = Post(
        title=title,
        body=body,
        path=path,
        language=language,
        author=current_user,
        tags=tags,
    )
    db.session.add(post)
    if lat is not None and lon is not None:
        post.latitude = lat
        post.longitude = lon
        db.session.add(PostMetadata(post=post, key='lat', value=str(lat)))
        db.session.add(PostMetadata(post=post, key='lon', value=str(lon)))
    db.session.flush()
    update_post_links(post)
    comment = (data.get('comment') or '').strip()
    rev = Revision(
        post=post,
        user=current_user,
        title=title,
        body=body,
        path=path,
        language=language,
        comment=comment,
        byte_change=len(body),
    )
    db.session.add(rev)
    db.session.commit()
    return (
        jsonify(
            {
                'id': post.id,
                'path': post.path,
                'language': post.language,
                'title': post.title,
            }
        ),
        201,
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
    location_list = []
    for loc in locations:
        name = reverse_geocode_coords(loc['lat'], loc['lon'])
        location_list.append({'lat': loc['lat'], 'lon': loc['lon'], 'name': name})
    geodata = extract_geodata(post_meta)
    meta_no_coords = post_meta.copy()
    if locations:
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
    return render_template(
        'post_detail.html',
        post=post,
        html_body=html_body,
        toc=toc,
        metadata=meta_no_coords,
        locations=location_list,
        geodata=geodata,
        user_metadata=user_meta,
        citations=citations,
        user_citations=user_citations,
        views=views,
        created_at=created_at,
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
    location_list = []
    for loc in locations:
        name = reverse_geocode_coords(loc['lat'], loc['lon'])
        location_list.append({'lat': loc['lat'], 'lon': loc['lon'], 'name': name})
    geodata = extract_geodata(post_meta)
    meta_no_coords = post_meta.copy()
    if locations:
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
        user_metadata=user_meta,
        citations=citations,
        user_citations=user_citations,
        views=views,
        created_at=created_at,
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
    escaped = escape(text)
    html, _ = render_markdown(str(escaped), base)
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


@app.route('/api/posts/<int:post_id>/citation', methods=['POST'])
@login_required
def api_add_url_citation(post_id: int):
    post = Post.query.get_or_404(post_id)
    if not request.is_json:
        return jsonify({'error': 'invalid JSON'}), 400
    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    context = (data.get('context') or '').strip()
    if not url or not is_url(url):
        return jsonify({'error': 'valid URL required'}), 400
    existing = PostCitation.query.filter_by(post_id=post.id, citation_text=url).first()
    if not existing:
        existing = UserPostCitation.query.filter_by(post_id=post.id, citation_text=url).first()
    if existing:
        return jsonify({'error': 'Citation with this URL already exists.'}), 400
    entry = {'url': url}
    if current_user.id == post.author_id or current_user.is_admin():
        citation = PostCitation(
            post=post,
            user=current_user,
            citation_part=entry,
            citation_text=url,
            context=context,
            doi=None,
            bibtex_raw=url,
            bibtex_fields=entry,
        )
    else:
        citation = UserPostCitation(
            post=post,
            user=current_user,
            citation_part=entry,
            citation_text=url,
            context=context,
            doi=None,
            bibtex_raw=url,
            bibtex_fields=entry,
        )
    db.session.add(citation)
    watcher_ids = {w.user_id for w in PostWatch.query.filter_by(post_id=post.id).all()}
    watcher_ids.add(post.author_id)
    link = url_for('post_detail', post_id=post.id)
    for uid in watcher_ids:
        if uid != current_user.id:
            msg = _('Citation added to "%(title)s".', title=post.title)
            db.session.add(Notification(user_id=uid, message=msg, link=link))
    db.session.commit()
    return jsonify({'id': citation.id, 'url': url}), 201


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
        for name in tag_names:
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


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if not current_user.is_admin():
        abort(403)
    title = get_setting('site_title', '')
    home_page = get_setting('home_page_path', '')
    timezone_value = get_setting('timezone', 'UTC')
    rss_enabled_val = get_setting('rss_enabled', 'false')
    rss_limit = get_setting('rss_limit', '20')
    head_tags = get_setting('head_tags', '')
    category_tags = get_setting('post_categories', '')
    if request.method == 'POST':

        title = request.form.get('site_title', title).strip()
        home_page = request.form.get('home_page_path', home_page).strip()
        tz_input = request.form.get('timezone', timezone_value).strip() or 'UTC'
        tz_norm = normalize_timezone(tz_input)
        if tz_norm is None:
            flash(_('Invalid timezone'))
            return redirect(url_for('settings'))
        timezone_value = tz_norm
        rss_enabled_val = 'rss_enabled' in request.form
        rss_limit = request.form.get('rss_limit', rss_limit).strip() or '20'
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

        db.session.commit()
        flash(_('Settings updated.'))
        return redirect(url_for('settings'))
    return render_template(
        'settings.html',
        site_title=title,
        home_page_path=home_page,
        timezone=timezone_value,
        rss_enabled=rss_enabled_val.lower() in ['true', '1', 'yes', 'on'],
        rss_limit=rss_limit,
        head_tags=head_tags,
        post_categories=category_tags
    )


@app.route('/tags')
def tag_list():
    tags = Tag.query.order_by(Tag.name).all()
    tag_locations = []
    tag_info = []
    tag_posts_data = []
    for tag in tags:
        coords = None
        for p in tag.posts:
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
            tag_locations.append(
                {
                    'name': tag.name,
                    'lat': coords[0],
                    'lon': coords[1],
                    'url': url_for('tag_filter', name=tag.name),
                }
            )
        top_posts = sorted(
            [(p, get_view_count(p)) for p in tag.posts],
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        tag_info.append({'tag': tag, 'top_posts': top_posts})
        posts_data = []
        for p, _ in top_posts:
            snippet = (p.body[:100] + '...') if len(p.body) > 100 else p.body
            posts_data.append(
                {
                    'title': p.display_title,
                    'url': url_for('document', language=p.language, doc_path=p.path),
                    'snippet': snippet,
                    'views': get_view_count(p),
                    'author': p.author.username,
                }
            )
        tag_posts_data.append({'tag': tag.name, 'posts': posts_data})
    tag_locations_json = json.dumps(tag_locations)
    tag_posts_json = json.dumps(tag_posts_data)
    return render_template(
        'tag_list.html',
        tag_info=tag_info,
        tag_locations_json=tag_locations_json,
        tag_posts_json=tag_posts_json,
    )


@app.route('/tag/<string:name>')
def tag_filter(name: str):
    tag = Tag.query.filter_by(name=name).first_or_404()
    categories = get_category_tags()
    return render_template('index.html', posts=tag.posts, tag=tag, categories=categories)


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

    # Gather distinct metadata keys for the dropdown and include title/path
    meta_keys = [k for (k,) in db.session.query(PostMetadata.key).distinct().all()]
    meta_keys = ['title', 'path'] + sorted(meta_keys)
    all_tags = [t.name for t in Tag.query.order_by(Tag.name).all()]

    posts_query = None
    examples = None
    if q:
        ids = [
            row[0]
            for row in db.session.execute(
                text('SELECT rowid FROM post_fts WHERE post_fts MATCH :q'),
                {'q': q},
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

    posts = posts_query
    if posts is not None:
        for name in tag_names:
            posts = posts.filter(Post.tags.any(Tag.name == name))
        posts = posts.all()

    if posts is not None and lat is not None and lon is not None and radius is not None:
        posts = [
            p
            for p in posts
            if p.latitude is not None
            and p.longitude is not None
            and geopy_distance((lat, lon), (p.latitude, p.longitude)).km <= radius
        ]

    coords_json = (
        json.dumps([{'lat': p.latitude, 'lon': p.longitude} for p in posts])
        if posts
        else '[]'
    )

    return render_template(
        'search.html',
        posts=posts,
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

    rows = (
        db.session.query(
            all_citations.c.doi,
            all_citations.c.citation_text,
            func.count().label('count'),
            func.group_concat(all_citations.c.post_id, ',').label('post_ids'),
        )
        .group_by(all_citations.c.doi, all_citations.c.citation_text)
        .order_by(func.count().desc())
        .all()
    )

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

    return render_template('citation_stats.html', stats=stats)


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
    socketio.run(app, host=host, port=port, debug=True)
