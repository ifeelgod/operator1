import sqlite3
import json
import os
from sentence_transformers import SentenceTransformer
import numpy as np

# Use an env variable for DB path to allow Railway persistent volumes
DB_PATH = os.getenv("DB_PATH", "operator.db")

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cursor = self.conn.cursor()
        self.setup()
        
        # Initialize embedding model (downloads on first run)
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')

    def setup(self):
        # Create conversations table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                user_id TEXT PRIMARY KEY,
                history TEXT
            )
        ''')
        
        # Create vault table
        # We store embeddings as JSON strings or raw bytes. JSON is easier for basic setup.
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS vault (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT,
                embedding TEXT,
                source TEXT
            )
        ''')
        self.conn.commit()

    def get_history(self, user_id):
        self.cursor.execute('SELECT history FROM conversations WHERE user_id = ?', (str(user_id),))
        row = self.cursor.fetchone()
        if row:
            return json.loads(row[0])
        return []

    def update_history(self, user_id, history):
        self.cursor.execute('''
            INSERT INTO conversations (user_id, history)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET history=excluded.history
        ''', (str(user_id), json.dumps(history)))
        self.conn.commit()

    def add_to_vault(self, content, source):
        embedding = self.encoder.encode(content).tolist()
        self.cursor.execute('''
            INSERT INTO vault (content, embedding, source)
            VALUES (?, ?, ?)
        ''', (content, json.dumps(embedding), source))
        self.conn.commit()

    def cosine_similarity(self, a, b):
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    def search_vault(self, query, top_k=3):
        query_embedding = self.encoder.encode(query)
        self.cursor.execute('SELECT content, embedding, source FROM vault')
        
        results = []
        for row in self.cursor.fetchall():
            content, emb_str, source = row
            doc_embedding = np.array(json.loads(emb_str))
            sim = self.cosine_similarity(query_embedding, doc_embedding)
            results.append((sim, content, source))
            
        # Sort by similarity descending
        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]

db = Database()
