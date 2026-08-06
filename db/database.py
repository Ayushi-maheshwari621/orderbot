import sqlite3
import os
import json
from datetime import datetime

# Path to the SQLite database file
DB_PATH = os.path.join(os.path.dirname(__file__), 'orders.db')

def get_connection():
    """
    Establish and return a connection to the SQLite database.
    """
    return sqlite3.connect(DB_PATH)

def initialize_database():
    """
    Create the orders table if it doesn't already exist.
    This function should be called at application startup to ensure the DB is ready.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            items TEXT NOT NULL,
            total REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def save_order(customer_name, items, total, status="Placed"):
    """
    Save a new order into the database.
    
    Args:
        customer_name (str): Name of the customer.
        items (list/dict/str): The items ordered, will be stored as a JSON string.
        total (float): The total cost of the order.
        status (str): Current status of the order. Defaults to "Placed".
        
    Returns:
        int: The ID of the newly created order.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Ensure items is stored as a JSON string
    if not isinstance(items, str):
        items = json.dumps(items)
        
    # Use ISO format for timestamps
    created_at = datetime.now().isoformat()
    cursor.execute('''
        INSERT INTO orders (customer_name, items, total, status, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (customer_name, items, total, status, created_at))
    
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return order_id

def get_orders():
    """
    Retrieve all orders from the database.
    
    Returns:
        list of dict: A list where each element is a dictionary representing an order.
    """
    conn = get_connection()
    # Configure connection to return rows as dictionaries
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM orders ORDER BY created_at DESC')
    rows = cursor.fetchall()
    
    orders = []
    for row in rows:
        order = dict(row)
        # Attempt to parse items back into a Python object if possible
        try:
            order['items'] = json.loads(order['items'])
        except (json.JSONDecodeError, TypeError):
            pass  # Keep as string if it wasn't valid JSON
        orders.append(order)
        
    conn.close()
    return orders
initialize_database()
