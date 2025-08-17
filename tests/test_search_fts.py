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
        t_apple = Tag(name='apple')
        t_other = Tag(name='other')
        db.session.add_all([user, t_apple, t_other])
        db.session.commit()
        p_tag = Post(title='TagMatch', body='something else', path='p1', language='en', author_id=user.id)
        p_tag.tags.append(t_apple)
        p_title = Post(title='AppleTitle', body='something else', path='p2', language='en', author_id=user.id)
        p_title.tags.append(t_other)
        p_body = Post(title='BodyMatch', body='I like apple', path='p3', language='en', author_id=user.id)
        p_body.tags.append(t_other)
        db.session.add_all([p_tag, p_title, p_body])
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_search_prioritizes_tag_title_body(client):
    resp = client.get('/search', query_string={'q': 'apple'})
    text = resp.get_data(as_text=True)
    assert text.index('TagMatch') < text.index('AppleTitle') < text.index('BodyMatch')


def test_tag_filter(client):
    resp = client.get('/search', query_string={'q': 'apple', 'tags': 'other'})
    text = resp.get_data(as_text=True)
    assert 'TagMatch' not in text
    assert 'AppleTitle' in text
    assert 'BodyMatch' in text
