import os, sys, pytest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, Post, PostMetadata

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.drop_all()
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

def test_edit_updates_location(client):
    meta = '{"locations":[{"lat":1,"lon":2}]}'
    client.post('/post/new', data={'title':'t','body':'b','path':'p','language':'en','tags':'','metadata':meta,'user_metadata':'','lat':'1','lon':'2'})
    with app.app_context():
        post = Post.query.first()
        pid = post.id
    stale_meta = meta
    client.post(f'/post/{pid}/edit', data={'title':'t','body':'b','path':'p','language':'en','tags':'','metadata':stale_meta,'user_metadata':'','lat':'5','lon':'6'})
    with app.app_context():
        loc_meta = PostMetadata.query.filter_by(post_id=pid, key='locations').first()
        assert loc_meta is not None
        assert loc_meta.value == [{'lat': '5', 'lon': '6'}]
        post = Post.query.get(pid)
        assert post.latitude == 5.0
        assert post.longitude == 6.0
