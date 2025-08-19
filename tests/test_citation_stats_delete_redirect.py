import os
import sys
import re
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
        post = Post(title='Post', body='Body', path='p', language='en', author=admin)
        db.session.add(post)
        db.session.commit()
        for i in range(25):
            db.session.add(
                PostCitation(
                    post_id=post.id,
                    user_id=admin.id,
                    citation_part={'title': f't{i}'},
                    citation_text=f'Cite {i}',
                    context='',
                    doi=f'10.1000/{i}',
                    bibtex_raw='@article{a}',
                    bibtex_fields={'title': f't{i}'},
                )
            )
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_delete_redirects_to_same_page(client):
    client.post('/login', data={'username': 'admin', 'password': 'pw'})
    resp = client.get('/citations/stats', query_string={'page': 2})
    html = resp.data.decode()
    m = re.search(r'href="https://doi.org/([^"]+)">.*?<textarea name="citation_text" class="d-none">(.*?)</textarea>', html, re.S)
    assert m is not None
    doi = m.group(1)
    citation_text = m.group(2)
    resp = client.post('/citations/delete', data={'doi': doi, 'citation_text': citation_text, 'page': 2})
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/citations/stats?page=2'
