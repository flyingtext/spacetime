"""API blueprint for spacetime.

Routes that expose JSON endpoints are collected here to keep ``app.py``
focused on application setup and HTML views.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, current_app, url_for
from flask_login import current_user, login_required
from flask_babel import _
from langdetect import detect, LangDetectException

from models import (
    db,
    Post,
    Tag,
    PostMetadata,
    Revision,
    PostCitation,
    UserPostCitation,
    PostWatch,
    Notification,
)


api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/posts", methods=["GET"])
def search_posts():
    """Search posts with optional full-text query and pagination."""
    from sqlalchemy import text

    q = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int, default=0)

    query = Post.query
    if q:
        ids = [
            row[0]
            for row in db.session.execute(
                text("SELECT rowid FROM post_fts WHERE post_fts MATCH :q"),
                {"q": q},
            )
        ]
        query = query.filter(Post.id.in_(ids)) if ids else query.filter(False)

    total = query.count()
    query = query.order_by(Post.id.desc())
    if offset:
        query = query.offset(offset)
    if limit and limit > 0:
        posts = query.limit(limit).all()
    else:
        posts = query.all()

    data = [
        {"id": p.id, "path": p.path, "language": p.language, "title": p.title}
        for p in posts
    ]
    return jsonify({"posts": data, "total": total})


@api_bp.route("/posts", methods=["POST"])
@login_required
def create_post():
    """Create a new post via the API."""
    from app import geocode_address, generate_unique_path, update_post_links

    if not current_user.can_edit_posts():
        return jsonify({"error": "forbidden"}), 403
    if not request.is_json:
        return jsonify({"error": "invalid JSON"}), 400
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    path = (data.get("path") or "").strip()
    language = (data.get("language") or "").strip()
    address = (data.get("address") or "").strip()
    lat_val = data.get("lat")
    lon_val = data.get("lon")
    lat = lon = None
    if address and lat_val is None and lon_val is None:
        coords = geocode_address(address)
        if not coords:
            return jsonify({"error": "invalid address"}), 400
        lat_val, lon_val = coords
    if lat_val is not None and lon_val is not None:
        try:
            lat = float(lat_val)
            lon = float(lon_val)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid coordinates"}), 400
    elif lat_val is not None or lon_val is not None:
        return jsonify({"error": "lat and lon required"}), 400
    if not title or not body:
        return jsonify({"error": "title and body required"}), 400
    if language not in current_app.config["LANGUAGES"]:
        try:
            language = detect(body)
        except LangDetectException:
            language = current_app.config["BABEL_DEFAULT_LOCALE"]
        if language not in current_app.config["LANGUAGES"]:
            language = current_app.config["BABEL_DEFAULT_LOCALE"]
    if not path or Post.query.filter_by(path=path, language=language).first():
        path = generate_unique_path(title, language)
    tags_input = data.get("tags", [])
    if isinstance(tags_input, str):
        tag_names = [t.strip() for t in tags_input.split(",") if t.strip()]
    else:
        tag_names = [
            t.strip() for t in tags_input if isinstance(t, str) and t.strip()
        ]
    tags = []
    for name in dict.fromkeys(tag_names):
        tag = Tag.query.filter_by(name=name).first()
        if not tag:
            tag = Tag(name=name)
            db.session.add(tag)
        tags.append(tag)
    post = Post(
        title=title,
        body=body,
        path=path,
        language=language,
        author=current_user,
        tags=tags,
    )
    db.session.add(post)
    if lat is not None and lon is not None:
        post.latitude = lat
        post.longitude = lon
        db.session.add(PostMetadata(post=post, key="lat", value=str(lat)))
        db.session.add(PostMetadata(post=post, key="lon", value=str(lon)))
    db.session.flush()
    update_post_links(post)
    comment = (data.get("comment") or "").strip()
    rev = Revision(
        post=post,
        user=current_user,
        title=title,
        body=body,
        path=path,
        language=language,
        comment=comment,
        byte_change=len(body),
    )
    db.session.add(rev)
    db.session.commit()
    return (
        jsonify(
            {
                "id": post.id,
                "path": post.path,
                "language": post.language,
                "title": post.title,
            }
        ),
        201,
    )


@api_bp.route("/posts/<int:post_id>", methods=["GET"])
def get_post(post_id: int):
    """Return a post's content and metadata."""
    post = Post.query.get_or_404(post_id)
    metadata = {m.key: m.value for m in post.metadata}
    return jsonify(
        {
            "id": post.id,
            "path": post.path,
            "language": post.language,
            "title": post.title,
            "body": post.body,
            "metadata": metadata,
        }
    )


@api_bp.route("/posts/<int:post_id>", methods=["PUT"])
@login_required
def update_post(post_id: int):
    """Update a post's content and metadata."""
    from app import generate_unique_path, update_post_links

    post = Post.query.get_or_404(post_id)
    if not current_user.can_edit_posts():
        return jsonify({"error": "forbidden"}), 403
    if not request.is_json:
        return jsonify({"error": "invalid JSON"}), 400
    data = request.get_json() or {}

    title = (data.get("title") or post.title).strip()
    body = (data.get("body") or post.body)
    path = (data.get("path") or post.path).strip()
    language = (data.get("language") or post.language).strip()
    comment = (data.get("comment") or "").strip()

    if not title or not body:
        return jsonify({"error": "title and body required"}), 400

    existing = (
        Post.query.filter_by(path=path, language=language)
        .filter(Post.id != post.id)
        .first()
    )
    if existing:
        return jsonify({"error": "path already exists"}), 400

    old_body = post.body
    rev = Revision(
        post=post,
        user=current_user,
        title=post.title,
        body=old_body,
        path=post.path,
        language=post.language,
        comment=comment,
    )
    db.session.add(rev)

    post.title = title
    post.body = body
    post.path = path or generate_unique_path(title, language)
    post.language = language

    meta = data.get("metadata")
    if isinstance(meta, dict):
        current_views = PostMetadata.query.filter_by(post_id=post.id, key="views").first()
        PostMetadata.query.filter(
            PostMetadata.post_id == post.id, PostMetadata.key != "views"
        ).delete(synchronize_session=False)
        for key, value in meta.items():
            if key in {"lat", "lon"}:
                value = str(value)
            db.session.add(PostMetadata(post=post, key=key, value=value))
        if current_views:
            db.session.add(current_views)
        lat_val = meta.get("lat")
        lon_val = meta.get("lon")
        if lat_val is not None and lon_val is not None:
            try:
                post.latitude = float(lat_val)
                post.longitude = float(lon_val)
            except (TypeError, ValueError):
                post.latitude = post.longitude = None
        else:
            post.latitude = post.longitude = None

    update_post_links(post)
    rev.byte_change = len(post.body) - len(old_body)
    db.session.commit()
    return jsonify(
        {
            "id": post.id,
            "path": post.path,
            "language": post.language,
            "title": post.title,
        }
    )


@api_bp.route("/posts/<int:post_id>/citation", methods=["POST"])
@login_required
def add_url_citation(post_id: int):
    from app import is_url

    post = Post.query.get_or_404(post_id)
    if not request.is_json:
        return jsonify({"error": "invalid JSON"}), 400
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    context = (data.get("context") or "").strip()
    if not url or not is_url(url):
        return jsonify({"error": "valid URL required"}), 400
    existing = PostCitation.query.filter_by(
        post_id=post.id, citation_text=url
    ).first()
    if not existing:
        existing = UserPostCitation.query.filter_by(
            post_id=post.id, citation_text=url
        ).first()
    if existing:
        return jsonify({"error": "Citation with this URL already exists."}), 400
    entry = {"url": url}
    if current_user.id == post.author_id or current_user.is_admin():
        citation = PostCitation(
            post=post,
            user=current_user,
            citation_part=entry,
            citation_text=url,
            context=context,
            doi=None,
            bibtex_raw=url,
            bibtex_fields=entry,
        )
    else:
        citation = UserPostCitation(
            post=post,
            user=current_user,
            citation_part=entry,
            citation_text=url,
            context=context,
            doi=None,
            bibtex_raw=url,
            bibtex_fields=entry,
        )
    db.session.add(citation)
    watcher_ids = {
        w.user_id for w in PostWatch.query.filter_by(post_id=post.id).all()
    }
    watcher_ids.add(post.author_id)
    link = url_for("post_detail", post_id=post.id)
    for uid in watcher_ids:
        if uid != current_user.id:
            msg = _("Citation added to \"%(title)s\".", title=post.title)
            db.session.add(Notification(user_id=uid, message=msg, link=link))
    db.session.commit()
    return jsonify({"id": citation.id, "url": url}), 201


__all__ = ["api_bp"]

