# Spacetime

[![License](https://img.shields.io/github/license/flyingtext/spacetime?color=blue)](https://github.com/flyingtext/spacetime/blob/main/LICENSE) 
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/flyingtext/spacetime?display_name=tag&color=brightgreen)](https://github.com/flyingtext/spacetime/releases) 
[![Python](https://img.shields.io/badge/python-3.9%2B-%233776AB?logo=python&logoColor=white)](https://www.python.org) 
[![Flask](https://img.shields.io/badge/Flask-2.3-%23000?logo=flask&logoColor=white)](https://palletsprojects.com/p/flask/) 
[![SQLite](https://img.shields.io/badge/SQLite-3.x-%2307405e?logo=sqlite&logoColor=white)](https://www.sqlite.org) 
[![GitHub Actions](https://img.shields.io/github/actions/workflow/status/flyingtext/spacetime/python-app.yml?branch=main&logo=github&label=CI)](https://github.com/flyingtext/spacetime/actions) 
[![Coverage Status](https://img.shields.io/codecov/c/gh/flyingtext/spacetime?logo=codecov&label=coverage)](https://app.codecov.io/gh/flyingtext/spacetime) 
[![CodeQL](https://img.shields.io/github/workflow/status/flyingtext/spacetime/CodeQL?label=CodeQL&logo=github)](https://github.com/flyingtext/spacetime/security/code-scanning) 
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/flyingtext/spacetime/badge)](https://securityscorecards.dev/viewer/?uri=github.com/flyingtext/spacetime) 
[![Stars](https://img.shields.io/github/stars/flyingtext/spacetime?style=flat-square)](https://github.com/flyingtext/spacetime/stargazers) 
[![Forks](https://img.shields.io/github/forks/flyingtext/spacetime?style=flat-square)](https://github.com/flyingtext/spacetime/network/members) 
[![Issues](https://img.shields.io/github/issues/flyingtext/spacetime?style=flat-square)](https://github.com/flyingtext/spacetime/issues) 
[![Pull Requests](https://img.shields.io/github/issues-pr/flyingtext/spacetime?style=flat-square)](https://github.com/flyingtext/spacetime/pulls)
[![Zenodo](https://zenodo.org/badge/DOI/10.5281/zenodo.16919675.svg)](https://doi.org/10.5281/zenodo.16919675)


Simple wiki-style bulletin board built with Flask and SQLite. Supports user registration and login, Markdown posts, global tagging, hierarchical paths, and multilingual linking with per-user permissions.

## Features
- User registration and login with role support (admin/user)
- Create and edit Markdown posts
- Global tag management; posts can be filtered by tags
- Hierarchical document paths using `/<lang>/<path>` addresses (legacy `/docs/<lang>/<path>` supported)
- Link posts written in different languages that share the same path
- Permissions: authors or admins can edit posts

## Installation
Use the provided script to install all dependencies and download the complete
NLTK dataset:

```bash
./install.sh
```

If you prefer to perform the steps manually, install the required packages and
download the NLTK resources yourself:

```bash
python -m pip install -r requirements.txt
python -m nltk.downloader all
```

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for additional details.

The application uses the Crossref API through the `habanero` library, so network
access is required when querying Crossref.

## Dependencies

A summary of third-party libraries used in Spacetime is available in [docs/LIBRARIES.md](docs/LIBRARIES.md).

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

## Testing

Run the test suite with [pytest](https://docs.pytest.org/):

```bash
pytest
```

## Development

For instructions on setting up a development environment and contributing to the
project, see the [development guide](docs/DEVELOPMENT.md).
