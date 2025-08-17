import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app as app_module
from app import app, db, User, Post


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


def test_post_shows_reverse_geocode(client, monkeypatch):
    monkeypatch.setattr(app_module, 'reverse_geocode_coords', lambda lat, lon: 'Test Place')
    resp = client.post(
        '/post/new',
        data={
            'title': 'Title',
            'body': 'Body',
            'path': 'p',
            'language': 'en',
            'tags': '',
            'metadata': '{"loc":{"lat":1,"lon":2}}',
            'user_metadata': '',
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        post = Post.query.first()
        post_id = post.id
    resp = client.get(f'/post/{post_id}')
    assert b'Test Place' in resp.data


def test_doc_path_shows_reverse_geocode(client, monkeypatch):
    monkeypatch.setattr(app_module, 'reverse_geocode_coords', lambda lat, lon: 'Test Place')
    resp = client.post(
        '/post/new',
        data={
            'title': 'Title',
            'body': 'Body',
            'path': 'p',
            'language': 'en',
            'tags': '',
            'metadata': '{"loc":{"lat":1,"lon":2}}',
            'user_metadata': '',
        },
    )
    assert resp.status_code == 302
    resp = client.get('/en/p')
    assert b'Test Place' in resp.data


def test_latlon_fields_reverse_geocode(client, monkeypatch):
    monkeypatch.setattr(app_module, 'reverse_geocode_coords', lambda lat, lon: 'Test Place')
    with app.app_context():
        user = User.query.first()
        post = Post(title='Title', body='Body', path='p2', language='en', author=user)
        post.latitude = 1.0
        post.longitude = 2.0
        db.session.add(post)
        db.session.commit()
        post_id = post.id
    resp = client.get(f'/post/{post_id}')
    assert b'Test Place' in resp.data
    resp = client.get('/en/p2')
    assert b'Test Place' in resp.data
