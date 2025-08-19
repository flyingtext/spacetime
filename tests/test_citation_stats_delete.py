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
        admin = User(username='admin', role='admin')
        admin.set_password('pw')
        db.session.add(admin)
        post1 = Post(title='P1', body='Body', path='p1', language='en', author=admin)
        post2 = Post(title='P2', body='Body', path='p2', language='en', author=admin)
        db.session.add_all([post1, post2])
        db.session.commit()
        for post in (post1, post2):
            db.session.add(PostCitation(
                post_id=post.id,
                user_id=admin.id,
                citation_part={'title': 't'},
                citation_text='Cite Me',
                context='',
                doi='10.1234/abc',
                bibtex_raw='@article{a}',
                bibtex_fields={'title': 't'},
            ))
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_delete_citation_everywhere(client):
    client.post('/login', data={'username': 'admin', 'password': 'pw'})
    resp = client.get('/citations/stats')
    assert b'Cite Me' in resp.data
    resp = client.post(
        '/admin/citations/delete-url',
        data={'url': 'Cite Me'},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    resp = client.get('/citations/stats')
    assert b'Cite Me' not in resp.data
    with app.app_context():
        assert PostCitation.query.count() == 0
