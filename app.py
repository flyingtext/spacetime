import difflib
import json
import os
import re
import markdown
from datetime import datetime
from xml.etree.ElementTree import Element

from flask import (Flask, render_template, redirect, url_for, request, flash,
                   abort, jsonify)
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
from sqlalchemy import func, event, or_, text
from flask_babel import Babel, _
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
from geopy.distance import distance as geopy_distance

load_dotenv()

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
    return request.accept_languages.best_match(app.config['LANGUAGES'])


babel.locale_selector_func = select_locale


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
    doi = items[0].get('DOI')
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
    """Split markdown text into sentences and return BibTeX suggestions.

    Each sentence is queried against Crossref sequentially. For every result
    the BibTeX is fetched and parsed into a dict with ``text`` and ``part``
    (fields without ID/ENTRYTYPE). Sentences with no suggestions are skipped.
    """

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", markdown_text) if s.strip()]
    results: dict[str, list[dict]] = {}
    for sentence in sentences:
        try:
            query_res = cr.works(query=sentence, limit=3)
        except Exception:
            continue
        items = query_res.get("message", {}).get("items", [])
        candidates: list[dict] = []
        for item in items:
            doi = item.get("DOI")
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
                return Markup(
                    f'<a href="{map_link(lat_f, lon_f)}">{lat_f}, {lon_f}</a>'
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


def extract_location(meta: dict) -> tuple[dict | None, str | None]:
    """Extract location dict from metadata if within valid range."""
    location = None
    warning = None
    for value in meta.values():
        if isinstance(value, dict):
            lat = value.get('lat') or value.get('latitude')
            lon = value.get('lon') or value.get('lng') or value.get('longitude')
            if lat is not None and lon is not None:
                try:
                    lat_f = float(lat)
                    lon_f = float(lon)
                except (TypeError, ValueError):
                    continue
                if -90 <= lat_f <= 90 and -180 <= lon_f <= 180:
                    location = {'lat': lat_f, 'lon': lon_f}
                    break
                warning = COORD_OUT_OF_RANGE_MSG
    if location is None:
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
                    location = {'lat': lat_f, 'lon': lon_f}
                else:
                    warning = COORD_OUT_OF_RANGE_MSG
    return location, warning


def extract_geodata(meta: dict) -> list[dict]:
    """Collect GeoJSON features from all metadata values."""
    geoms: list[dict] = []
    for value in meta.values():
        geoms.extend(parse_geodata(value))
    return geoms


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


# Roles allowed to create or edit posts
POST_EDITOR_ROLES = {'editor', 'admin'}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user')
    avatar_url = db.Column(db.String(200))
    bio = db.Column(db.Text)

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


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref='notifications')


class RequestedPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    requester = db.relationship('User', backref='requested_posts')


class Redirect(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    old_path = db.Column(db.String(200), nullable=False)
    new_path = db.Column(db.String(200), nullable=False)
    language = db.Column(db.String(8), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('old_path', 'language', name='uix_redirect_oldpath_language'),
    )


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

    user = db.relationship('User')
    post = db.relationship('Post', backref='revisions')


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))


@app.route('/')
def index():
    posts = Post.query.order_by(Post.id.desc()).all()
    return render_template('index.html', posts=posts)


@app.route('/recent')
def recent_changes():
    revisions = (
        Revision.query.order_by(Revision.created_at.desc()).limit(20).all()
    )
    return render_template('recent.html', revisions=revisions)


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
    post_count = Post.query.filter_by(author_id=user.id).count()
    citation_count = (
        PostCitation.query.filter_by(user_id=user.id).count()
        + UserPostCitation.query.filter_by(user_id=user.id).count()
    )
    if request.method == 'POST':
        if not current_user.is_authenticated or current_user.id != user.id:
            abort(403)
        user.avatar_url = request.form.get('avatar_url', '').strip() or None
        user.bio = request.form.get('bio', '').strip() or None
        db.session.commit()
        flash(_('Profile updated'))
        return redirect(url_for('profile', username=user.username))
    return render_template(
        'profile.html',
        user=user,
        posts=posts,
        post_count=post_count,
        citation_count=citation_count,
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


@app.route('/post/new', methods=['GET', 'POST'])
@login_required
def create_post():
    if not current_user.can_edit_posts():
        abort(403)
    if request.method == 'POST':
        title = request.form['title']
        body = request.form['body']
        path = request.form['path']
        language = request.form['language']
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

        lat = request.form.get('lat')
        lon = request.form.get('lon')
        if lat and lon:
            meta_dict['lat'] = lat
            meta_dict['lon'] = lon

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

        rev = Revision(post=post, user=current_user, title=title, body=body,
                       path=path, language=language)
        db.session.add(rev)

        req_id = request.form.get('request_id')
        if req_id:
            req = RequestedPost.query.get(int(req_id))
            if req:
                db.session.delete(req)

        db.session.commit()
        return redirect(url_for('document', language=post.language, doc_path=post.path))

    req_id = request.args.get('request_id')
    prefill_title = prefill_body = None
    if req_id:
        req = RequestedPost.query.get_or_404(req_id)
        prefill_title = req.title
        prefill_body = req.description
    return render_template('post_form.html', action=_('Create'), metadata='',
                           user_metadata='', prefill_title=prefill_title,
                           prefill_body=prefill_body, request_id=req_id,
                           lat=None, lon=None)


@app.route('/post/<int:post_id>')
def post_detail(post_id: int):
    post = Post.query.get_or_404(post_id)
    post_meta = {m.key: m.value for m in post.metadata}
    location, warning = extract_location(post_meta)
    geodata = extract_geodata(post_meta)
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
    md = markdown.Markdown(
        extensions=[WikiLinkExtension(base_url=base), 'toc']
    )
    html_body = md.convert(post.body)
    toc = md.toc
    return render_template(
        'post_detail.html',
        post=post,
        html_body=html_body,
        toc=toc,
        metadata=post_meta,
        location=location,
        geodata=geodata,
        user_metadata=user_meta,
        citations=citations,
        user_citations=user_citations,
    )


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
    db.session.delete(post)
    db.session.commit()
    flash(_('Post deleted.'))
    return redirect(url_for('index'))


@app.route('/docs/<string:language>/<path:doc_path>')
def document(language: str, doc_path: str):
    post = Post.query.filter_by(language=language, path=doc_path).first()
    if not post:
        redirect_entry = Redirect.query.filter_by(
            language=language, old_path=doc_path
        ).first()
        if redirect_entry:
            return redirect(
                url_for('document', language=language, doc_path=redirect_entry.new_path)
            )
        abort(404)
    post_meta = {m.key: m.value for m in post.metadata}
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
    html_body = markdown.markdown(
        post.body, extensions=[WikiLinkExtension(base_url=base)]
    )
    translations = Post.query.filter(
        Post.path == doc_path, Post.language != language
    ).all()
    return render_template(
        'post_detail.html',
        post=post,
        html_body=html_body,
        translations=translations,
        metadata=post_meta,
        user_metadata=user_meta,
        citations=citations,
    user_citations=user_citations,
    )


@app.route('/markdown/preview', methods=['POST'])
def markdown_preview():
    data = request.get_json() or {}
    text = data.get('text', '')
    html = Markup(markdown.markdown(escape(text)))
    return {'html': str(html)}


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
    return {'part': entry, 'text': bibtex}


@app.route('/post/<int:post_id>/citation/new', methods=['POST'])
@login_required
def new_citation(post_id: int):
    post = Post.query.get_or_404(post_id)
    text = request.form.get('citation_text', '').strip()
    if not text:
        flash(_('Citation text is required.'))
        return redirect(url_for('post_detail', post_id=post.id))
    try:
        bib_db = bibtexparser.loads(text)
        entry = bib_db.entries[0] if bib_db.entries else {}
    except Exception:
        flash(_('Failed to parse BibTeX'))
        return redirect(url_for('post_detail', post_id=post.id))
    entry.pop('ID', None)
    entry.pop('ENTRYTYPE', None)
    doi = entry.get('doi')
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
            doi=doi,
            bibtex_raw=text,
            bibtex_fields=entry,
        )
    db.session.add(citation)
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
        if not text:
            flash(_('Citation text is required.'))
            return redirect(url_for('edit_citation', post_id=post.id, cid=cid))
        try:
            bib_db = bibtexparser.loads(text)
            entry = bib_db.entries[0] if bib_db.entries else {}
        except Exception:
            flash(_('Failed to parse BibTeX'))
            return redirect(url_for('edit_citation', post_id=post.id, cid=cid))
        entry.pop('ID', None)
        entry.pop('ENTRYTYPE', None)
        doi = entry.get('doi')
        if doi:
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
        else:
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
        citation.doi = doi
        citation.bibtex_raw = text
        citation.bibtex_fields = entry
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
        rev = Revision(post=post, user=current_user, title=post.title,
                       body=post.body, path=post.path, language=post.language)
        db.session.add(rev)
        post.title = request.form['title']
        post.body = request.form['body']
        post.path = request.form['path']
        post.language = request.form['language']
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

        lat = request.form.get('lat')
        lon = request.form.get('lon')
        if lat and lon:
            meta_dict['lat'] = lat
            meta_dict['lon'] = lon

        PostMetadata.query.filter_by(post_id=post.id).delete()
        for key, value in meta_dict.items():
            db.session.add(PostMetadata(post=post, key=key, value=value))

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
        watchers = PostWatch.query.filter_by(post_id=post.id).all()
        for w in watchers:
            if w.user_id != current_user.id:
                msg = _('Post "%(title)s" was updated.', title=post.title)
                db.session.add(Notification(user_id=w.user_id, message=msg))
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
                           metadata=post_meta, user_metadata=user_meta, lat=lat, lon=lon)


@app.route('/post/<int:post_id>/history')
def history(post_id: int):
    post = Post.query.get_or_404(post_id)
    revisions = Revision.query.filter_by(post_id=post_id).order_by(Revision.created_at.desc()).all()
    return render_template('history.html', post=post, revisions=revisions)


@app.route('/post/<int:post_id>/diff/<int:rev_id>')
def revision_diff(post_id: int, rev_id: int):
    post = Post.query.get_or_404(post_id)
    revision = Revision.query.get_or_404(rev_id)
    if revision.post_id != post.id:
        abort(404)
    diff = difflib.unified_diff(
        revision.body.splitlines(),
        post.body.splitlines(),
        fromfile=f'rev {revision.id}',
        tofile='current',
        lineterm='',
    )
    return render_template('diff.html', post=post, revision=revision, diff='\n'.join(diff))


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

    watchers = PostWatch.query.filter_by(post_id=post.id).all()
    for w in watchers:
        if w.user_id != current_user.id:
            msg = _('Post "%(title)s" was updated.', title=post.title)
            db.session.add(Notification(user_id=w.user_id, message=msg))

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


@app.route('/tags')
def tag_list():
    tags = Tag.query.order_by(Tag.name).all()
    return render_template('tag_list.html', tags=tags)


@app.route('/tag/<string:name>')
def tag_filter(name: str):
    tag = Tag.query.filter_by(name=name).first_or_404()
    return render_template('index.html', posts=tag.posts, tag=tag)


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
