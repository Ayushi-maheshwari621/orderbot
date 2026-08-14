import json
import os
import sys
import re
import math
import sqlite3
from typing import List, Dict, Any, Tuple

# Ensure we can import from db
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db.database import save_order, get_connection
from agent.geocoder import geocode_address

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

# In-memory user locations
# Maps session_id -> {"latitude": float, "longitude": float, "raw_query": str, "city": str | None}
_USER_LOCATIONS: Dict[str, Dict[str, Any]] = {}

def set_user_gps_location(session_id: str, latitude: float, longitude: float, raw_query: str = "", city: str = None):
    """
    Set the user's explicit GPS coordinates directly (e.g. from device GPS via Streamlit).
    """
    _USER_LOCATIONS[session_id] = {"latitude": latitude, "longitude": longitude, "raw_query": raw_query, "city": city}

def set_user_location(session_id: str, location_query: str) -> Dict[str, Any]:
    """
    Geocode a text address/city and save to the user's session.
    """
    result = geocode_address(location_query)
    if result:
        set_user_gps_location(session_id, result["latitude"], result["longitude"], location_query, result.get("city"))
        return {"status": "success", "message": f"Location successfully set to {location_query}."}
    else:
        return {"status": "error", "message": f"Could not find coordinates for '{location_query}'. Please try a more specific address or city."}

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
    
    # Ensure restaurant context consistency:
    # All items in the cart must belong to the same restaurant_id.
    if cart:
        existing_dish_id = list(cart.keys())[0]
        existing_dish = get_dish_by_id(existing_dish_id)
        if existing_dish and str(existing_dish.get("restaurant_id")) != str(dish.get("restaurant_id")):
            return {
                "status": "error",
                "message": f"Cannot add items from different restaurants. Cart contains items from restaurant '{existing_dish.get('restaurant_id')}', but this item belongs to '{dish.get('restaurant_id')}'."
            }
            
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
    cart_items = []
    total_value = 0.0
    
    cart = _get_cart(session_id)
    
    for dish_id, quantity in cart.items():
        # Find the dish in the menu
        dish = get_dish_by_id(dish_id)
        
        if not dish:
            return {
                "status": "error",
                "message": f"Cart contains invalid dish ID {dish_id} which does not exist in the database. Please clear your cart and search for valid menu items.",
                "items": [],
                "item_count": sum(cart.values()),
                "total": 0.0
            }
            
        subtotal = dish.get("price", 0.0) * quantity
        total_value += subtotal
        
        cart_items.append({
            "dish": dish,
            "quantity": quantity,
            "subtotal": subtotal
        })
            
    return {
        "status": "success",
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
    
    if cart.get("status") == "error":
        return {"status": "error", "message": f"Cannot place order: {cart.get('message')}"}
        
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

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees) in kilometers.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return float('inf')
        
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    r = 6371 # Radius of earth in kilometers
    return c * r

def get_bounding_box(lat: float, lon: float, radius_km: float) -> Tuple[float, float, float, float]:
    """
    Calculate a bounding box (min_lat, max_lat, min_lon, max_lon) for a given radius.
    """
    # 1 degree of latitude is roughly 111.32 km
    lat_delta = radius_km / 111.32
    
    # 1 degree of longitude is 111.32 * cos(latitude) km
    lon_delta = radius_km / (111.32 * math.cos(math.radians(lat)))
    
    return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta

def jit_geocode_restaurants(conn, search_term: str, city_term: str = None, user_city: str = None, offset: int = 0):
    """
    Perform Just-In-Time geocoding for a limited number of matching restaurants that lack coordinates.
    Returns the number of candidates processed in this batch.
    """
    cursor = conn.cursor()
    
    query = '''
        SELECT id, address, city, subcity, name 
        FROM restaurants 
        WHERE latitude IS NULL
    '''
    params = []
    
    if city_term:
        query += ' AND (city LIKE ? OR address LIKE ? OR subcity LIKE ?)'
        params.extend([city_term, city_term, city_term])
        
    if search_term:
        query += ' AND (name LIKE ? OR cuisine LIKE ?)'
        params.extend([search_term, search_term])
        
    # Prioritize candidates whose city, subcity, or address match the search
    if city_term:
        query += '''
            ORDER BY 
            CASE WHEN city LIKE ? THEN 3
                 WHEN subcity LIKE ? THEN 2
                 WHEN address LIKE ? THEN 1
                 ELSE 0 END DESC
        '''
        params.extend([city_term, city_term, city_term])
        
    query += ' LIMIT 5 OFFSET ?'
    params.append(offset)
    
    cursor.execute(query, params)
    candidates = cursor.fetchall()
    print(f"JIT candidates found: {len(candidates)}")
    
    for cand in candidates:
        rest_id = cand['id']
        name = cand['name']
        address = cand['address'] if cand['address'] else ""
        db_city = cand['city'] if cand['city'] else ""
        
        addr_str = f"{address}, {db_city}" if db_city else address
        if not addr_str:
            print(f"Could not geocode {rest_id}; skipping (empty address)")
            continue
            
        print(f"Geocoding restaurant {rest_id}: {name}")
        
        # 1. Full address
        res = geocode_address(f"{addr_str}, India")
        
        # 2. PIN code
        if not res:
            pin_match = re.search(r'\b\d{6}\b', addr_str)
            if pin_match:
                pin = pin_match.group(0)
                print(f"Address geocoding failed; trying PIN: {pin}")
                res = geocode_address(f"{pin}, India")
        
        # 3. Name + User City + India
        if not res and user_city:
            print(f"Address and PIN failed; trying name + user city: {name}, {user_city}")
            res = geocode_address(f"{name}, {user_city}, India")
            
        # 4. Address + DB City (if different)
        if not res and db_city and db_city.lower() not in (user_city.lower() if user_city else ""):
            print(f"Name+City failed; trying address + DB city: {address}, {db_city}")
            res = geocode_address(f"{address}, {db_city}, India")
        
        if res:
            print(f"Geocoding succeeded: {res['latitude']}, {res['longitude']}")
            cursor.execute('''
                UPDATE restaurants 
                SET latitude = ?, longitude = ? 
                WHERE id = ?
            ''', (res['latitude'], res['longitude'], rest_id))
            conn.commit()
        else:
            print(f"Could not geocode {rest_id}; skipping permanently")
            cursor.execute('''
                UPDATE restaurants 
                SET latitude = 0.0, longitude = 0.0 
                WHERE id = ?
            ''', (rest_id,))
            conn.commit()
            
    return len(candidates)

def search_restaurants(session_id: str, query: str, city: str = None, near_me: bool = False) -> List[Dict[str, Any]]:
    """
    Search Indian restaurants using SQLite.
    If near_me is True, uses the user's location from the session and performs spatial search.
    If city is provided, it explicitly filters by city and matches query against name or cuisine.
    If city is not provided, it matches query against name, city, subcity, and cuisine case-insensitively.
    Returns a limited number of items to prevent blowing up the LLM context.
    """
    print("SEARCH_RESTAURANTS SESSION:", session_id)
    print("SEARCH_RESTAURANTS LOCATION:", _USER_LOCATIONS.get(session_id))
    print("SEARCH near_me:", near_me)
    
    if near_me:
        user_loc = _USER_LOCATIONS.get(session_id)
        if not user_loc:
            # We return a specific structure or string? Wait, we return a list of dicts.
            # But the agent expects a string if it fails, or a list if it succeeds.
            # Let's raise an exception or return a special list so LangGraph knows to ask the user.
            raise ValueError("Location unknown. Please ask the user to provide their current address or city.")
            
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        search_term = f"%{query.strip()}%" if (query and query.strip()) else None
        city_term = f"%{city.strip()}%" if (city and city.strip()) else None
        
        if near_me:
            user_lat = user_loc['latitude']
            user_lon = user_loc['longitude']
            user_city = user_loc.get('city')
            
            print(f"User location: {user_city}, {user_lat}, {user_lon}")
            
            jit_city_term = None
            if user_city:
                jit_city_term = f"%{user_city.strip()}%"
                
            radius_km = 10.0 # 10 km radius
            lat_min, lat_max, lon_min, lon_max = get_bounding_box(user_lat, user_lon, radius_km)
            
            def _query_spatial():
                q = '''
                    SELECT id, name, city, address, rating, cuisine, cost_for_two, latitude, longitude
                    FROM restaurants
                    WHERE latitude IS NOT NULL
                      AND latitude BETWEEN ? AND ?
                      AND longitude BETWEEN ? AND ?
                '''
                p = [lat_min, lat_max, lon_min, lon_max]
                if search_term:
                    q += ' AND (name LIKE ? OR cuisine LIKE ?)'
                    p.extend([f"%{search_term}%", f"%{search_term}%"])
                cursor.execute(q, p)
                rows = cursor.fetchall()
                res = []
                for row in rows:
                    d = dict(row)
                    dist = haversine_distance(user_lat, user_lon, d['latitude'], d['longitude'])
                    if dist <= radius_km:
                        d['distance_km'] = round(dist, 2)
                        res.append(d)
                return res

            results = _query_spatial()
            
            # If we don't have enough results in DB, attempt JIT geocoding for un-geocoded candidates
            if len(results) < 5:
                max_jit_batches = 3
                jit_offset = 0
                for batch in range(max_jit_batches):
                    print(f"JIT batch offset={jit_offset}")
                    candidates_processed = jit_geocode_restaurants(conn, search_term, jit_city_term, user_city, offset=jit_offset)
                    print(f"JIT batch completed offset={jit_offset}, candidates_processed={candidates_processed}")
                    results = _query_spatial()
                    if len(results) >= 5 or candidates_processed < 5:
                        break
                    jit_offset += 5
                
            # Sort by distance
            results.sort(key=lambda x: x['distance_km'])
            
            print(f"Spatial results found: {len(results)}")
            
            conn.close()
            return results[:20]
            
        else:
            # Standard search
            if city and not search_term:
                cursor.execute('''
                    SELECT id, name, city, subcity, address, cuisine, rating, rating_count, cost_for_two 
                    FROM restaurants 
                    WHERE city LIKE ? 
                    LIMIT 20
                ''', (city_term,))
            elif not search_term:
                conn.close()
                return []
            else:
                if city:
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
        # Re-raise ValueError so the LLM gets the message
        if isinstance(e, ValueError):
            raise
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