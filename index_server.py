from flask import Flask, request, jsonify
import sqlite3
import threading
import json

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
    return app.db.conn

@app.route('/index', methods=['POST'])
def index_document():
    data = request.get_json(force=True)
    doc_id = data.get('id')
    title = data.get('title', '')
    body = data.get('body', '')
    metadata = data.get('metadata', {})
    tags = data.get('tags', [])
    if doc_id is None:
        return jsonify({'error': 'id is required'}), 400
    conn = get_db()
    with conn:
        conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
        conn.execute('DELETE FROM tags WHERE doc_id = ?', (doc_id,))
        conn.execute(
            'INSERT INTO documents (id, title, body, metadata) VALUES (?, ?, ?, ?)',
            (doc_id, title, body, json.dumps(metadata))
        )
        for tag in tags:
            conn.execute(
                'INSERT INTO tags (doc_id, tag) VALUES (?, ?)',
                (doc_id, tag)
            )
    return jsonify({'status': 'indexed'})

@app.route('/index/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    conn = get_db()
    with conn:
        conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
    return jsonify({'status': 'deleted'})

@app.route('/search')
def search():
    query = request.args.get('q')
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
                results.append(doc_id)
    else:
        results = [row[0] for row in rows]

    return jsonify(results)

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run()
