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


def test_duplicate_tags_are_deduplicated(client):
    resp = client.post(
        '/api/posts',
        json={
            'title': 'T',
            'body': 'B',
            'path': 'p1',
            'tags': ['dupe', 'dupe', 'other'],
        },
    )
    assert resp.status_code == 201
    with app.app_context():
        post = Post.query.filter_by(path='p1', language='en').first()
        assert post is not None
        assert sorted(t.name for t in post.tags) == ['dupe', 'other']
        assert len(post.tags) == 2

