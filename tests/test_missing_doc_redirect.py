import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db


def test_missing_doc_redirect():
    original_uri = app.config['SQLALCHEMY_DATABASE_URI']
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.engine.dispose()
        db.create_all()
        client = app.test_client()
        resp = client.get('/docs/en/NonexistentPage')
        assert resp.status_code == 302
        loc = resp.headers['Location']
        assert '/post/new' in loc
        assert 'title=NonexistentPage' in loc
        assert 'path=NonexistentPage' in loc
        assert 'language=en' in loc
        db.drop_all()
    app.config['SQLALCHEMY_DATABASE_URI'] = original_uri
    with app.app_context():
        db.engine.dispose()
