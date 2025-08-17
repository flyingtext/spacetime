import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Setting


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


def test_all_posts_route_returns_list(client):
    with app.app_context():
        user = User(username='author')
        user.set_password('pw')
        db.session.add(user)
        post = Post(title='Home', body='Content', path='home', language='en', author=user)
        other = Post(title='Other', body='Content', path='other', language='en', author=user)
        db.session.add_all([post, other])
        db.session.add(Setting(key='home_page_path', value='home'))
        db.session.commit()

    resp = client.get('/posts')
    assert resp.status_code == 200
    assert b'Home' in resp.data
    assert b'Other' in resp.data
    assert b'href="/posts"' in resp.data


def test_posts_pagination(client):
    with app.app_context():
        user = User(username='author')
        user.set_password('pw')
        db.session.add(user)
        for i in range(25):
            db.session.add(
                Post(
                    title=f'Post {i}',
                    body='Content',
                    path=f'post-{i}',
                    language='en',
                    author=user,
                )
            )
        db.session.commit()

    resp = client.get('/posts')
    assert resp.status_code == 200
    assert b'Post 24' in resp.data
    assert b'Post 4' not in resp.data

    resp = client.get('/posts', query_string={'page': 2})
    assert b'Post 4' in resp.data
    assert b'Post 24' not in resp.data
