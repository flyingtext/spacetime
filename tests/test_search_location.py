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
        user = User(username='u')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
        near = Post(
            title='Near Post',
            body='body',
            path='near',
            language='en',
            author_id=user.id,
            latitude=10.0,
            longitude=10.0,
        )
        far = Post(
            title='Far Post',
            body='body',
            path='far',
            language='en',
            author_id=user.id,
            latitude=20.0,
            longitude=20.0,
        )
        db.session.add_all([near, far])
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_search_filters_by_distance(client):
    resp = client.get('/search', query_string={'lat': 10, 'lon': 10, 'radius': 500})
    data = resp.get_data(as_text=True)
    assert 'Near Post' in data
    assert 'Far Post' not in data
    assert 'postCoords' in data
    assert '"lat": 10.0' in data
    assert '"lat": 20.0' not in data

