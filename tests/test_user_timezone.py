import os
import sys
from datetime import datetime

import pytest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        user = User(username='u', role='editor')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
    with app.test_client() as client:
        client.post('/login', data={'username': 'u', 'password': 'pw'})
        yield client
    with app.app_context():
        db.drop_all()


def test_profile_timezone_and_locale(client):
    resp = client.post(
        '/post/new',
        data={
            'title': 'T',
            'body': 'B',
            'path': 'p',
            'language': 'en',
            'tags': '',
            'metadata': '',
            'user_metadata': '',
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        post = Post.query.first()
        rev = post.revisions[0]
        rev.created_at = datetime(2024, 1, 1, 0, 0)
        db.session.commit()

    client.post('/user/u', data={'bio': '', 'locale': 'es', 'timezone': 'Asia/Seoul'})

    resp = client.get('/user/u')
    data = resp.get_data(as_text=True)
    assert 'Locale' in data
    assert 'es' in data
    assert 'Timezone' in data
    assert 'Asia/Seoul' in data

    resp = client.get('/recent')
    data = resp.get_data(as_text=True)
    assert '09:00' in data
    assert 'KST' in data

