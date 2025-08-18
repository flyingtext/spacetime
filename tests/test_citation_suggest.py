import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app
from app import db, User, Post


@pytest.fixture
def app_ctx():
    app.app.config['TESTING'] = True
    app.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app.app_context():
        db.create_all()
        user = User(username='author', role='editor')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def test_suggest_citations_internal(app_ctx):
    with app_ctx.app.app_context():
        post = Post(
            title='Quantum mechanics',
            body='Quantum mechanics studies matter at small scales.',
            path='quantum',
            language='en',
            author_id=1,
        )
        db.session.add(post)
        db.session.commit()

        text = 'Quantum mechanics covers interesting topics.'
        results = app_ctx.suggest_citations(text)
        assert text in results
        cand = results[text][0]['text']
        assert 'Quantum mechanics' in cand
        assert '/en/quantum' in cand

