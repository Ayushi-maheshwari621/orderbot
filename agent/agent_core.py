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
    model_name = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
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
   - Never guess, extract, or invent a dish_id, and never use dummy or placeholder IDs. You must use the exact, real dish_id integer returned in the results of search_menu.
16. RESTAURANT MENU ROUTING RULE: When the user asks for the menu of a specific restaurant by NAME and a real restaurant_id is NOT already known:
   - NEVER call search_menu using the restaurant name as restaurant_id.
   - NEVER pass a restaurant name (or placeholder like "Sunny Pizza Cafe ID") into the restaurant_id parameter. Restaurant names and restaurant IDs are different types of values and MUST NEVER be substituted for one another.
   - You MUST call search_restaurants first, wait for the tool output to get the actual restaurant_id, and only call search_menu in a later turn.
   - You must only generate a single tool call to search_restaurants(query=<restaurant name>) in the first turn. You are STRICTLY FORBIDDEN from generating any other tool calls (like search_menu or get_restaurant_by_id) in parallel/same turn.
   - NEVER guess or use a dummy or placeholder ID.
   - FIRST call search_restaurants(query=<restaurant name>) alone.
   - Inspect the returned results.
   - If exactly one restaurant matches, take its ACTUAL returned id.
   - Optionally call get_restaurant_by_id(actual_id) if restaurant details are needed.
   - THEN call search_menu(query="", restaurant_id=<actual returned id>) to retrieve the restaurant menu.
   - Only after that produce the final answer.
   - If multiple restaurants match, show the options and ask the user to choose.
   - If no restaurant matches, tell the user the restaurant could not be found.""".strip()

# Mapped by session_id -> dict of cache_key -> results
_INVOCATION_SEARCH_CACHES = {}
# Mapped by session_id -> set of dish_ids actually returned by search_menu
_SESSION_VALID_DISH_IDS: dict[str, set] = {}
# Mapped by (session_id, restaurant_id) -> count of invalid calls
_INVALID_RESTAURANT_CALL_COUNTS = {}

def reset_search_cache(session_id: str):
    """Reset duplicate-search and valid-dish caches for the current agent invocation."""
    _INVOCATION_SEARCH_CACHES[session_id] = {}
    _SESSION_VALID_DISH_IDS[session_id] = set()
    # Clear invalid call counts for this session
    for k in list(_INVALID_RESTAURANT_CALL_COUNTS.keys()):
        if k[0] == session_id:
            del _INVALID_RESTAURANT_CALL_COUNTS[k]

def get_tools(session_id: str) -> List[Any]:
    """
    Return a list of LangChain-compatible tools exposed from agent.tools.
    The tools are bound to the specific session_id.
    """
    @tool
    def search_menu(query: str, restaurant_id: str | int | None = None):
        """Search the menu for items matching the given query case-insensitively.
        query: food/item/category the user is looking for (can be empty string for full menu).
        restaurant_id: optional restaurant ID.
        """
        if restaurant_id is not None and str(restaurant_id).strip():
            restaurant_id = str(restaurant_id).strip()
        else:
            restaurant_id = None
        print(f"SEARCH_MENU query: {query}")

        # Check duplicate first, but do not return duplicate message if it is an invalid ID
        cache_key = ("search_menu", query, restaurant_id)
        if session_id not in _INVOCATION_SEARCH_CACHES:
            _INVOCATION_SEARCH_CACHES[session_id] = {}

        is_duplicate = cache_key in _INVOCATION_SEARCH_CACHES[session_id]

        # --- restaurant_id guard ---
        if restaurant_id is not None:
            validated = agent_tools.get_restaurant_by_id(restaurant_id)
            if not validated:
                key = (session_id, restaurant_id)
                count = _INVALID_RESTAURANT_CALL_COUNTS.get(key, 0) + 1
                _INVALID_RESTAURANT_CALL_COUNTS[key] = count
                print(f"SEARCH_MENU: invalid restaurant_id={restaurant_id!r}, count={count}, rejecting")
                if count >= 3:
                    return f"Error: You have repeatedly called search_menu with invalid restaurant_id '{restaurant_id}'. You must stop calling search_menu and call search_restaurants first to obtain the correct ID."
                return f"Error: restaurant_id '{restaurant_id}' not found. Call search_restaurants first to get the real ID."
        # --- end guard ---

        if is_duplicate:
            cached = _INVOCATION_SEARCH_CACHES[session_id][cache_key]
            print(f"DUPLICATE SEARCH_MENU DETECTED in this invocation: {cache_key}.")
            return f"Notice: This menu search was already performed. Results: {cached}. Do NOT call search_menu again with the same parameters; use the returned dish_id to call add_to_cart."

        res = agent_tools.search_menu(query, restaurant_id)
        if isinstance(res, list):
            for r in res:
                r["dish_id"] = r.get("id")
            # Track every returned dish_id so add_to_cart can validate
            if session_id not in _SESSION_VALID_DISH_IDS:
                _SESSION_VALID_DISH_IDS[session_id] = set()
            for r in res:
                _SESSION_VALID_DISH_IDS[session_id].add(r["id"])
            # Limit menu search results to 5 items to save tokens
            if len(res) > 5:
                res = res[:5]
                res.append({"note": "...menu truncated, use a more specific query to find other items"})
        print(f"SEARCH_MENU results: {res}")
        
        import json as _json
        final_val = res
        if not isinstance(final_val, str):
            final_val = _json.dumps(final_val)
        _INVOCATION_SEARCH_CACHES[session_id][cache_key] = final_val
        return final_val
        
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
        CRITICAL: You are STRICTLY FORBIDDEN from guessing dish_id. You MUST call search_menu first and use the real, returned dish_id integer. Do NOT call this tool with dummy values.
        """
        print(f"ADD_TO_CART dish_id: {dish_id}, quantity: {quantity}")
        dish = agent_tools.get_dish_by_id(dish_id)
        valid_ids = _SESSION_VALID_DISH_IDS.get(session_id, set())
        if not dish:
            if valid_ids:
                return f"Error: dish_id {dish_id} does not exist in the database. Please call add_to_cart using one of the valid dish_ids returned by search_menu: {sorted(list(valid_ids))}."
            return f"Error: dish_id {dish_id} does not exist in the database. Call search_menu first to retrieve valid dish_ids."
            
        if not valid_ids or dish_id not in valid_ids:
            if valid_ids:
                return f"Error: dish_id {dish_id} was not returned by search_menu in this session. Please call add_to_cart using one of the valid dish_ids returned by search_menu: {sorted(list(valid_ids))}."
            return f"Error: dish_id {dish_id} was not returned by search_menu in this session. You must call search_menu first to retrieve the menu, then use the returned dish_id."
            
        result = agent_tools.add_to_cart(session_id, dish_id, quantity)
        return f"Added {quantity}x '{dish['name']}' (dish_id={dish_id}, \u20b9{dish['price']}) to cart. Confirm this matches the user's request. {result}"
        
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
            city_val = str(city).strip() if city is not None and str(city).strip() else None
            print("TOOL SESSION:", session_id)
            user_loc = agent_tools._USER_LOCATIONS.get(session_id)
            print("TOOL LOCATION:", user_loc)
            
            # Check for duplicate call in the current invocation
            loc_key = (user_loc.get("latitude"), user_loc.get("longitude")) if user_loc else (None, None)
            cache_key = (query, city_val, near_me, loc_key)
            
            if session_id not in _INVOCATION_SEARCH_CACHES:
                _INVOCATION_SEARCH_CACHES[session_id] = {}
                
            if cache_key in _INVOCATION_SEARCH_CACHES[session_id]:
                cached = _INVOCATION_SEARCH_CACHES[session_id][cache_key]
                print(f"DUPLICATE SEARCH DETECTED in this invocation: {cache_key}.")
                return f"Notice: This restaurant search was already performed. Results: {cached}. Do NOT call search_restaurants again with the same parameters; use the returned restaurant ID for search_menu."
                
            res = agent_tools.search_restaurants(session_id, query, city_val, near_me)
            trimmed_res = res
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
            import json as _json
            final_res = trimmed_res if trimmed_res else "No restaurants found matching your query."
            if not isinstance(final_res, str):
                final_res = _json.dumps(final_res)
            _INVOCATION_SEARCH_CACHES[session_id][cache_key] = final_res
            return final_res
        except ValueError as e:
            return str(e)
        
    @tool
    def get_restaurant_by_id(restaurant_id: str):
        """Retrieve a restaurant by its ID from the SQLite database. MUST be the real database integer ID obtained from a prior search_restaurants call. NEVER guess this ID, and NEVER call in parallel with search_restaurants."""
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

# Max chars per ToolMessage body kept from OLDER turns to stay under 6000 TPM.
_TOOL_MSG_TRIM_CHARS = 150

def _trim_history(messages: list) -> list:
    """Keep only the most recent conversation turns to stay under Groq's 6000-token limit.

    Strategy: keep the last MAX_TURNS complete round-trips (HumanMessage → AI →
    ToolMessages) plus the most recent HumanMessage. This guarantees the
    AIMessage→ToolMessage tool_call_id chain is never broken, which would cause
    LangGraph to raise 'model output must contain text or tool calls'.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    MAX_TURNS = 1  # number of prior completed turns to retain

    # Separate out any leading SystemMessage (keep it always)
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    # Split into turns: each turn starts with a HumanMessage
    turns: list[list] = []
    current: list = []
    for m in non_system:
        if isinstance(m, HumanMessage) and current:
            turns.append(current)
            current = [m]
        else:
            current.append(m)
    if current:
        turns.append(current)

    # Keep the last MAX_TURNS completed turns + the final (possibly incomplete) turn
    kept_turns = turns[-(MAX_TURNS + 1):]
    return system_msgs + [m for turn in kept_turns for m in turn]


def create_agent(session_id: str):
    """
    Create and return the LangGraph ReAct agent.
    The returned object exposes an .invoke() that trims history before
    forwarding to Groq so single requests stay under 6000 tokens.
    """
    llm = get_llm()
    tools = get_tools(session_id)
    system_prompt = build_system_prompt()

    agent = create_react_agent(
        llm,
        tools,
        prompt=system_prompt
    )

    # Wrap invoke to trim accumulated ToolMessage history and reset per-turn caches
    class _AgentWithTrim:
        def invoke(self, inputs: dict, **kwargs):
            import time as _time
            # Clear caches for this new user turn
            reset_search_cache(session_id)
            msgs = inputs.get('messages', [])
            inputs = {**inputs, 'messages': _trim_history(msgs)}
            # Retry on transient Groq RateLimitError (HTTP 429) or empty response errors (at most 2 retries)
            last_err = None
            for attempt in range(3):
                try:
                    return agent.invoke(inputs, **kwargs)
                except Exception as e:
                    err_str = str(e)
                    is_rate_limit = '429' in err_str or 'Rate limit' in err_str or 'rate_limit_exceeded' in err_str
                    is_empty_resp = 'model output must contain' in err_str or 'Connection error' in err_str
                    if (is_rate_limit or is_empty_resp) and attempt < 2:
                        last_err = e
                        wait = 5 * (attempt + 1)
                        print(f"[RETRY {attempt+1}/2] Groq rate-limit/transient error, waiting {wait}s: {err_str[:80]}")
                        _time.sleep(wait)
                    else:
                        raise
            raise last_err

    return _AgentWithTrim()
