import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, PostView


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        admin = User(username='admin', role='admin')
        admin.set_password('pw')
        user = User(username='user', role='user')
        user.set_password('pw')
        post = Post(title='T', body='B', path='p', language='en', author=user)
        db.session.add_all([admin, user, post])
        db.session.commit()
    with app.test_client() as client:
        client.post('/login', data={'username': 'admin', 'password': 'pw'})
        yield client
    with app.app_context():
        db.drop_all()


def test_view_stats_page(client):
    client.get('/docs/en/p')
    resp = client.get('/admin/view-stats')
    assert resp.status_code == 200
    assert b'Total Views' in resp.data
    assert b'Total Visitors' in resp.data


def test_view_stats_top_posts_json(client):
    client.get('/docs/en/p')
    resp = client.get('/admin/view-stats/top_posts')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'daily' in data and len(data['daily']) >= 1
    assert data['daily'][0]['views'] == 1


@pytest.fixture
def normal_client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        user = User(username='user', role='user')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
    with app.test_client() as client:
        client.post('/login', data={'username': 'user', 'password': 'pw'})
        yield client
    with app.app_context():
        db.drop_all()


def test_view_stats_forbidden(normal_client):
    resp = normal_client.get('/admin/view-stats')
    assert resp.status_code == 403
