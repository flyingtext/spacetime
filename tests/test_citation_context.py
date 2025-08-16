import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, PostCitation


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


def test_citation_context_display(client):
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
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        post = Post.query.first()
        post_id = post.id
    resp = client.post(
        f'/post/{post_id}/citation/new',
        data={
            'citation_text': '@article{a,title={t}}',
            'citation_context': 'Intro section',
        },
    )
    assert resp.status_code == 302
    resp = client.get(f'/post/{post_id}')
    assert b'Intro section' in resp.data
    with app.app_context():
        cit = PostCitation.query.filter_by(post_id=post_id).first()
        assert cit.context == 'Intro section'
