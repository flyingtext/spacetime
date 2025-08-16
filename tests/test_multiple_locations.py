import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        u = User(username='u', role='editor')
        u.set_password('pw')
        db.session.add(u)
        db.session.commit()
    with app.test_client() as client:
        client.post('/login', data={'username': 'u', 'password': 'pw'})
        yield client
    with app.app_context():
        db.drop_all()


def test_render_multiple_locations(client):
    meta = '{"loc1":{"lat":1,"lon":2},"loc2":{"lat":3,"lon":4}}'
    resp = client.post(
        '/post/new',
        data={
            'title': 't',
            'body': 'b',
            'path': 'p',
            'language': 'en',
            'tags': '',
            'metadata': meta,
            'user_metadata': '',
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        post = Post.query.first()
        pid = post.id
    resp = client.get(f'/post/{pid}')
    html = resp.get_data(as_text=True)
    assert '(1.0, 2.0)' in html
    assert '(3.0, 4.0)' in html

