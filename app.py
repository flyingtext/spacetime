import difflib
import markdown
from flask import (Flask, render_template, redirect, url_for, request, flash,
                   abort)
from flask_login import (LoginManager, login_user, login_required,
                         logout_user, current_user)

from models import db, User, Post, Tag, Revision
from wikilinks import WikiLinkExtension

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///wiki.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


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
        rev = Revision(post=post, user=current_user, title=title, body=body,
                       path=path, language=language)
        db.session.add(rev)
        db.session.commit()
        return redirect(url_for('document', language=post.language, doc_path=post.path))
    return render_template('post_form.html', action='Create')


@app.route('/post/<int:post_id>')
def post_detail(post_id: int):
    post = Post.query.get_or_404(post_id)
    base = url_for('document', language=post.language, doc_path='')
    html_body = markdown.markdown(post.body,
                                  extensions=[WikiLinkExtension(base_url=base)])
    return render_template('post_detail.html', post=post, html_body=html_body)


@app.route('/docs/<string:language>/<path:doc_path>')
def document(language: str, doc_path: str):
    post = Post.query.filter_by(language=language, path=doc_path).first_or_404()
    base = url_for('document', language=language, doc_path='')
    html_body = markdown.markdown(post.body,
                                  extensions=[WikiLinkExtension(base_url=base)])
    translations = Post.query.filter(Post.path == doc_path, Post.language != language).all()
    return render_template('post_detail.html', post=post, html_body=html_body,
                           translations=translations)


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
        db.session.commit()
        return redirect(url_for('document', language=post.language, doc_path=post.path))
    tags_str = ', '.join([t.name for t in post.tags])
    return render_template('post_form.html', action='Edit', post=post, tags=tags_str)


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


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
