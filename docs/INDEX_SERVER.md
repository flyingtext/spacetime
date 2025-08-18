# Index Server

The index server (`index_server.py`) provides a small HTTP service for full-text
search. It uses [Flask](https://flask.palletsprojects.com/) and a SQLite
[FTS5](https://sqlite.org/fts5.html) virtual table to store and query
documents.

## Database

A single SQLite database file named `search.db` sits alongside the server. When
the server starts it ensures a table called `documents` exists with the
following columns:

- `id` – unique identifier for the document (primary key)
- `title` – title text used during search
- `body` – full document body used for matching

Connections are stored in a thread-local object so that each request handler can
safely reuse a connection. Each connection is created with
`check_same_thread=False` so multiple threads may interact with the database.

## HTTP API

### `POST /index`

Index or update a document. The request body must be JSON with at least the
field `id` and optional `title` and `body` fields:

```json
{
  "id": "123",
  "title": "Example",
  "body": "Document text"
}
```

If a document with the same `id` already exists it is replaced. The response is
`{"status": "indexed"}` on success.

### `DELETE /index/<id>`

Remove the document identified by `id` from the database. The response is
`{"status": "deleted"}` even if the document was not present.

### `GET /search?q=<term>`

Search for documents containing the query term. The query string parameter `q`
is required and may contain any valid FTS5 query. The response is a JSON array
of matching document identifiers:

```json
["123", "456"]
```

### `GET /health`

Simple health check endpoint that returns `{"status": "ok"}`.

## Running the Service

Start the server directly with Python:

```bash
python index_server.py
```

For production deployments you can use `gunicorn` or another WSGI server and
run multiple worker processes:

```bash
gunicorn -w 4 -b 0.0.0.0:8000 index_server:app
```

Because the server is stateless apart from the `search.db` file, multiple
instances can share the same database by pointing to a common file location.

## Example Usage

Index a document and perform a search using `curl`:

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"id":"1","title":"Hello","body":"Hello world"}' \
  http://localhost:8000/index

curl "http://localhost:8000/search?q=hello"
```

