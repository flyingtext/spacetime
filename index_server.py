from flask import Flask, request, jsonify
import sqlite3
import threading
import math

app = Flask(__name__)

def get_db():
    # Lazily create a thread-local connection
    if not hasattr(app, 'db'):  # but thread safe? We can store thread-local connections
        app.db = threading.local()
    if getattr(app.db, 'conn', None) is None:
        app.db.conn = sqlite3.connect('search.db', check_same_thread=False)
        app.db.conn.execute(
            'CREATE VIRTUAL TABLE IF NOT EXISTS documents '
            'USING fts5(id, title, body)'
        )
        app.db.conn.execute(
            'CREATE TABLE IF NOT EXISTS locations '
            '(id TEXT PRIMARY KEY, lat REAL, lon REAL)'
        )
        app.db.conn.execute(
            'CREATE VIRTUAL TABLE IF NOT EXISTS locations_rtree '
            'USING rtree(id, minLat, maxLat, minLon, maxLon)'
        )
    return app.db.conn

@app.route('/index', methods=['POST'])
def index_document():
    data = request.get_json(force=True)
    doc_id = data.get('id')
    title = data.get('title', '')
    body = data.get('body', '')
    lat = data.get('lat')
    lon = data.get('lon')
    if doc_id is None:
        return jsonify({'error': 'id is required'}), 400
    conn = get_db()
    with conn:
        conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
        conn.execute('DELETE FROM locations WHERE id = ?', (doc_id,))
        conn.execute('DELETE FROM locations_rtree WHERE id = ?', (doc_id,))
        conn.execute(
            'INSERT INTO documents (id, title, body) VALUES (?, ?, ?)',
            (doc_id, title, body)
        )
        if lat is not None and lon is not None:
            conn.execute(
                'INSERT INTO locations (id, lat, lon) VALUES (?, ?, ?)',
                (doc_id, lat, lon)
            )
            conn.execute(
                'INSERT INTO locations_rtree (id, minLat, maxLat, minLon, maxLon) '
                'VALUES (?, ?, ?, ?, ?)',
                (doc_id, lat, lat, lon, lon)
            )
    return jsonify({'status': 'indexed'})

@app.route('/index/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    conn = get_db()
    with conn:
        conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
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

    if query:
        cur = conn.execute('SELECT id FROM documents WHERE documents MATCH ?', (query,))
    else:
        cur = conn.execute('SELECT id FROM documents')
    fts_ids = {str(row[0]) for row in cur.fetchall()}

    if lat is not None and lon is not None and radius is not None:
        dlat = radius / 111.0
        dlon = radius / (111.0 * math.cos(math.radians(lat))) if math.cos(math.radians(lat)) != 0 else 180.0
        min_lat, max_lat = lat - dlat, lat + dlat
        min_lon, max_lon = lon - dlon, lon + dlon
        cur = conn.execute(
            'SELECT id FROM locations_rtree WHERE maxLat >= ? AND minLat <= ? '
            'AND maxLon >= ? AND minLon <= ?',
            (min_lat, max_lat, min_lon, max_lon),
        )
        loc_ids = {str(row[0]) for row in cur.fetchall()}
    else:
        cur = conn.execute('SELECT id FROM locations')
        loc_ids = {str(row[0]) for row in cur.fetchall()}

    results = list(fts_ids & loc_ids)
    return jsonify(results)

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run()
