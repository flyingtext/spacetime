from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user')

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def is_admin(self) -> bool:
        return self.role == 'admin'


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    path = db.Column(db.String(200), nullable=False)
    language = db.Column(db.String(8), nullable=False, default='en')
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    author = db.relationship('User', backref='posts')
    tags = db.relationship('Tag', secondary='post_tag', backref='posts')
    __table_args__ = (
        db.UniqueConstraint('path', 'language', name='uix_path_language'),
    )


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)


class PostTag(db.Model):
    __tablename__ = 'post_tag'
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tag.id'), primary_key=True)


class Revision(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    path = db.Column(db.String(200), nullable=False)
    language = db.Column(db.String(8), nullable=False, default='en')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User')
    post = db.relationship('Post', backref='revisions')
