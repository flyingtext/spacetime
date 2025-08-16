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
        tag = Tag(name='t1')
        db.session.add_all([user, tag])
        db.session.commit()
        post = Post(
            title='Post1',
            body='body',
            path='p1',
            language='en',
            author_id=user.id,
            latitude=10.0,
            longitude=20.0,
            tags=[tag],
        )
        db.session.add(post)
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_tags_page_includes_locations(client):
    resp = client.get('/tags')
    data = resp.get_data(as_text=True)
    assert 'tagLocations' in data
    assert '"lat": 10.0' in data
    assert '/tag/t1' in data
