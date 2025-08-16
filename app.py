import difflib
import json
import markdown
from datetime import datetime
from xml.etree.ElementTree import Element

from flask import (Flask, render_template, redirect, url_for, request, flash,
                   abort)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, login_user, login_required,
                         logout_user, current_user, UserMixin)
from werkzeug.security import generate_password_hash, check_password_hash
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markupsafe import Markup, escape
import requests
from habanero import Crossref
import bibtexparser
from sqlalchemy import func

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///wiki.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

cr = Crossref()


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


def map_link(lat: float, lon: float) -> str:
    """Return an OpenStreetMap link for given coordinates."""
    return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=12/{lat}/{lon}"


def format_metadata_value(value):
    if isinstance(value, dict):
        lat = value.get('lat') or value.get('latitude')
        lon = value.get('lon') or value.get('lng') or value.get('longitude')
        if lat is not None and lon is not None:
            return Markup(f'<a href="{map_link(lat, lon)}">{lat}, {lon}</a>')
        return Markup(escape(json.dumps(value)))
    if isinstance(value, list):
        return Markup(escape(json.dumps(value)))
    return Markup(escape(str(value)))


app.jinja_env.filters['format_metadata'] = format_metadata_value


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


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user')

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def is_admin(self) -> bool:
        return self.role == 'admin'


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    path = db.Column(db.String(200), nullable=False)
    language = db.Column(db.String(8), nullable=False, default='en')
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    author = db.relationship('User', backref='posts')
    tags = db.relationship('Tag', secondary='post_tag', backref='posts')
    __table_args__ = (db.UniqueConstraint('path', 'language', name='uix_path_language'),)


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)


class PostTag(db.Model):
    __tablename__ = 'post_tag'
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tag.id'), primary_key=True)


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


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful. Please log in.')
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
        flash('Invalid credentials')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/post/new', methods=['GET', 'POST'])
@login_required
def create_post():
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

        if metadata_json:
            try:
                meta_dict = json.loads(metadata_json)
            except ValueError:
                flash('Invalid metadata JSON')
                return redirect(url_for('create_post'))
            for key, value in meta_dict.items():
                db.session.add(PostMetadata(post=post, key=key, value=value))

        if user_metadata_json:
            try:
                user_meta_dict = json.loads(user_metadata_json)
            except ValueError:
                flash('Invalid user metadata JSON')
                return redirect(url_for('create_post'))
            for key, value in user_meta_dict.items():
                db.session.add(
                    UserPostMetadata(post=post, user=current_user, key=key, value=value)
                )

        rev = Revision(post=post, user=current_user, title=title, body=body,
                       path=path, language=language)
        db.session.add(rev)
        db.session.commit()
        return redirect(url_for('document', language=post.language, doc_path=post.path))
    return render_template('post_form.html', action='Create', metadata='', user_metadata='')


@app.route('/post/<int:post_id>')
def post_detail(post_id: int):
    post = Post.query.get_or_404(post_id)
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
    base = url_for('document', language=post.language, doc_path='')
    html_body = markdown.markdown(
        post.body, extensions=[WikiLinkExtension(base_url=base)]
    )
    return render_template(
        'post_detail.html',
        post=post,
        html_body=html_body,
        metadata=post_meta,
        user_metadata=user_meta,
        citations=citations,
        user_citations=user_citations,
    )


@app.route('/docs/<string:language>/<path:doc_path>')
def document(language: str, doc_path: str):
    post = Post.query.filter_by(language=language, path=doc_path).first_or_404()
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


@app.route('/citation/fetch', methods=['POST'])
def fetch_citation():
    data = request.get_json() or {}
    title = data.get('title', '').strip()
    if not title:
        return {'error': 'Title is required'}, 400
    bibtex = fetch_bibtex_by_title(title)
    if not bibtex:
        return {'error': 'Citation not found'}, 404
    try:
        bib_db = bibtexparser.loads(bibtex)
        entry = bib_db.entries[0] if bib_db.entries else {}
    except Exception:
        return {'error': 'Failed to parse BibTeX'}, 500
    entry.pop('ID', None)
    entry.pop('ENTRYTYPE', None)
    return {'part': entry, 'text': bibtex}


@app.route('/post/<int:post_id>/citation/new', methods=['POST'])
@login_required
def new_citation(post_id: int):
    post = Post.query.get_or_404(post_id)
    text = request.form.get('citation_text', '').strip()
    if not text:
        flash('Citation text is required.')
        return redirect(url_for('post_detail', post_id=post.id))
    try:
        bib_db = bibtexparser.loads(text)
        entry = bib_db.entries[0] if bib_db.entries else {}
    except Exception:
        flash('Failed to parse BibTeX')
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
            flash('Citation with this DOI already exists.')
            return redirect(url_for('post_detail', post_id=post.id))
    else:
        existing = PostCitation.query.filter_by(post_id=post.id, citation_text=text).first()
        if not existing:
            existing = UserPostCitation.query.filter_by(post_id=post.id, citation_text=text).first()
        if existing:
            flash('Citation with this text already exists.')
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
        flash('Permission denied.')
        return redirect(url_for('post_detail', post_id=post.id))
    if request.method == 'POST':
        text = request.form.get('citation_text', '').strip()
        if not text:
            flash('Citation text is required.')
            return redirect(url_for('edit_citation', post_id=post.id, cid=cid))
        try:
            bib_db = bibtexparser.loads(text)
            entry = bib_db.entries[0] if bib_db.entries else {}
        except Exception:
            flash('Failed to parse BibTeX')
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
                flash('Citation with this DOI already exists.')
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
                flash('Citation with this text already exists.')
                return redirect(url_for('edit_citation', post_id=post.id, cid=cid))
        citation.citation_part = entry
        citation.citation_text = text
        citation.doi = doi
        citation.bibtex_raw = text
        citation.bibtex_fields = entry
        db.session.commit()
        return redirect(url_for('post_detail', post_id=post.id))
    part_json = json.dumps(citation.citation_part)
    return render_template('citation_form.html', action='Edit', citation=citation,
                           citation_part=part_json, post=post)


@app.route('/post/<int:post_id>/citation/<int:cid>/delete', methods=['POST'])
@login_required
def delete_citation(post_id: int, cid: int):
    post = Post.query.get_or_404(post_id)
    citation = PostCitation.query.filter_by(id=cid, post_id=post.id).first()
    if citation is None:
        citation = UserPostCitation.query.filter_by(id=cid, post_id=post.id).first_or_404()
    if current_user.id != citation.user_id and not current_user.is_admin():
        flash('Permission denied.')
        return redirect(url_for('post_detail', post_id=post.id))
    db.session.delete(citation)
    db.session.commit()
    return redirect(url_for('post_detail', post_id=post.id))


@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id: int):
    post = Post.query.get_or_404(post_id)
    if current_user.id != post.author_id and not current_user.is_admin():
        flash('Permission denied.')
        return redirect(url_for('document', language=post.language, doc_path=post.path))
    if request.method == 'POST':
        rev = Revision(post=post, user=current_user, title=post.title,
                       body=post.body, path=post.path, language=post.language)
        db.session.add(rev)
        post.title = request.form['title']
        post.body = request.form['body']
        post.path = request.form['path']
        post.language = request.form['language']
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

        if metadata_json:
            try:
                meta_dict = json.loads(metadata_json)
            except ValueError:
                flash('Invalid metadata JSON')
                return redirect(url_for('edit_post', post_id=post.id))
            PostMetadata.query.filter_by(post_id=post.id).delete()
            for key, value in meta_dict.items():
                db.session.add(PostMetadata(post=post, key=key, value=value))
        else:
            PostMetadata.query.filter_by(post_id=post.id).delete()

        if user_metadata_json:
            try:
                user_meta_dict = json.loads(user_metadata_json)
            except ValueError:
                flash('Invalid user metadata JSON')
                return redirect(url_for('edit_post', post_id=post.id))
            UserPostMetadata.query.filter_by(post_id=post.id, user_id=current_user.id).delete()
            for key, value in user_meta_dict.items():
                db.session.add(
                    UserPostMetadata(post=post, user=current_user, key=key, value=value)
                )
        else:
            UserPostMetadata.query.filter_by(post_id=post.id, user_id=current_user.id).delete()

        db.session.commit()
        return redirect(url_for('document', language=post.language, doc_path=post.path))
    tags_str = ', '.join([t.name for t in post.tags])
    post_meta_dict = {m.key: m.value for m in post.metadata}
    post_meta = json.dumps(post_meta_dict) if post_meta_dict else ''
    user_entries = UserPostMetadata.query.filter_by(post_id=post.id, user_id=current_user.id).all()
    user_meta_dict = {m.key: m.value for m in user_entries}
    user_meta = json.dumps(user_meta_dict) if user_meta_dict else ''
    return render_template('post_form.html', action='Edit', post=post, tags=tags_str,
                           metadata=post_meta, user_metadata=user_meta)


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
    key = request.args.get('key', '').strip()
    value_raw = request.args.get('value', '').strip()
    posts = None
    if key and value_raw:
        try:
            value = json.loads(value_raw)
        except ValueError:
            value = value_raw
        posts = (
            Post.query.join(PostMetadata)
            .filter(
                PostMetadata.key == key,
                PostMetadata.value == value,
            )
            .all()
        )
    return render_template('search.html', posts=posts, key=key, value=value_raw)


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
        PostMetadata.__table__.create(bind=db.engine, checkfirst=True)
        UserPostMetadata.__table__.create(bind=db.engine, checkfirst=True)
        PostCitation.__table__.create(bind=db.engine, checkfirst=True)
        UserPostCitation.__table__.create(bind=db.engine, checkfirst=True)
        db.create_all()
    app.run(debug=True)
