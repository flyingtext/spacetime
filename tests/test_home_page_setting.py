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
    assert resp.headers['Location'].endswith('/en/home')


def test_home_page_redirect_ko_locale(client):
    with app.app_context():
        user = User(username='author')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
        post = Post(
            title='Spacetime',
            body='Content',
            path='spacetime',
            language='ko',
            author=user,
        )
        db.session.add(post)
        db.session.add(Setting(key='home_page_path', value='spacetime'))
        db.session.commit()

    resp = client.get('/', headers={'Accept-Language': 'ko'})
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/ko/spacetime')


def test_home_page_with_language_in_setting(client):
    with app.app_context():
        user = User(username='author')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
        post = Post(
            title='Spacetime',
            body='Content',
            path='spacetime',
            language='ko',
            author=user,
        )
        db.session.add(post)
        db.session.add(Setting(key='home_page_path', value='ko/spacetime'))
        db.session.commit()

    resp = client.get('/', headers={'Accept-Language': 'en'})
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/ko/spacetime')


def test_updating_home_page_path_preserves_site_title(client):
    with app.app_context():
        admin = User(username='admin', role='admin')
        admin.set_password('pw')
        db.session.add(admin)
        db.session.add(Setting(key='site_title', value='Original Title'))
        db.session.add(Setting(key='home_page_path', value='home'))
        db.session.commit()

    client.post('/login', data={'username': 'admin', 'password': 'pw'})

    resp = client.post('/settings', data={'home_page_path': 'new-home'})
    assert resp.status_code == 302

    with app.app_context():
        assert Setting.query.filter_by(key='site_title').first().value == 'Original Title'
        assert Setting.query.filter_by(key='home_page_path').first().value == 'new-home'
