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
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_deleted_posts_not_listed(client):
    with app.app_context():
        user = User(username='author')
        user.set_password('pw')
        db.session.add(user)
        p1 = Post(title='Visible', body='Content', path='visible', language='en', author=user)
        p2 = Post(title='Hidden', body='Content', path='hidden', language='en', author=user)
        db.session.add_all([p1, p2])
        db.session.commit()
        p2.title = ''
        p2.body = ''
        db.session.commit()
    resp = client.get('/posts')
    assert b'Visible' in resp.data
    assert b'Hidden' not in resp.data
