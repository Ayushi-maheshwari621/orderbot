import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'orders.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            items_json TEXT,
            total_price REAL,
            status TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_order(cart, total):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    created_at = datetime.utcnow().isoformat()
    cursor.execute('''
        INSERT INTO orders (items_json, total_price, status, created_at)
        VALUES (?, ?, ?, ?)
    ''', (json.dumps(cart), total, 'Pending', created_at))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id
