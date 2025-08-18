from flask import Flask, request, jsonify
import sqlite3
import threading

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
    return app.db.conn

@app.route('/index', methods=['POST'])
def index_document():
    data = request.get_json(force=True)
    doc_id = data.get('id')
    title = data.get('title', '')
    body = data.get('body', '')
    if doc_id is None:
        return jsonify({'error': 'id is required'}), 400
    conn = get_db()
    with conn:
        conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
        conn.execute(
            'INSERT INTO documents (id, title, body) VALUES (?, ?, ?)',
            (doc_id, title, body)
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
    if not query:
        return jsonify({'error': 'q parameter is required'}), 400
    conn = get_db()
    cur = conn.execute('SELECT id FROM documents WHERE documents MATCH ?', (query,))
    results = [row[0] for row in cur.fetchall()]
    return jsonify(results)

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run()
