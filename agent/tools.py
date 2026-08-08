import json
import os
import sys
from typing import List, Dict, Any

# Ensure we can import from db
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db.database import save_order

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

def _item_matches_query(item: Dict[str, Any], query: str) -> bool:
    """
    Check if a single menu item matches the search query.
    Matches against name, category, cuisine, and description case-insensitively.
    
    Args:
        item (Dict[str, Any]): The menu item to check.
        query (str): The search query.
        
    Returns:
        bool: True if the item matches the query, False otherwise.
    """
    search_fields = [
        item.get('name', ''),
        item.get('category', ''),
        item.get('cuisine', ''),
        item.get('description', '')
    ]
    
    query_lower = query.lower()
    for field in search_fields:
        if field and query_lower in str(field).lower():
            return True
            
    return False

def search_menu(query: str) -> List[Dict[str, Any]]:
    """
    Search the menu for items matching the given query case-insensitively.
    Only returns items that are marked as available.
    
    Args:
        query (str): The text to search for across dish name, category, cuisine, and description.
        
    Returns:
        List[Dict[str, Any]]: A list of available menu items matching the query.
    """
    menu = load_menu()
    
    if not query or not query.strip():
        return []
        
    return [
    item
    for item in menu
    if item.get("available") and _item_matches_query(item, query)
]

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
    Retrieve a dish by its ID from the cached menu.
    """
    menu = load_menu()
    return next((item for item in menu if item.get("id") == dish_id), None)

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