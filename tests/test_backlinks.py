import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, PostLink, update_post_links


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
        p1 = Post(title='P1', body='See [[p2]]', path='p1', language='en', author=user)
        p2 = Post(title='P2', body='No links', path='p2', language='en', author=user)
        db.session.add_all([p1, p2])
        db.session.commit()
        update_post_links(p1)
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_backlinks(client):
    with app.app_context():
        target = Post.query.filter_by(path='p2').first()
        assert target is not None
        link = PostLink.query.filter_by(target_id=target.id).first()
        assert link is not None
        resp = client.get(f'/post/{target.id}/backlinks')
        assert resp.status_code == 200
        assert b'P1' in resp.data
