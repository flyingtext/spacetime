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

