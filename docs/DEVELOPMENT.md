# Development Guide

This guide describes how to set up a local development environment for **Spacetime**, run the application, and execute the test suite.

## Prerequisites

- Python 3.11 or later
- [pip](https://pip.pypa.io/)
- Optional but recommended: [virtualenv](https://virtualenv.pypa.io/)

## Environment Setup

1. **Clone the repository**
   ```bash
   git clone https://example.com/spacetime.git
   cd spacetime
   ```
2. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Runtime settings are read from a `.env` file in the project root. At a minimum, define a `SECRET_KEY` and the database URL:

```ini
SECRET_KEY=dev-secret
SQLALCHEMY_DATABASE_URI=sqlite:///wiki.db
BABEL_DEFAULT_LOCALE=en
LANGUAGES=en,es
BABEL_TRANSLATION_DIRECTORIES=translations
HOST=127.0.0.1
PORT=5000
```

## Running the Application

Start the development server with:

```bash
HOST=127.0.0.1 PORT=5000 python app.py
```

The first run creates a `wiki.db` SQLite database. Navigate to `http://HOST:PORT/` to view the site.

## Tests

The project uses [pytest](https://docs.pytest.org/). Run the test suite with:

```bash
pytest
```

## Translations

Spacetime uses Flask-Babel for translations. Translation files live in the `translations/` directory and are managed via [Babel](https://babel.pocoo.org/).

To extract messages and update translation catalogs:

```bash
pybabel extract -F babel.cfg -o messages.pot .
pybabel update -i messages.pot -d translations
```

## Code Style

Follow [PEP 8](https://peps.python.org/pep-0008/) guidelines. Formatting tools such as [black](https://black.readthedocs.io/) and [flake8](https://flake8.pycqa.org/) can help maintain consistency.

## Contributing

1. Fork the repository and create your feature branch.
2. Commit your changes with descriptive messages.
3. Ensure all tests pass.
4. Submit a pull request.

