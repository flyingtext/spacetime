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


def test_citation_stats_pagination(client):
    with app.app_context():
        user = User.query.first()
        post = Post.query.first()
        for i in range(25):
            db.session.add(
                PostCitation(
                    post_id=post.id,
                    user_id=user.id,
                    citation_part={'title': f'title{i}'},
                    citation_text=f'Cite {i}',
                    context='',
                    doi=f'10.1000/{i}',
                    bibtex_raw='@article{a}',
                    bibtex_fields={'title': f'title{i}'},
                )
            )
        db.session.commit()

    resp = client.get('/citations/stats')
    assert resp.status_code == 200
    assert resp.data.count(b'https://doi.org') == 20

    resp = client.get('/citations/stats', query_string={'page': 2})
    assert resp.status_code == 200
    assert resp.data.count(b'https://doi.org') == 5
