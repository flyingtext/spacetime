"""Database models for the spacetime application.

This module defines the SQLAlchemy ``db`` instance and all ORM models
previously kept in ``app.py``.  Separating them into their own module keeps
``app.py`` focused on application wiring while models remain importable
from a single place.
"""

from __future__ import annotations

from datetime import datetime

from flask_babel import _
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, text
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()


# Roles allowed to create or edit posts
POST_EDITOR_ROLES = {"editor", "admin"}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default="user")
    bio = db.Column(db.Text)
    locale = db.Column(db.String(8))
    timezone = db.Column(db.String(50), default="UTC")
    tag_modal_new_tab = db.Column(db.Boolean, default=False)
    distance_unit = db.Column(db.String(5), default="km")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def is_admin(self) -> bool:
        return self.role == "admin"

    def can_edit_posts(self) -> bool:
        return self.role in POST_EDITOR_ROLES


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    path = db.Column(db.String(200), nullable=False)
    language = db.Column(db.String(8), nullable=False, default="en")
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    author = db.relationship("User", backref="posts")
    tags = db.relationship("Tag", secondary="post_tag", backref="posts")
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint("path", "language", name="uix_path_language"),
    )

    @property
    def display_title(self) -> str:
        """Return title or a placeholder if the post was deleted."""
        return self.title or _("[deleted]")


@event.listens_for(Post.__table__, "after_create")
def create_post_fts(target, connection, **kw):
    """Create FTS5 table and triggers for Post.body."""
    connection.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS post_fts "
            "USING fts5(body, content=\"post\", content_rowid=\"id\")"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER post_fts_ai AFTER INSERT ON post BEGIN "
            "INSERT INTO post_fts(rowid, body) VALUES (new.id, new.body); "
            "END;"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER post_fts_ad AFTER DELETE ON post BEGIN "
            "INSERT INTO post_fts(post_fts, rowid, body) VALUES('delete', old.id, old.body); "
            "END;"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER post_fts_au AFTER UPDATE ON post BEGIN "
            "INSERT INTO post_fts(post_fts, rowid, body) VALUES('delete', old.id, old.body); "
            "INSERT INTO post_fts(rowid, body) VALUES (new.id, new.body); "
            "END;"
        )
    )


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)


class PostTag(db.Model):
    __tablename__ = "post_tag"
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey("tag.id"), primary_key=True)


class PostLink(db.Model):
    __tablename__ = "post_link"
    source_id = db.Column(db.Integer, db.ForeignKey("post.id"), primary_key=True)
    target_id = db.Column(db.Integer, db.ForeignKey("post.id"), primary_key=True)

    source = db.relationship(
        "Post", foreign_keys=[source_id], backref="outgoing_links"
    )
    target = db.relationship(
        "Post", foreign_keys=[target_id], backref="incoming_links"
    )


class PostWatch(db.Model):
    __tablename__ = "post_watch"
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)

    post = db.relationship(
        "Post", backref=db.backref("watchers", cascade="all, delete-orphan")
    )
    user = db.relationship("User", backref="watched_posts")


class PostView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    ip_address = db.Column(db.String(45))
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship("Post", backref="views")


class PostMetadata(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    key = db.Column(db.String(50), nullable=False)
    value = db.Column(db.JSON, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("post_id", "key", name="uix_post_metadata_key"),
    )

    post = db.relationship(
        "Post", backref=db.backref("metadata", cascade="all, delete-orphan")
    )


class UserPostMetadata(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    key = db.Column(db.String(50), nullable=False)
    value = db.Column(db.JSON, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "post_id", "user_id", "key", name="uix_post_user_metadata_key"
        ),
    )

    post = db.relationship("Post", backref="user_metadata")
    user = db.relationship("User")


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    message = db.Column(db.String(200), nullable=False)
    link = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref="notifications")


class RequestedPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    admin_comment = db.Column(db.String(200), default="")

    requester = db.relationship("User", backref="requested_posts")


class Redirect(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    old_path = db.Column(db.String(200), nullable=False)
    new_path = db.Column(db.String(200), nullable=False)
    language = db.Column(db.String(8), nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "old_path", "language", name="uix_redirect_oldpath_language"
        ),
    )


class Setting(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, nullable=True)


class PostCitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    citation_part = db.Column(db.JSON, nullable=False)
    citation_text = db.Column(db.Text, nullable=False)
    context = db.Column(db.Text)
    doi = db.Column(db.String, nullable=True)
    bibtex_raw = db.Column(db.Text, nullable=False)
    bibtex_fields = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship(
        "Post", backref=db.backref("citations", cascade="all, delete-orphan")
    )
    user = db.relationship("User")


class UserPostCitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    citation_part = db.Column(db.JSON, nullable=False)
    citation_text = db.Column(db.Text, nullable=False)
    context = db.Column(db.Text)
    doi = db.Column(db.String, nullable=True)
    bibtex_raw = db.Column(db.Text, nullable=False)
    bibtex_fields = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship("Post", backref="user_citations")
    user = db.relationship("User")


db.Index("ix_post_metadata_key_post", PostMetadata.key, PostMetadata.post_id)
db.Index(
    "ix_user_post_metadata_key_post_user",
    UserPostMetadata.key,
    UserPostMetadata.post_id,
    UserPostMetadata.user_id,
)
db.Index("ix_post_citation_post_id", PostCitation.post_id)
db.Index("ix_post_citation_user_id", PostCitation.user_id)
db.Index("ix_user_post_citation_post_id", UserPostCitation.post_id)
db.Index("ix_user_post_citation_user_id", UserPostCitation.user_id)
db.Index(
    "uq_post_citation_doi",
    PostCitation.post_id,
    PostCitation.doi,
    unique=True,
    sqlite_where=db.text("doi IS NOT NULL"),
)
db.Index(
    "uq_post_citation_text",
    PostCitation.post_id,
    PostCitation.citation_text,
    unique=True,
    sqlite_where=db.text("doi IS NULL"),
)
db.Index(
    "uq_user_post_citation_doi",
    UserPostCitation.post_id,
    UserPostCitation.doi,
    unique=True,
    sqlite_where=db.text("doi IS NOT NULL"),
)
db.Index(
    "uq_user_post_citation_text",
    UserPostCitation.post_id,
    UserPostCitation.citation_text,
    unique=True,
    sqlite_where=db.text("doi IS NULL"),
)


class Revision(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    path = db.Column(db.String(200), nullable=False)
    language = db.Column(db.String(8), nullable=False, default="en")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    comment = db.Column(db.String(200), default="")
    byte_change = db.Column(db.Integer, default=0)

    user = db.relationship("User")
    post = db.relationship("Post", backref="revisions")


__all__ = [
    "db",
    "POST_EDITOR_ROLES",
    "User",
    "Post",
    "Tag",
    "PostTag",
    "PostLink",
    "PostWatch",
    "PostMetadata",
    "UserPostMetadata",
    "Notification",
    "RequestedPost",
    "Redirect",
    "Setting",
    "PostCitation",
    "UserPostCitation",
    "Revision",
]

