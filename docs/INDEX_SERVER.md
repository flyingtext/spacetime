# Index Server

The index server (`index_server.py`) provides a small HTTP service for full-text
search and geographic lookups. It uses [Flask](https://flask.palletsprojects.com/)
and a SQLite [FTS5](https://sqlite.org/fts5.html) virtual table together with an
R-tree for location indexing.

## Database

A single SQLite database file named `search.db` sits alongside the server. When
the server starts it ensures the following tables exist:

- `documents` – FTS5 table with columns `id`, `title`, `body`, `metadata`
- `tags` – table linking document ids to tags
- `locations` – table storing `id`, `lat`, and `lon`
- `locations_rtree` – R-tree virtual table on latitude/longitude for fast range queries

Connections are stored in a thread-local object so that each request handler can
safely reuse a connection. Each connection is created with
`check_same_thread=False` so multiple threads may interact with the database.

## HTTP API

### `POST /index`

Index or update a document. The request body must be JSON with at least the
field `id` and optional `title`, `body`, `lat`, `lon`, `metadata`, and `tags`
fields:

```json
{
  "id": "123",
  "title": "Example",
  "body": "Document text",
  "lat": 10.0,
  "lon": 20.0
}
```

If a document with the same `id` already exists it is replaced. The response is
`{"status": "indexed"}` on success.

### `DELETE /index/<id>`

Remove the document identified by `id` from the database. The response is
`{"status": "deleted"}` even if the document was not present.

### `GET /search`

Search for documents. Optional query parameters include:

- `q` – FTS5 search query
- `metadata.KEY` – filter by metadata value
- `lat`, `lon`, `radius` – return only documents whose stored location falls
  within `radius` kilometers of the provided latitude and longitude

The response is a JSON array of matching document identifiers:

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
  -d '{"id":"1","title":"Hello","body":"Hello world","lat":10,"lon":10}' \
  http://localhost:8000/index

# full-text search
curl "http://localhost:8000/search?q=hello"

# location search within 500km of 10,10
curl "http://localhost:8000/search?lat=10&lon=10&radius=500"
```

