import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Revision


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


def test_delete_post_clears_content_and_preserves_revisions(client):
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
        revisions = Revision.query.filter_by(post_id=post_id).all()
        assert len(revisions) == 1
    resp = client.post(f'/post/{post_id}/delete')
    assert resp.status_code == 302
    with app.app_context():
        post = Post.query.get(post_id)
        assert post.title == ''
        assert post.body == ''
        revisions = Revision.query.filter_by(post_id=post_id).order_by(Revision.id).all()
        assert len(revisions) == 2
        assert revisions[-1].body == 'Body'


def test_revision_diff_available_after_deletion(client):
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
        revision = Revision.query.filter_by(post_id=post_id).first()
        rev_id = revision.id
    resp = client.post(f'/post/{post_id}/delete')
    assert resp.status_code == 302
    resp = client.get(f'/post/{post_id}/diff/{rev_id}')
    assert resp.status_code == 200
    assert b'-Body' in resp.data


def test_recent_page_links_to_diff_for_deleted_post(client):
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
        revision = Revision.query.filter_by(post_id=post_id).first()
        rev_id = revision.id
    resp = client.post(f'/post/{post_id}/delete')
    assert resp.status_code == 302
    resp = client.get('/recent')
    assert resp.status_code == 200
    assert f'/post/{post_id}/diff/{rev_id}'.encode() in resp.data
    resp = client.get(f'/post/{post_id}/diff/{rev_id}')
    assert resp.status_code == 200
    assert b'-Body' in resp.data
