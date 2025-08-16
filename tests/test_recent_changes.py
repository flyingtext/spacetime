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


def test_recent_changes_show_comment_and_delta(client):
    resp = client.post(
        '/post/new',
        data={
            'title': 'Title',
            'body': 'Body',
            'path': 'p',
            'language': 'en',
            'tags': '',
            'metadata': '',
            'user_metadata': '',
            'comment': 'initial',
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        post = Post.query.first()
        post_id = post.id
    resp = client.post(
        f'/post/{post_id}/edit',
        data={
            'title': 'Title',
            'body': 'Body1',
            'path': 'p',
            'language': 'en',
            'tags': '',
            'metadata': '',
            'user_metadata': '',
            'comment': 'edit',
        },
    )
    assert resp.status_code == 302
    resp = client.get('/recent')
    assert resp.status_code == 200
    assert b'initial' in resp.data
    assert b'(+4)' in resp.data
    assert b'edit' in resp.data
    assert b'(+1)' in resp.data
