# Wiki Board

Simple wiki-style bulletin board built with Flask and SQLite. Supports user registration and login, Markdown posts, and global tagging with per-user permissions.

## Features
- User registration and login with role support (admin/user)
- Create and edit Markdown posts
- Global tag management; posts can be filtered by tags
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
