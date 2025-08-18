import os
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


def test_save_suggested_citation(client):
    # Create a post that will receive the citation
    resp = client.post(
        '/post/new',
        data={
            'title': 'Main',
            'body': 'Body',
            'path': 'main',
            'language': 'en',
            'tags': '',
            'metadata': '',
            'user_metadata': '',
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        post_id = Post.query.filter_by(path='main').first().id
        bibtex = "@misc{123,\n  title={Reference},\n  url={/en/ref}\n}"
    resp = client.post(
        f'/post/{post_id}/citation/new',
        data={'citation_text': bibtex},
    )
    assert resp.status_code == 302
    with app.app_context():
        cit = PostCitation.query.filter_by(post_id=post_id).first()
        assert cit.citation_part['title'] == 'Reference'
        assert cit.citation_part['url'] == '/en/ref'
