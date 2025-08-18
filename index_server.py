from flask import Flask, request, jsonify
import sqlite3
import threading
import json
import math

app = Flask(__name__)

def get_db():
    # Lazily create a thread-local connection
    if not hasattr(app, 'db'):  # but thread safe? We can store thread-local connections
        app.db = threading.local()
    if getattr(app.db, 'conn', None) is None:
        app.db.conn = sqlite3.connect('search.db', check_same_thread=False)
        # Expand the FTS5 table with an extra column for metadata and create a
        # companion table to store tags for each document.
        app.db.conn.execute(
            'CREATE VIRTUAL TABLE IF NOT EXISTS documents '
            'USING fts5(id, title, body, metadata)'
        )
        app.db.conn.execute(
            'CREATE TABLE IF NOT EXISTS tags (doc_id TEXT, tag TEXT)'
        )
        app.db.conn.execute(
            'CREATE TABLE IF NOT EXISTS locations (id INTEGER PRIMARY KEY, lat REAL, lon REAL)'
        )
        app.db.conn.execute(
            'CREATE VIRTUAL TABLE IF NOT EXISTS locations_rtree '
            'USING rtree(id, min_lat, max_lat, min_lon, max_lon)'
        )
    return app.db.conn

@app.route('/index', methods=['POST'])
def index_document():
    data = request.get_json(force=True)
    doc_id = data.get('id')
    title = data.get('title', '')
    body = data.get('body', '')
    metadata = data.get('metadata', {})
    tags = data.get('tags', [])
    lat = data.get('lat')
    lon = data.get('lon')
    if doc_id is None:
        return jsonify({'error': 'id is required'}), 400

    doc_id_int = int(doc_id)
    conn = get_db()
    with conn:
        conn.execute('DELETE FROM documents WHERE id = ?', (doc_id_int,))
        conn.execute('DELETE FROM tags WHERE doc_id = ?', (doc_id_int,))
        conn.execute('DELETE FROM locations WHERE id = ?', (doc_id_int,))
        conn.execute('DELETE FROM locations_rtree WHERE id = ?', (doc_id_int,))
        conn.execute(
            'INSERT INTO documents (id, title, body, metadata) VALUES (?, ?, ?, ?)',
            (doc_id_int, title, body, json.dumps(metadata))
        )
        for tag in tags:
            conn.execute(
                'INSERT INTO tags (doc_id, tag) VALUES (?, ?)',
                (doc_id_int, tag)
            )
        if lat is not None and lon is not None:
            conn.execute(
                'INSERT INTO locations (id, lat, lon) VALUES (?, ?, ?)',
                (doc_id_int, lat, lon)
            )
            conn.execute(
                'INSERT INTO locations_rtree (id, min_lat, max_lat, min_lon, max_lon) VALUES (?, ?, ?, ?, ?)',
                (doc_id_int, lat, lat, lon, lon)
            )
    return jsonify({'status': 'indexed'})

@app.route('/index/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    conn = get_db()
    with conn:
        conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
        conn.execute('DELETE FROM tags WHERE doc_id = ?', (doc_id,))
        conn.execute('DELETE FROM locations WHERE id = ?', (doc_id,))
        conn.execute('DELETE FROM locations_rtree WHERE id = ?', (doc_id,))
    return jsonify({'status': 'deleted'})

@app.route('/search')
def search():
    query = request.args.get('q')
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    radius = request.args.get('radius', type=float)
    conn = get_db()

    # Extract metadata filters from query parameters of the form
    # "metadata.key=value".
    meta_filters = {
        k.split('.', 1)[1]: v
        for k, v in request.args.items()
        if k.startswith('metadata.')
    }

    if query:
        cur = conn.execute(
            'SELECT id, metadata FROM documents WHERE documents MATCH ?',
            (query,),
        )
    else:
        cur = conn.execute('SELECT id, metadata FROM documents')

    rows = cur.fetchall()

    if meta_filters:
        results = []
        for doc_id, meta_json in rows:
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except json.JSONDecodeError:
                meta = {}
            if all(str(meta.get(k)) == v for k, v in meta_filters.items()):
                results.append(str(doc_id))
    else:
        results = [str(row[0]) for row in rows]

    if lat is not None and lon is not None and radius is not None:
        lat_deg = radius / 111.0
        lon_deg = radius / (111.0 * max(math.cos(math.radians(lat)), 1e-8))
        min_lat = lat - lat_deg
        max_lat = lat + lat_deg
        min_lon = lon - lon_deg
        max_lon = lon + lon_deg
        cur = conn.execute(
            'SELECT id FROM locations_rtree WHERE min_lat >= ? AND max_lat <= ? AND min_lon >= ? AND max_lon <= ?',
            (min_lat, max_lat, min_lon, max_lon),
        )
        loc_ids = {str(row[0]) for row in cur.fetchall()}
        results = [doc_id for doc_id in results if doc_id in loc_ids]

    return jsonify(results)

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run()
