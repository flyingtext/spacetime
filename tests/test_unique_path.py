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


def test_unique_path_generated_for_blank_path(client):
    resp1 = client.post(
        '/post/new',
        data={
            'title': 'Hello World',
            'body': 'Body1',
            'path': '',
            'language': 'en',
            'tags': '',
            'metadata': '',
            'user_metadata': '',
        },
    )
    assert resp1.status_code == 302

    resp2 = client.post(
        '/post/new',
        data={
            'title': 'Hello World',
            'body': 'Body2',
            'path': '',
            'language': 'en',
            'tags': '',
            'metadata': '',
            'user_metadata': '',
        },
    )
    assert resp2.status_code == 302

    with app.app_context():
        posts = Post.query.filter_by(title='Hello World').order_by(Post.id).all()
        assert len(posts) == 2
        assert posts[0].path == 'hello-world'
        assert posts[1].path == 'hello-world-1'
