import time
import requests
from typing import Dict, Any, Optional

# Ensure we don't hit Nominatim more than once per second
_LAST_REQUEST_TIME = 0.0

def geocode_address(query: str) -> Optional[Dict[str, Any]]:
    """
    Geocodes a text query (address/city/locality) into latitude and longitude 
    using OpenStreetMap Nominatim.
    
    Enforces a strict 1-second rate limit between requests to comply with OSM policies.
    Returns:
        {"latitude": float, "longitude": float, "city": str} if successful, None otherwise.
    """
    global _LAST_REQUEST_TIME
    
    if not query or not query.strip():
        return None
        
    # Rate limit enforcement (1 request per second max, safe margin = 1.1s)
    current_time = time.time()
    elapsed = current_time - _LAST_REQUEST_TIME
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
        
    _LAST_REQUEST_TIME = time.time()
    
    headers = {
        "User-Agent": "OrderBotApp/1.0 (contact@orderbot.local)"
    }
    
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "addressdetails": 1
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=5.0)
        response.raise_for_status()
        data = response.json()
        
        if data and len(data) > 0:
            result = {
                "latitude": float(data[0]["lat"]),
                "longitude": float(data[0]["lon"])
            }
            address = data[0].get("address", {})
            city = address.get("city") or address.get("town") or address.get("municipality") or address.get("village") or address.get("suburb")
            if city:
                result["city"] = city
            return result
        return None
        
    except Exception as e:
        print(f"Geocoding error for '{query}': {e}")
        return None

def reverse_geocode(latitude: float, longitude: float) -> Optional[Dict[str, Any]]:
    """
    Reverse geocodes coordinates to find the city/locality.
    """
    global _LAST_REQUEST_TIME
    
    current_time = time.time()
    elapsed = current_time - _LAST_REQUEST_TIME
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
        
    _LAST_REQUEST_TIME = time.time()
    
    headers = {
        "User-Agent": "OrderBotApp/1.0 (contact@orderbot.local)"
    }
    
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "json",
        "addressdetails": 1
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=5.0)
        response.raise_for_status()
        data = response.json()
        
        address = data.get("address", {})
        city = address.get("city") or address.get("town") or address.get("municipality") or address.get("village") or address.get("suburb")
        
        result = {
            "latitude": latitude,
            "longitude": longitude
        }
        if city:
            result["city"] = city
        return result
        
    except Exception as e:
        print(f"Reverse geocoding error for lat={latitude}, lon={longitude}: {e}")
        return None
