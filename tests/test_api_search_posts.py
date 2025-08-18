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


def test_api_search_pagination(client):
    resp = client.get('/api/posts', query_string={'q': 'apple', 'limit': 2})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['total'] == 3
    titles = [p['title'] for p in data['posts']]
    assert titles == ['Apple 2', 'Apple 1']

    resp = client.get('/api/posts', query_string={'q': 'apple', 'limit': 2, 'offset': 2})
    data = resp.get_json()
    titles = [p['title'] for p in data['posts']]
    assert titles == ['Apple 0']

    resp = client.get('/api/posts', query_string={'q': 'apple', 'limit': 0})
    data = resp.get_json()
    assert len(data['posts']) == 3
