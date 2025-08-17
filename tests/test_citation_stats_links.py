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
        user = User(username='author')
        user.set_password('pw')
        db.session.add(user)
        post = Post(title='Post', body='Content', path='post', language='en', author=user)
        db.session.add(post)
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_citation_links(client):
    with app.app_context():
        user = User.query.first()
        post = Post.query.first()
        db.session.add(
            PostCitation(
                post_id=post.id,
                user_id=user.id,
                citation_part={'title': 'title1'},
                citation_text='Cite 1',
                context='',
                doi='10.1000/xyz',
                bibtex_raw='@article{a}',
                bibtex_fields={'title': 'title1'},
            )
        )
        db.session.add(
            PostCitation(
                post_id=post.id,
                user_id=user.id,
                citation_part={'title': 'title2'},
                citation_text='No DOI',
                context='',
                doi=None,
                bibtex_raw='@article{b}',
                bibtex_fields={'title': 'title2'},
            )
        )
        db.session.commit()

    resp = client.get('/citations/stats')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')
    assert 'href="https://doi.org/10.1000/xyz"' in html
    assert 'href="https://scholar.google.com/scholar?q=No%20DOI"' in html
