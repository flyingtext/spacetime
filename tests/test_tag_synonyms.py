import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Tag  # noqa: E402
from sqlalchemy import text


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.drop_all()
        db.session.execute(text('DROP TABLE IF EXISTS post_fts'))
        db.create_all()
        user = User(username='u')
        user.set_password('pw')
        t1 = Tag(name='automobile')
        db.session.add_all([user, t1])
        db.session.commit()
        p1 = Post(
            title='Vehicle',
            body='A car or automobile',
            path='p1',
            language='en',
            author_id=user.id,
        )
        p1.tags.append(t1)
        db.session.add(p1)
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()
        db.session.execute(text('DROP TABLE IF EXISTS post_fts'))


def test_synonym_tag_filter(client):
    resp = client.get('/tag/car')
    text = resp.get_data(as_text=True)
    assert 'Vehicle' in text


def test_synonym_search(client):
    resp = client.get('/search', query_string={'tags': 'car'})
    text = resp.get_data(as_text=True)
    assert 'Vehicle' in text
