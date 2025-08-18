import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        user = User(username='editor', role='editor')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
    with app.test_client() as client:
        client.post('/login', data={'username': 'editor', 'password': 'pw'})
        yield client
    with app.app_context():
        db.drop_all()


def test_creates_large_post(client):
    large_body = 'A' * 600000
    resp = client.post(
        '/api/posts',
        json={
            'title': 'Big',
            'body': large_body,
            'path': 'big-post',
            'language': 'en',
        },
    )
    assert resp.status_code == 201
    with app.app_context():
        post = Post.query.filter_by(path='big-post', language='en').first()
        assert post is not None
        assert post.body == large_body
