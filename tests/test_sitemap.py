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


def _create_post():
    with app.app_context():
        user = User(username='author')
        user.set_password('pw')
        db.session.add(user)
        post = Post(title='Hello', body='World', path='hello', language='en', author=user)
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


def test_sitemap(client):
    _create_post()
    resp = client.get('/sitemap.xml')
    assert resp.status_code == 200
    assert b'http://localhost/docs/en/hello' in resp.data
