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
        post = Post(title='Original Title', body='Original Body', path='p1', language='en', author_id=user.id)
        db.session.add(post)
        db.session.commit()
        rev = Revision(post=post, user=user, title=post.title, body=post.body, path=post.path, language=post.language)
        db.session.add(rev)
        db.session.commit()
        post.title = 'Edited Title'
        post.body = 'Edited Body'
        post.path = 'p2'
        post.language = 'es'
        db.session.commit()
    with app.test_client() as client:
        client.post('/login', data={'username': 'editor', 'password': 'pw'})
        yield client
    with app.app_context():
        db.drop_all()


def test_revert_revision(client):
    with app.app_context():
        post = Post.query.first()
        rev = Revision.query.filter_by(post_id=post.id).first()
        post_id = post.id
        rev_id = rev.id
    resp = client.post(f'/post/{post_id}/revert/{rev_id}')
    assert resp.status_code == 302
    with app.app_context():
        post = Post.query.get(post_id)
        assert post.title == 'Original Title'
        assert post.body == 'Original Body'
        assert post.path == 'p1'
        assert post.language == 'en'
        revisions = Revision.query.filter_by(post_id=post_id).order_by(Revision.id).all()
        assert len(revisions) == 2
        assert revisions[-1].title == 'Edited Title'
