import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User, RequestedPost


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        requester = User(username='req', role='user')
        requester.set_password('pw')
        admin = User(username='admin', role='admin')
        admin.set_password('pw')
        db.session.add_all([requester, admin])
        db.session.commit()
        req = RequestedPost(title='Need', description='Desc', requester=requester)
        db.session.add(req)
        db.session.commit()
        req_id = req.id
    with app.test_client() as client:
        client.post('/login', data={'username': 'admin', 'password': 'pw'})
        yield client, req_id
    with app.app_context():
        db.drop_all()


def test_admin_can_add_comment(client):
    client, req_id = client
    resp = client.post('/admin/requested', data={'request_id': req_id, 'comment': 'processing'}, follow_redirects=True)
    assert resp.status_code == 200
    resp = client.get('/posts/requested')
    assert b'processing' in resp.data
