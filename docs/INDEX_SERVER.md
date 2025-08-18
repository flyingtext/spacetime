# Index Server

The index server (`index_server.py`) provides a small HTTP service for full-text
and basic geographic search. It uses [Flask](https://flask.palletsprojects.com/)
and a SQLite [FTS5](https://sqlite.org/fts5.html) virtual table to store and
query documents. Latitude/longitude coordinates are stored in a separate table
and indexed using an [R-tree](https://sqlite.org/rtree.html) virtual table for
efficient range queries.

## Database

A single SQLite database file named `search.db` sits alongside the server. When
the server starts it ensures the following tables exist:

- `documents` – FTS5 virtual table with columns `id`, `title`, and `body`
- `locations` – table mapping `id` to `lat` and `lon`
- `locations_rtree` – R-tree virtual table used to quickly select ids within a
  geographic bounding box

Connections are stored in a thread-local object so that each request handler can
safely reuse a connection. Each connection is created with
`check_same_thread=False` so multiple threads may interact with the database.

## HTTP API

### `POST /index`

Index or update a document. The request body must be JSON with at least the
field `id`. Optional fields `title` and `body` populate the FTS table, while
`lat` and `lon` store a geographic location:

```json
{
  "id": "123",
  "title": "Example",
  "body": "Document text",
  "lat": 51.5,
  "lon": -0.1
}
```

If a document with the same `id` already exists it is replaced. The response is
`{"status": "indexed"}` on success.

### `DELETE /index/<id>`

Remove the document identified by `id` from the database. The response is
`{"status": "deleted"}` even if the document was not present.

### `GET /search`

Search for documents. The query string may include `q` for full-text search and
`lat`, `lon`, and `radius` (in kilometers) to filter results to a geographic
area. All parameters are optional; when both sets are supplied the server
returns the intersection of the full-text and location results. The response is
a JSON array of matching document identifiers:

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

Index a document with coordinates and perform a text+location search using
`curl`:

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"id":"1","title":"Hello","body":"Hello world","lat":40.0,"lon":-74.0}' \
  http://localhost:8000/index

# Find documents matching "hello" within 5km of the given point
curl "http://localhost:8000/search?q=hello&lat=40&lon=-74&radius=5"
```

