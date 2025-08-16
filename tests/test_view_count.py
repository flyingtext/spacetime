import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, PostMetadata


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        user = User(username='u', role='editor')
        user.set_password('pw')
        post = Post(title='Post', body='body', path='p', language='en', author=user)
        db.session.add_all([user, post])
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_view_count_increment(client):
    resp = client.get('/docs/en/p')
    assert resp.status_code == 200
    with app.app_context():
        meta = PostMetadata.query.filter_by(key='views').first()
        assert meta is not None
        assert meta.value == 1
    client.get('/docs/en/p')
    with app.app_context():
        meta = PostMetadata.query.filter_by(key='views').first()
        assert meta.value == 2


def test_view_count_not_editable_via_metadata(client):
    # Initial view increments the counter
    client.get('/docs/en/p')
    with app.app_context():
        post = Post.query.first()
        meta = PostMetadata.query.filter_by(post_id=post.id, key='views').first()
        assert meta.value == 1

    # Log in to edit the post and attempt to change views through metadata
    client.post('/login', data={'username': 'u', 'password': 'pw'})
    client.post(
        f'/post/{post.id}/edit',
        data={
            'title': 'Post',
            'body': 'body',
            'path': 'p',
            'language': 'en',
            'tags': '',
            'metadata': '{"views": 100}',
            'user_metadata': '',
        },
    )

    with app.app_context():
        meta = PostMetadata.query.filter_by(post_id=post.id, key='views').first()
        # View count should remain unchanged
        assert meta.value == 1
