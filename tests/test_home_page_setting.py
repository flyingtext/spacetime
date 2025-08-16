import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Setting


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


def test_home_page_redirect(client):
    with app.app_context():
        user = User(username='author')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
        post = Post(title='Home', body='Content', path='home', language='en', author=user)
        db.session.add(post)
        db.session.add(Setting(key='home_page_path', value='home'))
        db.session.commit()

    resp = client.get('/')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/docs/en/home')
