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


def test_api_add_url_citation(client):
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
        post_id = Post.query.first().id
    resp = client.post(
        f'/api/posts/{post_id}/citation',
        json={'url': 'https://example.com', 'context': 'Intro'},
    )
    assert resp.status_code == 201
    assert resp.json['url'] == 'https://example.com'
    with app.app_context():
        cit = PostCitation.query.filter_by(post_id=post_id).first()
        assert cit.citation_text == 'https://example.com'
        assert cit.context == 'Intro'
