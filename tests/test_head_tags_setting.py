import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, User


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


def test_custom_head_tags_rendered(client):
    meta = '<meta name="test" content="value">'
    with app.app_context():
        admin = User(username='admin', role='admin')
        admin.set_password('pw')
        db.session.add(admin)
        db.session.commit()
    client.post('/login', data={'username': 'admin', 'password': 'pw'})
    client.post('/settings', data={'head_tags': meta})
    resp = client.get('/')
    assert meta.encode() in resp.data
