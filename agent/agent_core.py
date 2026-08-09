import os
from typing import List, Any
from dotenv import load_dotenv

from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from agent import tools as agent_tools

# Load environment variables from the .env file (e.g. GROQ_API_KEY)
load_dotenv()

def get_llm() -> ChatGroq:
    """
    Initialize and return the ChatGroq model instance.
    
    This function relies on the GROQ_API_KEY environment variable being loaded.
    
    Returns:
        ChatGroq: The initialized LangChain Groq model.
        
    Raises:
        ValueError: If the GROQ_API_KEY is not found in the environment variables.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is missing. Please add it to your .env file.")
        
    # Initialize the ChatGroq model with a standard low temperature for factual, reliable responses
    model_name = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    llm = ChatGroq(
        groq_api_key=api_key,
        model_name=model_name,
        temperature=0.0
    )
    
    return llm

def build_system_prompt() -> str:
    """
    Construct and return the detailed system prompt for the OrderBot agent.
    """
    return """You are OrderBot, a restaurant ordering assistant.
1. Never invent menu items, prices, availability, order/restaurant IDs, names, ratings, addresses, or cuisines.
2. Use menu tools for food queries. Use cart tools for cart operations. Call place_order ONLY when the user explicitly asks to checkout, place the order, or buy. NEVER call place_order when the user is searching for food, adding items, viewing the cart, or editing the cart.
3. Base all recommendations and restaurant info strictly on tool results. Be concise and helpful.
4. Search restaurants via search_restaurants. If a restaurant is named but has no ID, call search_restaurants first. If ambiguous, ask user. Once resolved, use its actual ID for search_menu.
5. Use get_restaurant_by_id to fetch specific restaurant details.
6. For cuisine and city queries, pass the city argument explicitly to search_restaurants.
7. Call search_menu with restaurant_id if the restaurant is known; do not mix name into the food query. Global search_menu is for general food queries.
8. Menu results are partial; never assume unavailability from previous searches. Always perform a fresh search_menu call for food/dish requests.
9. Always verify a dish via menu tools to get its real dish_id before calling add_to_cart.
10. For proximity searches ("near me", "nearby"), ALWAYS call search_restaurants(near_me=True). If location is unknown (returns error), ask user to set location via set_user_location.
11. After a search_restaurants tool call returns results, do not call the same search again unless the user request or location has changed.
12. Always explicitly list the found restaurants to the user, including details like rating, cost, cuisine, and distance. Use bullet points or numbered lists.
13. If no restaurants are found, state so clearly and ask the user to specify another search or location.
14. Do not ask "Which of these restaurants would you like to order from?" without first displaying/listing their names. Must list them first. Description is required. Use the information returned from the tool. Keep descriptions concise. Never fabricat any restaurant data.
15. To add a dish to the cart (e.g., "add 1 plain raita"):
   - Step 1: Call search_menu(query="...") first with the exact dish name. You must do this alone. Do NOT call add_to_cart or guess any IDs in this turn.
   - Step 2: Once the tool output of search_menu is returned:
     * If exactly one matching dish is found, call add_to_cart with its exact returned dish_id.
     * If multiple matching dishes are found, list them to the user (with price/restaurant) and ask them to choose. Do NOT call add_to_cart yet.
     * If no matching dishes are found, clearly tell the user that the item was not found.
   - Never guess, extract, or invent a dish_id, and never use dummy/placeholder IDs like 12345, 1, or 0. You must use the exact, real dish_id integer returned in the results of search_menu.""".strip()

# Mapped by session_id -> set of cache keys
_INVOCATION_SEARCH_CACHES = {}

def reset_search_cache(session_id: str):
    """Reset the duplicate search tool call cache for the current agent invocation."""
    _INVOCATION_SEARCH_CACHES[session_id] = set()

def get_tools(session_id: str) -> List[Any]:
    """
    Return a list of LangChain-compatible tools exposed from agent.tools.
    The tools are bound to the specific session_id.
    """
    @tool
    def search_menu(query: str, restaurant_id: str | None = None):
        """Search the menu for items matching the given query case-insensitively.
        query: food/item/category the user is looking for (can be empty string for full menu).
        restaurant_id: optional restaurant ID. When provided, results come ONLY from that restaurant. When omitted, search is global.
        """
        print(f"SEARCH_MENU query: {query}")
        cache_key = ("search_menu", query, restaurant_id)
        if session_id not in _INVOCATION_SEARCH_CACHES:
            _INVOCATION_SEARCH_CACHES[session_id] = set()
            
        if cache_key in _INVOCATION_SEARCH_CACHES[session_id]:
            print(f"DUPLICATE SEARCH_MENU DETECTED in this invocation: {cache_key}. Returning existing results notice.")
            return "This exact menu search has already been performed in this step. Please use the results from the previous search_menu tool output to answer the user's question directly."
            
        _INVOCATION_SEARCH_CACHES[session_id].add(cache_key)
        
        res = agent_tools.search_menu(query, restaurant_id)
        if isinstance(res, list):
            for r in res:
                r["dish_id"] = r.get("id")
        print(f"SEARCH_MENU results: {res}")
        return res if res else "No menu items found matching your query."
        
    @tool
    def get_dish_by_id(dish_id: int):
        """Retrieve a dish by its ID from the cached menu."""
        res = agent_tools.get_dish_by_id(dish_id)
        if isinstance(res, dict):
            res["dish_id"] = res.get("id")
        return res

    @tool
    def add_to_cart(dish_id: int, quantity: int):
        """Add a specific quantity of a dish to the shopping cart.
        CRITICAL: You are STRICTLY FORBIDDEN from guessing dish_id. You MUST call search_menu first and use the real, returned dish_id integer. Do NOT call this tool with dummy values like 12345, 1, or 0.
        """
        print(f"ADD_TO_CART dish_id: {dish_id}, quantity: {quantity}")
        return agent_tools.add_to_cart(session_id, dish_id, quantity)
        
    @tool
    def remove_from_cart(dish_id: int):
        """Remove a dish completely from the shopping cart."""
        return agent_tools.remove_from_cart(session_id, dish_id)
        
    @tool
    def view_cart():
        """View the current contents of the shopping cart."""
        return agent_tools.view_cart(session_id)
        
    @tool
    def clear_cart():
        """Clear all items from the shopping cart."""
        return agent_tools.clear_cart(session_id)
        
    @tool
    def place_order(customer_name: str):
        """Place an order for the current shopping cart."""
        return agent_tools.place_order(session_id, customer_name)
        
    @tool
    def search_restaurants(query: str, city: str | None = None, near_me: bool = False):
        """Search Indian restaurants using SQLite. 
        query: restaurant name or cuisine/type.
        city: optional city/location filter.
        near_me: set to True if the user asks for restaurants near them or close by."""
        try:
            print("TOOL SESSION:", session_id)
            user_loc = agent_tools._USER_LOCATIONS.get(session_id)
            print("TOOL LOCATION:", user_loc)
            
            # Check for duplicate call in the current invocation
            loc_key = (user_loc.get("latitude"), user_loc.get("longitude")) if user_loc else (None, None)
            cache_key = (query, city, near_me, loc_key)
            
            if session_id not in _INVOCATION_SEARCH_CACHES:
                _INVOCATION_SEARCH_CACHES[session_id] = set()
                
            if cache_key in _INVOCATION_SEARCH_CACHES[session_id]:
                print(f"DUPLICATE SEARCH DETECTED in this invocation: {cache_key}. Returning existing results notice.")
                return "This exact search has already been performed in this step. Please use the results from the previous search tool output to answer the user's question directly."
                
            _INVOCATION_SEARCH_CACHES[session_id].add(cache_key)
            
            res = agent_tools.search_restaurants(session_id, query, city, near_me)
            if isinstance(res, list):
                trimmed_res = []
                for r in res[:5]:
                    trimmed_res.append({
                        "id": r.get("id"),
                        "name": r.get("name"),
                        "cuisine": r.get("cuisine") or r.get("cuisines"),
                        "rating": r.get("rating"),
                        "cost_for_two": r.get("cost_for_two") or r.get("price_for_two"),
                        "distance_km": r.get("distance_km"),
                        "subcity": r.get("subcity"),
                        "city": r.get("city")
                    })
                return trimmed_res
            return res if res else "No restaurants found matching your query."
        except ValueError as e:
            return str(e)
        
    @tool
    def get_restaurant_by_id(restaurant_id: str):
        """Retrieve a restaurant by its ID from the SQLite database."""
        res = agent_tools.get_restaurant_by_id(restaurant_id)
        return res if res else "Restaurant not found."

    @tool
    def set_user_location(location_query: str):
        """Geocode and save a user's typed address or city to their session."""
        return agent_tools.set_user_location(session_id, location_query)
        
    return [
        search_menu,
        get_dish_by_id,
        add_to_cart,
        remove_from_cart,
        view_cart,
        clear_cart,
        place_order,
        search_restaurants,
        get_restaurant_by_id,
        set_user_location
    ]

def create_agent(session_id: str):
    """
    Create and return the LangGraph ReAct agent.
    """
    llm = get_llm()
    tools = get_tools(session_id)
    system_prompt = build_system_prompt()
    
    # Create the agent with tools and system prompt
    agent = create_react_agent(
        llm,
        tools,
        prompt=system_prompt
    )
    
    return agent
