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
        t1 = Tag(name='news')
        t2 = Tag(name='science')
        db.session.add_all([user, t1, t2])
        db.session.commit()
        p1 = Post(title='Apple', body='apple banana', path='p1', language='en', author_id=user.id)
        p1.tags.append(t1)
        p2 = Post(title='Banana', body='banana carrot', path='p2', language='en', author_id=user.id)
        p2.tags.append(t2)
        db.session.add_all([p1, p2])
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_fulltext_search(client):
    resp = client.get('/search', query_string={'q': 'apple'})
    text = resp.get_data(as_text=True)
    assert 'Apple' in text
    assert 'Banana' not in text


def test_tag_filter(client):
    resp = client.get('/search', query_string={'q': 'banana', 'tags': 'news'})
    text = resp.get_data(as_text=True)
    assert 'Apple' in text
    assert 'Banana' not in text
