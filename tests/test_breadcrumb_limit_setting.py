import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Setting


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['LANGUAGES'] = ['en', 'ko']
    with app.app_context():
        db.drop_all()
        db.create_all()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_breadcrumb_limit_setting(client):
    with app.app_context():
        admin = User(username='admin', role='admin')
        admin.set_password('pw')
        db.session.add(admin)
        post = Post(title='Hello', body='Body', path='hello', language='en', author=admin)
        db.session.add(post)
        db.session.commit()
        pid = post.id
    client.post('/login', data={'username': 'admin', 'password': 'pw'})
    client.post('/settings', data={'breadcrumb_limit': '5'})
    resp = client.get(f'/post/{pid}')
    assert b'const maxItems = 5;' in resp.data
    with app.app_context():
        assert Setting.query.filter_by(key='breadcrumb_limit').first().value == '5'
