import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Revision


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        u = User(username='u')
        u.set_password('pw')
        other = User(username='o')
        other.set_password('pw')
        db.session.add_all([u, other])
        db.session.commit()
        p1 = Post(
            title='P1',
            body='b',
            path='p1',
            language='en',
            author_id=u.id,
            latitude=10.0,
            longitude=20.0,
        )
        p2 = Post(
            title='P2',
            body='b',
            path='p2',
            language='en',
            author_id=other.id,
            latitude=30.0,
            longitude=40.0,
        )
        db.session.add_all([p1, p2])
        db.session.commit()
        rev = Revision(
            post_id=p2.id,
            user_id=u.id,
            title=p2.title,
            body=p2.body,
            path=p2.path,
            language=p2.language,
        )
        db.session.add(rev)
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_profile_includes_post_locations(client):
    resp = client.get('/user/u')
    data = resp.get_data(as_text=True)
    assert 'postLocations' in data
    assert '"lat": 10.0' in data
    assert '"lat": 30.0' in data
