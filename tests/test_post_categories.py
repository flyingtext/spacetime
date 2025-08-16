import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, Tag, Setting


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_posts_category_filter(client):
    with app.app_context():
        user = User(username='author')
        user.set_password('pw')
        db.session.add(user)
        news = Tag(name='news')
        tech = Tag(name='tech')
        misc = Tag(name='misc')
        db.session.add_all([news, tech, misc])
        p1 = Post(title='News Post', body='b', path='news', language='en', author=user, tags=[news])
        p2 = Post(title='Tech Post', body='b', path='tech', language='en', author=user, tags=[tech])
        p3 = Post(title='Misc Post', body='b', path='misc', language='en', author=user, tags=[misc])
        db.session.add_all([p1, p2, p3])
        db.session.add(Setting(key='post_categories', value='news, tech'))
        db.session.commit()

    resp = client.get('/posts')
    assert resp.status_code == 200
    assert b'?tag=news' in resp.data
    assert b'?tag=tech' in resp.data

    resp = client.get('/posts', query_string={'tag': 'news'})
    assert b'News Post' in resp.data
    assert b'Tech Post' not in resp.data
    assert b'Misc Post' not in resp.data

