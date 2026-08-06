import json
import os
from typing import List, Dict, Any

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

# In-memory shopping cart
# Maps dish_id to quantity
_CART: Dict[int, int] = {}

def add_to_cart(dish_id: int, quantity: int) -> Dict[str, Any]:
    """
    Add a specific quantity of a dish to the shopping cart.
    
    Args:
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
        
    _CART[dish_id] = _CART.get(dish_id, 0) + quantity
    return {"status": "success", "message": f"Added {quantity} of {dish.get('name')} to the cart."}

def remove_from_cart(dish_id: int) -> Dict[str, Any]:
    """
    Remove a dish completely from the shopping cart.
    
    Args:
        dish_id (int): The ID of the dish to remove.
        
    Returns:
        Dict[str, Any]: A structured response indicating success or failure.
    """
    if dish_id not in _CART:
        return {"status": "error", "message": f"Dish with ID {dish_id} is not in the cart."}
        
    del _CART[dish_id]
    return {"status": "success", "message": f"Removed dish ID {dish_id} from the cart."}

def view_cart() -> Dict[str, Any]:
    """
    View the current contents of the shopping cart.
    
    Returns:
        Dict[str, Any]: A dictionary containing a list of items (with full dish info, 
                        quantity, and subtotal) and the total cart value.
    """
    menu = load_menu()
    cart_items = []
    total_value = 0.0
    
    for dish_id, quantity in _CART.items():
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
    "item_count": sum(_CART.values()),
    "total": total_value
}

def clear_cart() -> Dict[str, Any]:
    """
    Clear all items from the shopping cart.
    
    Returns:
        Dict[str, Any]: A structured response indicating success.
    """
    _CART.clear()
    return {"status": "success", "message": "Cart cleared successfully."}

def get_dish_by_id(dish_id: int) -> Dict[str, Any] | None:
    """
    Retrieve a dish by its ID from the cached menu.
    """
    menu = load_menu()
    return next((item for item in menu if item.get("id") == dish_id), None)