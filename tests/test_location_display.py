import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app
from app import app as flask_app, db, User, Post, PostMetadata


@pytest.fixture
def client(monkeypatch):
    flask_app.config['TESTING'] = True
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    monkeypatch.setattr(app, 'reverse_geocode_coords', lambda lat, lon: None)
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        user = User(username='u')
        user.set_password('pw')
        post = Post(title='Post', body='body', path='p', language='en', author=user)
        db.session.add_all([user, post])
        db.session.flush()
        db.session.add_all([
            PostMetadata(post=post, key='lat', value='10.0'),
            PostMetadata(post=post, key='lon', value='20.0'),
        ])
        db.session.commit()
    with flask_app.test_client() as client:
        yield client
    with flask_app.app_context():
        db.drop_all()


def test_coordinates_not_list_items(client):
    resp = client.get('/docs/en/p')
    data = resp.get_data(as_text=True)
    assert '<strong>lat:' not in data
    assert '<strong>lon:' not in data
    assert '(10.0, 20.0)' in data
