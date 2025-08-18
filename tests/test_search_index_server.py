import os
import sys

import pytest
import requests

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


def test_index_server_called_on_save(client, monkeypatch):
    calls: list[tuple[str, dict]] = []

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, json):
        calls.append((url, json))
        return FakeResp()

    monkeypatch.setenv('INDEX_SERVER_URL', 'http://index')
    monkeypatch.setattr(requests, 'post', fake_post)

    with app.app_context():
        user = User.query.filter_by(username='u').first()
        post = Post(title='Dog', body='dog', path='dog', language='en', author_id=user.id)
        db.session.add(post)
        db.session.commit()
        post.title = 'Doggo'
        db.session.commit()

    assert calls[0][0] == 'http://index/index'
    assert calls[0][1]['title'] == 'Dog'
    assert calls[1][1]['title'] == 'Doggo'


def test_index_server_called_on_delete(client, monkeypatch):
    deleted: list[str] = []

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_delete(url):
        deleted.append(url)
        return FakeResp()

    monkeypatch.setenv('INDEX_SERVER_URL', 'http://index')
    monkeypatch.setattr(requests, 'delete', fake_delete)

    with app.app_context():
        post = Post.query.filter_by(title='Apple').first()
        pid = post.id
        db.session.delete(post)
        db.session.commit()

    assert deleted == [f'http://index/index/{pid}']
