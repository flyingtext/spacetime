import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Tag, PostMetadata


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


def test_tags_page_includes_locations_and_post_links(client):
    resp = client.get('/tags')
    data = resp.get_data(as_text=True)
    assert 'tagLocations' in data
    assert '"lat": 10.0' in data
    assert '/tag/t1' in data
    assert '/docs/en/p1' in data


def test_tags_page_uses_metadata_for_locations(client):
    with app.app_context():
        user = User.query.filter_by(username='u').first()
        tag = Tag(name='t2')
        db.session.add(tag)
        db.session.commit()
        post = Post(
            title='Post2',
            body='body',
            path='p2',
            language='en',
            author_id=user.id,
            tags=[tag],
        )
        db.session.add(post)
        db.session.flush()
        db.session.add_all([
            PostMetadata(post=post, key='lat', value='30.0'),
            PostMetadata(post=post, key='lon', value='40.0'),
        ])
        db.session.commit()
    resp = client.get('/tags')
    data = resp.get_data(as_text=True)
    assert '"lat": 30.0' in data
    assert '/tag/t2' in data
