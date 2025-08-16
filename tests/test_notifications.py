import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Notification


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        users = [
            User(username='author', role='editor'),
            User(username='watcher1'),
            User(username='watcher2'),
            User(username='admin', role='admin'),
        ]
        for u in users:
            u.set_password('pw')
            db.session.add(u)
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def login(client, username):
    return client.post('/login', data={'username': username, 'password': 'pw'})


def logout(client):
    client.post('/logout')


def create_post(client):
    login(client, 'author')
    client.post(
        '/post/new',
        data={
            'title': 'Title',
            'body': 'Body',
            'path': 'p',
            'language': 'en',
            'tags': '',
            'metadata': '',
            'user_metadata': '',
        },
    )
    logout(client)
    with app.app_context():
        return Post.query.first().id


def test_citation_notifications(client):
    post_id = create_post(client)
    login(client, 'watcher1')
    client.post(f'/post/{post_id}/watch', data={})
    logout(client)

    login(client, 'watcher2')
    client.post(f'/post/{post_id}/watch', data={})
    logout(client)

    login(client, 'watcher1')
    client.post(
        f'/post/{post_id}/citation/new',
        data={'citation_text': '@article{a,title={t}}'},
    )
    logout(client)

    with app.app_context():
        author = User.query.filter_by(username='author').first()
        watcher1 = User.query.filter_by(username='watcher1').first()
        watcher2 = User.query.filter_by(username='watcher2').first()
        assert Notification.query.filter_by(user_id=author.id).count() == 1
        assert Notification.query.filter_by(user_id=watcher2.id).count() == 1
        assert Notification.query.filter_by(user_id=watcher1.id).count() == 0


def test_metadata_update_notifies_author(client):
    post_id = create_post(client)
    login(client, 'admin')
    client.post(
        f'/post/{post_id}/edit',
        data={
            'title': 'Title',
            'body': 'Body',
            'path': 'p',
            'language': 'en',
            'tags': '',
            'metadata': '{"k":"v"}',
            'user_metadata': '',
            'lat': '',
            'lon': '',
        },
    )
    logout(client)

    with app.app_context():
        author = User.query.filter_by(username='author').first()
        admin = User.query.filter_by(username='admin').first()
        assert Notification.query.filter_by(user_id=author.id).count() == 1
        assert Notification.query.filter_by(user_id=admin.id).count() == 0


def test_notification_link_rendered(client):
    post_id = create_post(client)
    login(client, 'watcher1')
    client.post(f'/post/{post_id}/watch', data={})
    logout(client)

    login(client, 'watcher2')
    client.post(
        f'/post/{post_id}/citation/new',
        data={'citation_text': '@article{a,title={t}}'},
    )
    logout(client)

    login(client, 'watcher1')
    resp = client.get('/notifications')
    assert f'href="/post/{post_id}"' in resp.text
    logout(client)

