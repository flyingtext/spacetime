# Spacetime

Simple wiki-style bulletin board built with Flask and SQLite. Supports user registration and login, Markdown posts, global tagging, hierarchical paths, and multilingual linking with per-user permissions.

## Features
- User registration and login with role support (admin/user)
- Create and edit Markdown posts
- Global tag management; posts can be filtered by tags
- Hierarchical document paths using `/<lang>/<path>` addresses (legacy `/docs/<lang>/<path>` supported)
- Link posts written in different languages that share the same path
- Permissions: authors or admins can edit posts

## Installation
Install dependencies:
```bash
pip install -r requirements.txt
```

The application uses the Crossref API through the `habanero` library, so network
access is required when querying Crossref.

## Configuration
Create a `.env` file in the project root to configure runtime settings. The
following variables are supported:

- `SECRET_KEY` – Flask secret key used for session signing.
- `SQLALCHEMY_DATABASE_URI` – database connection string.
- `BABEL_DEFAULT_LOCALE` – default locale for translations.
- `LANGUAGES` – comma-separated list of supported languages.
- `BABEL_TRANSLATION_DIRECTORIES` – path to translation files.
- `HOST` – hostname or IP address for the server.
- `PORT` – port for the server.
- `SSL_CERT_FILE` – path to a PEM-formatted certificate file to enable HTTPS.
- `SSL_KEY_FILE` – path to the private key file if not included in the certificate.

Example `.env`:

```ini
SECRET_KEY=dev-secret
SQLALCHEMY_DATABASE_URI=sqlite:///wiki.db
BABEL_DEFAULT_LOCALE=en
LANGUAGES=en,es
BABEL_TRANSLATION_DIRECTORIES=translations
HOST=127.0.0.1
PORT=5000
SSL_CERT_FILE=cert.pem
SSL_KEY_FILE=key.pem
```

## Usage
```bash
HOST=127.0.0.1 PORT=5000 SSL_CERT_FILE=cert.pem SSL_KEY_FILE=key.pem python app.py
```
The application creates `wiki.db` SQLite database on first run.

Open browser at `http://${HOST}:${PORT}/` or `https://${HOST}:${PORT}/` when SSL is configured.

## API

See [API.md](API.md) for a list of HTTP endpoints.

## Search Index Service

A lightweight full-text search service is provided in `index_server.py`. It
uses SQLite FTS5 and exposes several HTTP endpoints:

- `POST /index` – index or update a document using JSON payload
  `{id, title, body}`.
- `DELETE /index/<id>` – remove a document from the index.
- `GET /search?q=…` – return a JSON array of matching document identifiers.
- `GET /health` – basic health check endpoint.

Run the service directly with:

```bash
python index_server.py
```

For production, multiple instances can be launched behind a load balancer.
Because the service is stateless aside from the SQLite database file, each
instance can point to the same database on shared storage. Example using
`gunicorn` with four workers:

```bash
gunicorn -w 4 -b 0.0.0.0:8000 index_server:app
```

Use a load balancer such as Nginx or HAProxy to distribute requests across
instances running on different ports or hosts.

## Testing

Run the test suite with [pytest](https://docs.pytest.org/):

```bash
pytest
```

## Development

For instructions on setting up a development environment and contributing to the
project, see the [development guide](docs/DEVELOPMENT.md).
