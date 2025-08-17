import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Revision


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def _create_post(title='Hello', body='World', path='hello'):
    with app.app_context():
        user = User.query.filter_by(username='author').first()
        if not user:
            user = User(username='author')
            user.set_password('pw')
            db.session.add(user)
            db.session.commit()
        post = Post(title=title, body=body, path=path, language='en', author=user)
        db.session.add(post)
        db.session.commit()
        rev = Revision(
            post_id=post.id,
            user_id=user.id,
            title=post.title,
            body=post.body,
            path=post.path,
            language=post.language,
        )
        db.session.add(rev)
        db.session.commit()
        return post.id


def test_sitemap(client):
    _create_post()
    resp = client.get('/sitemap.xml')
    assert resp.status_code == 200
    assert b'http://localhost/en/hello' in resp.data


def test_sitemap_skips_deleted_posts(client):
    _create_post(title='Hello', path='hello')
    deleted_id = _create_post(title='Bye', path='bye')
    with app.app_context():
        post = Post.query.get(deleted_id)
        post.title = ''
        post.body = ''
        db.session.commit()
    resp = client.get('/sitemap.xml')
    assert resp.status_code == 200
    assert b'http://localhost/en/hello' in resp.data
    assert b'http://localhost/en/bye' not in resp.data
