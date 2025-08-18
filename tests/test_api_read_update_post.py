import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, PostMetadata


@pytest.fixture
def client_and_post():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        user = User(username='editor', role='editor')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
        post = Post(title='Old Title', body='Old Body', path='old', language='en', author_id=user.id)
        db.session.add(post)
        db.session.add(PostMetadata(post=post, key='foo', value='bar'))
        db.session.commit()
        pid = post.id
    with app.test_client() as client:
        client.post('/login', data={'username': 'editor', 'password': 'pw'})
        yield client, pid
    with app.app_context():
        db.drop_all()


def test_api_get_post(client_and_post):
    client, pid = client_and_post
    resp = client.get(f'/api/posts/{pid}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['title'] == 'Old Title'
    assert data['metadata']['foo'] == 'bar'


def test_api_update_post(client_and_post):
    client, pid = client_and_post
    resp = client.put(
        f'/api/posts/{pid}',
        json={'title': 'New Title', 'body': 'New Body', 'metadata': {'foo': 'baz', 'lat': 1.0, 'lon': 2.0}},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['title'] == 'New Title'
    with app.app_context():
        post = Post.query.get(pid)
        assert post.title == 'New Title'
        assert post.body == 'New Body'
        meta = {m.key: m.value for m in post.metadata}
        assert meta['foo'] == 'baz'
        assert meta['lat'] == '1.0'
        assert meta['lon'] == '2.0'
        assert post.latitude == 1.0
        assert post.longitude == 2.0
