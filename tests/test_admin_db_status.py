import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = User(username='admin', role='admin')
        admin.set_password('pw')
        user = User(username='user', role='user')
        user.set_password('pw')
        db.session.add_all([admin, user])
        post = Post(title='T', body='B', path='p', language='en', author=user)
        db.session.add(post)
        db.session.commit()
    with app.test_client() as client:
        client.post('/login', data={'username': 'admin', 'password': 'pw'})
        yield client
    with app.app_context():
        db.drop_all()


def test_admin_can_view_db_status(client):
    resp = client.get('/admin/db-status')
    assert resp.status_code == 200
    assert b'user' in resp.data
    assert b'post' in resp.data


@pytest.fixture
def normal_client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.drop_all()
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
    resp = normal_client.get('/admin/db-status')
    assert resp.status_code == 403
