import os
import sys
from datetime import datetime, timedelta
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post


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
        db.session.add_all([admin, user])
        db.session.commit()
        post = Post(title='T', body='B', path='p', language='en', author=user)
        db.session.add(post)
        db.session.commit()
    with app.test_client() as client:
        client.post('/login', data={'username': 'admin', 'password': 'pw'})
        yield client
    with app.app_context():
        db.drop_all()


def test_admin_stats_counts(client):
    resp = client.get('/admin/stats')
    assert resp.status_code == 200
    assert b'Users</th><td>2' in resp.data
    assert b'Posts</th><td>1' in resp.data


def test_admin_stats_time_series_json(client):
    with app.app_context():
        user = User.query.filter_by(username='user').first()
        older = datetime.utcnow() - timedelta(days=1)
        post2 = Post(title='T2', body='B2', path='p2', language='en', author=user, created_at=older)
        db.session.add(post2)
        db.session.commit()
    resp = client.get('/admin/stats/posts_over_time')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'daily' in data and 'weekly' in data and 'monthly' in data and 'yearly' in data
    daily_counts = {item['period']: item['count'] for item in data['daily']}
    assert len(daily_counts) >= 2


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


def test_non_admin_forbidden(normal_client):
    resp = normal_client.get('/admin/stats')
    assert resp.status_code == 403
