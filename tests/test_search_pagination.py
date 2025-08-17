import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post
from sqlalchemy import text


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SEARCH_RESULTS_PER_PAGE'] = 2
    with app.app_context():
        db.drop_all()
        db.session.execute(text('DROP TABLE IF EXISTS post_fts'))
        db.create_all()
        user = User(username='u')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
        posts = [
            Post(title=f'Apple {i}', body='apple', path=f'p{i}', language='en', author_id=user.id)
            for i in range(3)
        ]
        db.session.add_all(posts)
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()
        db.session.execute(text('DROP TABLE IF EXISTS post_fts'))


def test_search_pagination(client):
    resp = client.get('/search', query_string={'q': 'apple'})
    text = resp.get_data(as_text=True)
    assert 'Apple 2' in text
    assert 'Apple 1' in text
    assert 'Apple 0' not in text

    resp = client.get('/search', query_string={'q': 'apple', 'page': 2})
    text = resp.get_data(as_text=True)
    assert 'Apple 0' in text
    assert 'Apple 2' not in text
