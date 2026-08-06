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
