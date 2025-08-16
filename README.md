# Wiki Board

Simple wiki-style bulletin board built with Flask and SQLite. Supports user registration and login, Markdown posts, global tagging, hierarchical paths, and multilingual linking with per-user permissions.

## Features
- User registration and login with role support (admin/user)
- Create and edit Markdown posts
- Global tag management; posts can be filtered by tags
- Hierarchical document paths using `/docs/<lang>/<path>` addresses
- Link posts written in different languages that share the same path
- Permissions: authors or admins can edit posts

## Requirements
Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage
```bash
python app.py
```
The application creates `wiki.db` SQLite database on first run.

Open browser at `http://127.0.0.1:5000/`.
