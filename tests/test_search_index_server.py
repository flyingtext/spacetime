import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from index_server import app as index_app
from app import app, db, User, Post, Tag
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
        t1 = Tag(name='news')
        t2 = Tag(name='science')
        db.session.add_all([user, t1, t2])
        db.session.commit()
        p1 = Post(
            title='Apple',
            body='apple banana',
            path='p1',
            language='en',
            author_id=user.id,
            latitude=10.0,
            longitude=10.0,
        )
        p1.tags.append(t1)
        p2 = Post(
            title='Banana',
            body='banana carrot',
            path='p2',
            language='en',
            author_id=user.id,
            latitude=20.0,
            longitude=20.0,
        )
        p2.tags.append(t2)
        db.session.add_all([p1, p2])
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()
        db.session.execute(text('DROP TABLE IF EXISTS post_fts'))


def test_remote_search_success(client, monkeypatch):
    with app.app_context():
        banana = Post.query.filter_by(title='Banana').first()
    class FakeResponse:
        status_code = 200
        def json(self):
            return {'ids': [banana.id]}
        def raise_for_status(self):
            pass
    monkeypatch.setenv('INDEX_SERVER_URL', 'http://index')
    monkeypatch.setattr(requests, 'get', lambda url, params: FakeResponse())
    resp = client.get('/search', query_string={'q': 'apple'})
    text_resp = resp.get_data(as_text=True)
    assert 'Banana' in text_resp
    assert 'Apple' not in text_resp


def test_remote_search_failure_fallback(client, monkeypatch):
    def fake_get(url, params):
        raise requests.RequestException('boom')
    monkeypatch.setenv('INDEX_SERVER_URL', 'http://index')
    monkeypatch.setattr(requests, 'get', fake_get)
    resp = client.get('/search', query_string={'q': 'apple'})
    text_resp = resp.get_data(as_text=True)
    assert 'Apple' in text_resp
    assert 'Search service unavailable' in text_resp


def test_index_server_metadata_search(tmp_path):
    db_path = 'search.db'
    if os.path.exists(db_path):
        os.remove(db_path)
    with index_app.test_client() as c:
        r = c.post('/index', json={'id': '1', 'title': 'One', 'body': 'foo', 'metadata': {'author': 'alice'}, 'tags': ['t1']})
        assert r.status_code == 200
        r = c.post('/index', json={'id': '2', 'title': 'Two', 'body': 'bar', 'metadata': {'author': 'bob'}, 'tags': []})
        assert r.status_code == 200
        rv = c.get('/search', query_string={'metadata.author': 'alice'})
        assert rv.get_json() == ['1']
        rv = c.get('/search', query_string={'q': 'bar', 'metadata.author': 'bob'})
        assert rv.get_json() == ['2']


def test_remote_metadata_search_success(client, monkeypatch):
    with app.app_context():
        banana = Post.query.filter_by(title='Banana').first()

    class FakeResponse:
        status_code = 200

        def json(self):
            return {'ids': [banana.id]}

        def raise_for_status(self):
            pass

    captured = {}

    def fake_get(url, params):
        captured.update(params)
        return FakeResponse()

    monkeypatch.setenv('INDEX_SERVER_URL', 'http://index')
    monkeypatch.setattr(requests, 'get', fake_get)
    resp = client.get('/search', query_string={'key': 'author', 'value': 'Alice'})
    text_resp = resp.get_data(as_text=True)
    assert 'Banana' in text_resp
    assert captured == {'metadata.author': 'Alice'}


def test_index_server_location_search(tmp_path):
    db_path = 'search.db'
    if hasattr(index_app, 'db') and getattr(index_app.db, 'conn', None):
        index_app.db.conn.close()
        del index_app.db.conn
    if os.path.exists(db_path):
        os.remove(db_path)
    with index_app.test_client() as c:
        r = c.post('/index', json={'id': '1', 'title': 'One', 'body': 'foo', 'lat': 10, 'lon': 10})
        assert r.status_code == 200
        r = c.post('/index', json={'id': '2', 'title': 'Two', 'body': 'bar', 'lat': 20, 'lon': 20})
        assert r.status_code == 200
        rv = c.get('/search', query_string={'lat': 10, 'lon': 10, 'radius': 500})
        assert rv.get_json() == ['1']


def test_remote_location_search_success(client, monkeypatch):
    with app.app_context():
        apple = Post.query.filter_by(title='Apple').first()

    class FakeResponse:
        status_code = 200

        def json(self):
            return {'ids': [apple.id]}

        def raise_for_status(self):
            pass

    captured = {}

    def fake_get(url, params):
        captured.update(params)
        return FakeResponse()

    monkeypatch.setenv('INDEX_SERVER_URL', 'http://index')
    monkeypatch.setattr(requests, 'get', fake_get)
    resp = client.get('/search', query_string={'lat': 10, 'lon': 10, 'radius': 500})
    text_resp = resp.get_data(as_text=True)
    assert 'Apple' in text_resp
    assert captured == {'lat': 10.0, 'lon': 10.0, 'radius': 500.0}
