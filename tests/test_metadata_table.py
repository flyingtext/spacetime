import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, PostMetadata


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        user = User(username='u')
        user.set_password('pw')
        post = Post(
            title='T',
            body='# H1\ncontent',
            path='p',
            language='en',
            author=user,
        )
        db.session.add_all([user, post])
        db.session.flush()
        db.session.add_all([
            PostMetadata(post=post, key='k', value='v'),
            PostMetadata(post=post, key='lat', value='10'),
            PostMetadata(post=post, key='lon', value='20'),
        ])
        db.session.commit()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_metadata_table_under_toc(client):
    resp = client.get('/docs/en/p')
    html = resp.get_data(as_text=True)
    start = html.find('<nav class="toc-container')
    end = html.find('</nav>', start)
    nav_html = html[start:end]
    assert '<table' in nav_html
    assert 'k' in nav_html
    assert 'v' in nav_html


def test_map_and_location_moved_under_toc(client):
    resp = client.get('/docs/en/p')
    html = resp.get_data(as_text=True)
    start = html.find('<nav class="toc-container')
    end = html.find('</nav>', start)
    nav_html = html[start:end]
    assert '<div id="map"' in nav_html
    assert html.count('<div id="map"') == 1
    assert '<h2>Location</h2>' not in html
