import os
import sys

import pytest
import requests
import index_server

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
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
        p1 = Post(title='Apple', body='apple banana', path='p1', language='en', author_id=user.id)
        p1.tags.append(t1)
        p2 = Post(title='Banana', body='banana carrot', path='p2', language='en', author_id=user.id)
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


def test_remote_geo_search(client, monkeypatch):
    with app.app_context():
        banana = Post.query.filter_by(title='Banana').first()

    class FakeResponse:
        status_code = 200

        def json(self):
            return [banana.id]

        def raise_for_status(self):
            pass

    def fake_get(url, params):
        assert params['lat'] == 1.0
        assert params['lon'] == 2.0
        assert params['radius'] == 5.0
        assert params['q'] == 'apple'
        return FakeResponse()

    monkeypatch.setenv('INDEX_SERVER_URL', 'http://index')
    monkeypatch.setattr(requests, 'get', fake_get)

    resp = client.get('/search', query_string={'q': 'apple', 'lat': 1.0, 'lon': 2.0, 'radius': 5.0})
    text_resp = resp.get_data(as_text=True)
    assert 'Banana' in text_resp
    assert 'Apple' not in text_resp


def test_index_server_geo_search(tmp_path):
    db_file = tmp_path / 'search.db'
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        client = index_server.app.test_client()
        client.post('/index', json={'id': '1', 'title': 'Apple', 'body': 'apple', 'lat': 0.0, 'lon': 0.0})
        client.post('/index', json={'id': '2', 'title': 'Banana', 'body': 'banana', 'lat': 10.0, 'lon': 10.0})
        resp = client.get('/search', query_string={'q': 'apple', 'lat': 0.0, 'lon': 0.0, 'radius': 500.0})
        assert resp.get_json() == ['1']
    finally:
        if hasattr(index_server.app, 'db') and getattr(index_server.app.db, 'conn', None):
            index_server.app.db.conn.close()
            del index_server.app.db
        if db_file.exists():
            os.remove(db_file)
        os.chdir(cwd)
