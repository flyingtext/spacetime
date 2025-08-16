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
        user = User(username='u')
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
