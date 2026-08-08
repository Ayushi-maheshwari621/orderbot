import json
import os
import sys
import sqlite3
from typing import List, Dict, Any

# Ensure we can import from db
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db.database import save_order, get_connection

# Cache the menu data at the module level
_MENU_CACHE: List[Dict[str, Any]] | None = None

def load_menu() -> List[Dict[str, Any]]:
    """
    Load the menu data from the data/menu.json file.
    Caches the data in memory after the first read to improve performance.
    
    Returns:
        List[Dict[str, Any]]: A list of dictionaries representing the menu items.
    """
    global _MENU_CACHE
    if _MENU_CACHE is not None:
        return _MENU_CACHE
        
    # Construct path relative to this script's location
    base_dir = os.path.dirname(os.path.dirname(__file__))
    menu_path = os.path.join(base_dir, 'data', 'menu.json')
    
    try:
        with open(menu_path, 'r', encoding='utf-8') as f:
            _MENU_CACHE = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Menu file not found: {menu_path}")
        
    return _MENU_CACHE

def search_menu(query: str, restaurant_id: str | None = None) -> List[Dict[str, Any]]:
    """
    Search the SQLite menu for items matching the given query case-insensitively.
    If restaurant_id is provided, only searches within that restaurant.
    Returns a limited number of items to prevent blowing up the LLM context.
    
    Args:
        query (str): The text to search for across dish name and category.
        restaurant_id (str, optional): The ID of the restaurant to filter by.
        
    Returns:
        List[Dict[str, Any]]: A list of menu items matching the query.
    """
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if restaurant_id and (not query or not query.strip()):
            cursor.execute('''
                SELECT id, restaurant_id, name, category, price, is_veg, currency 
                FROM menu_items 
                WHERE restaurant_id = ?
                LIMIT 20
            ''', (restaurant_id,))
        elif not query or not query.strip():
            return []
        else:
            search_term = f"%{query.strip()}%"
            if restaurant_id:
                cursor.execute('''
                    SELECT id, restaurant_id, name, category, price, is_veg, currency 
                    FROM menu_items 
                    WHERE restaurant_id = ? 
                    AND (name LIKE ? OR category LIKE ?)
                    LIMIT 20
                ''', (restaurant_id, search_term, search_term))
            else:
                cursor.execute('''
                    SELECT id, restaurant_id, name, category, price, is_veg, currency 
                    FROM menu_items 
                    WHERE name LIKE ? OR category LIKE ?
                    LIMIT 20
                ''', (search_term, search_term))
        
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            dish = dict(row)
            dish["available"] = True
            results.append(dish)
            
        return results
    except Exception as e:
        print(f"Database error in search_menu: {e}")
        return []

# In-memory shopping carts
# Maps session_id -> {dish_id -> quantity}
_CARTS: Dict[str, Dict[int, int]] = {}

def _get_cart(session_id: str) -> Dict[int, int]:
    if session_id not in _CARTS:
        _CARTS[session_id] = {}
    return _CARTS[session_id]

def add_to_cart(session_id: str, dish_id: int, quantity: int) -> Dict[str, Any]:
    """
    Add a specific quantity of a dish to the shopping cart.
    
    Args:
        session_id (str): The current user session ID.
        dish_id (int): The ID of the dish to add.
        quantity (int): The number of units to add (must be > 0).
        
    Returns:
        Dict[str, Any]: A structured response indicating success or failure.
    """
    if quantity <= 0:
        return {"status": "error", "message": "Quantity must be greater than 0."}
        
    dish = get_dish_by_id(dish_id)
    
    if not dish:
        return {"status": "error", "message": f"Dish with ID {dish_id} does not exist."}
        
    if not dish.get("available"):
        return {"status": "error", "message": f"Dish '{dish.get('name')}' is currently unavailable."}
        
    cart = _get_cart(session_id)
    cart[dish_id] = cart.get(dish_id, 0) + quantity
    return {"status": "success", "message": f"Added {quantity} of {dish.get('name')} to the cart."}

def remove_from_cart(session_id: str, dish_id: int) -> Dict[str, Any]:
    """
    Remove a dish completely from the shopping cart.
    
    Args:
        session_id (str): The current user session ID.
        dish_id (int): The ID of the dish to remove.
        
    Returns:
        Dict[str, Any]: A structured response indicating success or failure.
    """
    cart = _get_cart(session_id)
    if dish_id not in cart:
        return {"status": "error", "message": f"Dish with ID {dish_id} is not in the cart."}
        
    del cart[dish_id]
    return {"status": "success", "message": f"Removed dish ID {dish_id} from the cart."}

def view_cart(session_id: str) -> Dict[str, Any]:
    """
    View the current contents of the shopping cart.
    
    Args:
        session_id (str): The current user session ID.
        
    Returns:
        Dict[str, Any]: A dictionary containing a list of items (with full dish info, 
                        quantity, and subtotal) and the total cart value.
    """
    menu = load_menu()
    cart_items = []
    total_value = 0.0
    
    cart = _get_cart(session_id)
    
    for dish_id, quantity in cart.items():
        # Find the dish in the menu
        dish = get_dish_by_id(dish_id)
        
        if dish:
            subtotal = dish.get("price", 0.0) * quantity
            total_value += subtotal
            
            cart_items.append({
                "dish": dish,
                "quantity": quantity,
                "subtotal": subtotal
            })
            
    return {
    "items": cart_items,
    "item_count": sum(cart.values()),
    "total": total_value
}

def clear_cart(session_id: str) -> Dict[str, Any]:
    """
    Clear all items from the shopping cart.
    
    Args:
        session_id (str): The current user session ID.
        
    Returns:
        Dict[str, Any]: A structured response indicating success.
    """
    cart = _get_cart(session_id)
    cart.clear()
    return {"status": "success", "message": "Cart cleared successfully."}

def get_dish_by_id(dish_id: int) -> Dict[str, Any] | None:
    """
    Retrieve a dish by its ID from the SQLite database.
    """
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, restaurant_id, name, category, price, is_veg, currency 
            FROM menu_items 
            WHERE id = ?
        ''', (dish_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            dish = dict(row)
            dish["available"] = True
            return dish
        return None
    except Exception as e:
        print(f"Database error in get_dish_by_id: {e}")
        return None

def place_order(session_id: str, customer_name: str) -> Dict[str, Any]:
    """
    Place an order for the current shopping cart.
    
    Args:
        session_id (str): The current user session ID.
        customer_name (str): The name of the customer placing the order.
        
    Returns:
        Dict[str, Any]: A structured response indicating success or failure.
    """
    cart = view_cart(session_id)
    
    if cart.get("item_count", 0) == 0:
        return {"status": "error", "message": "Cannot place an order with an empty cart."}
        
    # Prepare the snapshot of items for the database
    order_items = []
    for item in cart.get("items", []):
        dish = item.get("dish", {})
        order_items.append({
            "dish_id": dish.get("id"),
            "name": dish.get("name"),
            "price": dish.get("price"),
            "quantity": item.get("quantity"),
            "subtotal": item.get("subtotal")
        })
        
    total = cart.get("total", 0.0)
    
    try:
        # Save to database
        order_id = save_order(customer_name=customer_name, items=order_items, total=total, status="Placed")
        
        # Clear the cart only after successful save
        clear_cart(session_id)
        
        return {
            "status": "success",
            "order_id": order_id,
            "customer_name": customer_name,
            "total": total,
            "message": "Order placed successfully."
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to place order: {str(e)}"}

def search_restaurants(query: str, city: str | None = None) -> List[Dict[str, Any]]:
    """
    Search Indian restaurants using SQLite.
    If city is provided, it explicitly filters by city and matches query against name or cuisine.
    If city is not provided, it matches query against name, city, subcity, and cuisine case-insensitively.
    Returns a limited number of items to prevent blowing up the LLM context.
    """
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if city and (not query or not query.strip()):
            city_term = f"%{city.strip()}%"
            cursor.execute('''
                SELECT id, name, city, subcity, address, cuisine, rating, rating_count, cost_for_two 
                FROM restaurants 
                WHERE city LIKE ? 
                LIMIT 20
            ''', (city_term,))
        elif not query or not query.strip():
            return []
        else:
            search_term = f"%{query.strip()}%"
            if city:
                city_term = f"%{city.strip()}%"
                cursor.execute('''
                    SELECT id, name, city, subcity, address, cuisine, rating, rating_count, cost_for_two 
                    FROM restaurants 
                    WHERE city LIKE ? 
                    AND (name LIKE ? OR cuisine LIKE ?)
                    LIMIT 20
                ''', (city_term, search_term, search_term))
            else:
                cursor.execute('''
                    SELECT id, name, city, subcity, address, cuisine, rating, rating_count, cost_for_two 
                    FROM restaurants 
                    WHERE name LIKE ? OR city LIKE ? OR subcity LIKE ? OR cuisine LIKE ?
                    LIMIT 20
                ''', (search_term, search_term, search_term, search_term))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"Database error in search_restaurants: {e}")
        return []

def get_restaurant_by_id(restaurant_id: str) -> Dict[str, Any] | None:
    """
    Retrieve a restaurant by its ID from the SQLite database.
    Note: restaurant_id is a string (TEXT in SQLite).
    """
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, name, city, subcity, address, cuisine, rating, rating_count, cost_for_two 
            FROM restaurants 
            WHERE id = ?
        ''', (restaurant_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    except Exception as e:
        print(f"Database error in get_restaurant_by_id: {e}")
        return None