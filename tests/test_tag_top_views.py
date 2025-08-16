import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Tag


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        user = User(username='u')
        user.set_password('pw')
        tag = Tag(name='t')
        db.session.add_all([user, tag])
        posts = []
        for i in range(3):
            p = Post(title=f'P{i}', body='b', path=f'p{i}', language='en', author=user, tags=[tag])
            posts.append(p)
            db.session.add(p)
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_tags_show_top_posts_by_views(client):
    client.get('/docs/en/p0')
    client.get('/docs/en/p1')
    client.get('/docs/en/p1')
    client.get('/docs/en/p2')
    client.get('/docs/en/p2')
    client.get('/docs/en/p2')
    resp = client.get('/tags')
    data = resp.get_data(as_text=True)
    assert data.index('P2') < data.index('P1') < data.index('P0')
