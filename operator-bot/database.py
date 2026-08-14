import os
import sqlite3
import json
import numpy as np
from datetime import datetime
from sentence_transformers import SentenceTransformer

# Initialize embedding model (downloads locally on first run)
print("Loading embedding model...")
embedder = SentenceTransformer('all-MiniLM-L6-v2')
print("Model loaded.")

DB_PATH = os.getenv("DB_PATH", "operator.db")

def init_db():
    # Ensure directory exists if not running locally
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table for conversational history
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Table for semantic vault
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vault (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            text_chunk TEXT NOT NULL,
            embedding BLOB NOT NULL,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def add_message(user_id: str, role: str, content: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content)
    )
    conn.commit()
    conn.close()

def get_conversation_history(user_id: str, limit: int = 10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, content FROM messages WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
        (user_id, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    
    # Reverse to get chronological order
    history = [{"role": row[0], "content": row[1]} for row in reversed(rows)]
    return history

def add_to_vault(source_name: str, text: str):
    """Chunk text and save to vault with embeddings."""
    # Simple chunking by paragraphs (can be improved based on file type)
    chunks = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 50]
    if not chunks:
        chunks = [text.strip()]
        
    embeddings = embedder.encode(chunks)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for chunk, emb in zip(chunks, embeddings):
        # Store embedding as binary numpy array
        emb_bytes = emb.astype(np.float32).tobytes()
        cursor.execute(
            "INSERT INTO vault (source_name, text_chunk, embedding) VALUES (?, ?, ?)",
            (source_name, chunk, emb_bytes)
        )
        
    conn.commit()
    conn.close()
    return len(chunks)

def search_vault(query: str, top_k: int = 3):
    """Search the vault for relevant chunks."""
    query_emb = embedder.encode(query).astype(np.float32)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT source_name, text_chunk, embedding FROM vault")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return []
        
    results = []
    for row in rows:
        source_name, chunk, emb_bytes = row
        doc_emb = np.frombuffer(emb_bytes, dtype=np.float32)
        score = cosine_similarity(query_emb, doc_emb)
        results.append({"score": float(score), "chunk": chunk, "source": source_name})
        
    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]

# Initialize on load
init_db()
