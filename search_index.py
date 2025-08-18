from __future__ import annotations

import os
from typing import Any

import requests


def send_to_index(post: "Post") -> None:
    """Send a document to the external index server."""
    index_url = os.getenv("INDEX_SERVER_URL")
    if not index_url:
        return
    try:
        resp = requests.post(
            f"{index_url}/index",
            json={
                "id": post.id,
                "title": post.title,
                "body": post.body,
                "lat": post.latitude,
                "lon": post.longitude,
            },
        )
        resp.raise_for_status()
    except requests.RequestException:
        pass


def remove_from_index(post_id: int) -> None:
    """Remove a document from the external index server."""
    index_url = os.getenv("INDEX_SERVER_URL")
    if not index_url:
        return
    try:
        resp = requests.delete(f"{index_url}/index/{post_id}")
        resp.raise_for_status()
    except requests.RequestException:
        pass

