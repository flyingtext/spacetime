import os
import sys
import pytest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app as app_module
from app import app, db, User, Post, PostMetadata


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        user = User(username='editor', role='editor')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
    with app.test_client() as client:
        client.post('/login', data={'username': 'editor', 'password': 'pw'})
        yield client
    with app.app_context():
        db.drop_all()


def test_api_creates_post_from_markdown(client):
    resp = client.post(
        '/api/posts',
        json={
            'title': 'API Title',
            'body': 'API Body',
            'path': 'api-path',
            'language': 'en'
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['path'] == 'api-path'
    with app.app_context():
        post = Post.query.filter_by(path='api-path', language='en').first()
        assert post is not None
        assert post.body == 'API Body'


def test_api_creates_post_with_lat_lon(client):
    resp = client.post(
        '/api/posts',
        json={
            'title': 'Loc Title',
            'body': 'Loc Body',
            'path': 'loc-path',
            'language': 'en',
            'lat': 1.0,
            'lon': 2.0,
        },
    )
    assert resp.status_code == 201
    with app.app_context():
        post = Post.query.filter_by(path='loc-path', language='en').first()
        assert post.latitude == 1.0
        assert post.longitude == 2.0
        lat_meta = PostMetadata.query.filter_by(post_id=post.id, key='lat').first()
        lon_meta = PostMetadata.query.filter_by(post_id=post.id, key='lon').first()
        assert lat_meta.value == '1.0'
        assert lon_meta.value == '2.0'


def test_api_creates_post_with_address(client, monkeypatch):
    monkeypatch.setattr(app_module, 'geocode_address', lambda addr: (3.0, 4.0))
    resp = client.post(
        '/api/posts',
        json={
            'title': 'Addr Title',
            'body': 'Addr Body',
            'path': 'addr-path',
            'language': 'en',
            'address': 'Somewhere',
        },
    )
    assert resp.status_code == 201
    with app.app_context():
        post = Post.query.filter_by(path='addr-path', language='en').first()
        assert post.latitude == 3.0
        assert post.longitude == 4.0
        lat_meta = PostMetadata.query.filter_by(post_id=post.id, key='lat').first()
        lon_meta = PostMetadata.query.filter_by(post_id=post.id, key='lon').first()
        assert lat_meta.value == '3.0'
        assert lon_meta.value == '4.0'
