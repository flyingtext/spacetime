import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Redirect


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


def test_redirect_on_path_change(client):
    with app.app_context():
        user = User.query.filter_by(username='editor').first()
        post = Post(title='Title', body='Body', path='old', language='en', author=user)
        db.session.add(post)
        db.session.commit()
        post_id = post.id

    resp = client.post(
        f'/post/{post_id}/edit',
        data={
            'title': 'Title',
            'body': 'Body',
            'path': 'new',
            'language': 'en',
            'tags': '',
            'metadata': '',
            'user_metadata': '',
        },
    )
    assert resp.status_code == 302

    with app.app_context():
        redirect_entry = Redirect.query.filter_by(
            old_path='old', new_path='new', language='en'
        ).first()
        assert redirect_entry is not None

    resp = client.get('/docs/en/old')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/en/new')
