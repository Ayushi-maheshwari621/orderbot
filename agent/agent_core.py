import os
from typing import List, Any
from dotenv import load_dotenv

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from agent import tools as agent_tools

# Load environment variables from the .env file (e.g. GOOGLE_API_KEY, GEMINI_MODEL)
load_dotenv()

def get_llm() -> ChatGoogleGenerativeAI:
    """
    Initialize and return the ChatGoogleGenerativeAI model instance.
    
    This function relies on the GOOGLE_API_KEY environment variable being loaded.
    
    Returns:
        ChatGoogleGenerativeAI: The initialized LangChain Gemini model.
        
    Raises:
        ValueError: If the GOOGLE_API_KEY is not found in the environment variables.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY is missing. Please add it to your .env file.")
        
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    fallback_list = [model_name, "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.5-flash"]
    # De-duplicate while preserving order
    seen_models = set()
    FALLBACK_MODELS = [m for m in fallback_list if not (m in seen_models or seen_models.add(m))]
    
    class _InstrumentedChatGoogleGenerativeAI(ChatGoogleGenerativeAI):
        current_model_idx: int = 0

        def _generate(self, *args, **kwargs):
            import time as _t
            import datetime as _dt
            
            last_exception = None
            for idx in range(len(FALLBACK_MODELS)):
                model_to_try = FALLBACK_MODELS[(self.current_model_idx + idx) % len(FALLBACK_MODELS)]
                self.model = model_to_try
                start_t = _t.time()
                now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                print(f"\n=== LLM CALL START ===")
                print(f"time: {now_str}")
                print(f"model: {self.model}")
                try:
                    res = super()._generate(*args, **kwargs)
                    elapsed = round(_t.time() - start_t, 3)
                    print(f"=== LLM CALL END ===")
                    print(f"elapsed: {elapsed}s\n")
                    self.current_model_idx = (self.current_model_idx + idx) % len(FALLBACK_MODELS)
                    return res
                except Exception as e:
                    elapsed = round(_t.time() - start_t, 3)
                    err_str = str(e)
                    print(f"=== LLM CALL ERROR ({elapsed}s) ===")
                    is_transient = any(code in err_str for code in ["429", "503", "500", "502", "504", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "quota", "high demand", "Overloaded"])
                    if is_transient:
                        print(f"⚠️ Model '{model_to_try}' unavailable ({err_str[:60]}...). Failing over to next model...")
                        continue
                    else:
                        raise e
            if last_exception:
                raise last_exception

    llm = _InstrumentedChatGoogleGenerativeAI(
        model=FALLBACK_MODELS[0],
        google_api_key=api_key,
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
15. To add a dish to the cart (e.g. "add 1 Capsicum Pizza to my cart", "add 1 Margherita Pizza", "add 2 burgers"):
   - Call add_to_cart(dish_name="Capsicum Pizza", quantity=1). You may also pass dish_id if already known.
   - The system automatically resolves the REAL database ID against the active restaurant menu. NEVER invent IDs.
16. When the user asks for the menu of a specific restaurant by name (e.g. "show me menu of Pizza Hut", "Pizza Hut menu"):
   - Step 1: Call search_restaurants(query="restaurant name") first to resolve the restaurant ID.
   - Step 2: Once search_restaurants returns matching outlets, immediately pick the first/best matching outlet's id (or nearest outlet if location is known) and call search_menu(query="", restaurant_id=id). Do NOT list restaurant outlets or ask the user to choose an outlet. Immediately call search_menu and display the menu items.""".strip()

# Mapped by session_id -> dict of cache_key -> results
_INVOCATION_SEARCH_CACHES = {}
# Mapped by session_id -> set of dish_ids actually returned by search_menu
_SESSION_VALID_DISH_IDS: dict[str, set] = {}
# Mapped by (session_id, restaurant_id) -> count of invalid calls
_INVALID_RESTAURANT_CALL_COUNTS = {}
# Mapped by session_id -> active restaurant_id
_SESSION_ACTIVE_RESTAURANT: dict[str, str] = {}

def reset_search_cache(session_id: str):
    """Reset duplicate-search cache for the current agent invocation."""
    _INVOCATION_SEARCH_CACHES[session_id] = {}
    # Clear invalid call counts for this session
    for k in list(_INVALID_RESTAURANT_CALL_COUNTS.keys()):
        if k[0] == session_id:
            del _INVALID_RESTAURANT_CALL_COUNTS[k]

def resolve_dish_for_cart(session_id: str, dish_id: Any = None, dish_name: str | None = None) -> tuple[dict | None, str | None]:
    """
    Resolve a dish request to a real database item using active restaurant context and name matching.
    """
    import sqlite3 as _sqlite3
    import re as _re

    active_resto = _SESSION_ACTIVE_RESTAURANT.get(session_id)

    # 1. If dish_id is actually a dish name string:
    if isinstance(dish_id, str) and not dish_id.strip().isdigit() and not dish_name:
        dish_name = dish_id.strip()
        dish_id = None

    # 2. If dish_id is an integer, check if it's a real dish in DB
    if dish_id is not None:
        try:
            val_id = int(str(dish_id).strip())
            found = agent_tools.get_dish_by_id(val_id)
            if found:
                # If active restaurant is set, make sure it matches
                if not active_resto or str(found.get("restaurant_id")) == str(active_resto):
                    return found, None
        except (ValueError, TypeError):
            pass

    # 3. Resolve by name against the active restaurant (or database)
    if dish_name or dish_id is not None:
        lookup_name = dish_name.strip() if dish_name else str(dish_id).strip()
        
        conn = agent_tools.get_connection()
        conn.row_factory = _sqlite3.Row
        c = conn.cursor()
        
        rows = []
        if active_resto:
            c.execute("SELECT id, restaurant_id, name, category, price, is_veg, currency FROM menu_items WHERE restaurant_id = ?", (str(active_resto),))
            rows = [dict(r) for r in c.fetchall()]
        else:
            search_pattern = f"%{lookup_name}%"
            c.execute("SELECT id, restaurant_id, name, category, price, is_veg, currency FROM menu_items WHERE name LIKE ? LIMIT 50", (search_pattern,))
            rows = [dict(r) for r in c.fetchall()]
        conn.close()
        
        if rows:
            target_lower = lookup_name.lower()
            
            # Exact match (case-insensitive)
            exact = [r for r in rows if r["name"].strip().lower() == target_lower]
            if len(exact) >= 1:
                return exact[0], None
                
            # Normalized match (stripping punctuation/brackets like [medium 8 inches])
            norm_target = _re.sub(r'[^a-zA-Z0-9\s]', '', target_lower).strip()
            sub_matches = []
            for r in rows:
                r_norm = _re.sub(r'[^a-zA-Z0-9\s]', '', r["name"].lower()).strip()
                if norm_target and (norm_target == r_norm or norm_target in r_norm or r_norm in norm_target):
                    sub_matches.append(r)
                    
            if len(sub_matches) == 1:
                return sub_matches[0], None
            elif len(sub_matches) > 1:
                # If all matches have identical name, pick first
                if len(set(m["name"].lower() for m in sub_matches)) == 1:
                    return sub_matches[0], None
                options_str = ", ".join([f"{m['name']} (ID: {m['id']}, ₹{m['price']})" for m in sub_matches[:5]])
                return None, f"Multiple matching dishes found for '{lookup_name}': {options_str}. Please specify which one you'd like to add."

    return None, f"Dish '{dish_name or dish_id}' could not be found. Please check the restaurant menu."


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
        print(f"TOOL CALL: search_menu(query={query!r}, restaurant_id={restaurant_id!r})")

        if restaurant_id:
            _SESSION_ACTIVE_RESTAURANT[session_id] = str(restaurant_id)

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
                print(f"TOOL RESULT: [Invalid restaurant_id={restaurant_id!r}, count={count}]")
                if count >= 3:
                    return f"Error: You have repeatedly called search_menu with invalid restaurant_id '{restaurant_id}'. You must stop calling search_menu and call search_restaurants first to obtain the correct ID."
                return f"Error: restaurant_id '{restaurant_id}' not found. Call search_restaurants first to get the real ID."
        # --- end guard ---

        if is_duplicate:
            cached = _INVOCATION_SEARCH_CACHES[session_id][cache_key]
            print(f"TOOL RESULT: [DUPLICATE CACHE HIT] {cached[:100]}...")
            return f"Notice: This menu search was already performed. Results: {cached}. Do NOT call search_menu again with the same parameters; use the returned dish_id to call add_to_cart."

        res = agent_tools.search_menu(query, restaurant_id)
        if isinstance(res, list):
            for r in res:
                r["dish_id"] = r.get("id")
            # Track every returned dish_id so add_to_cart can validate
            if session_id not in _SESSION_VALID_DISH_IDS:
                _SESSION_VALID_DISH_IDS[session_id] = set()
            for r in res:
                if "id" in r:
                    _SESSION_VALID_DISH_IDS[session_id].add(r["id"])
            # Limit menu search results to 10 items to save tokens while showing a rich menu
            if len(res) > 10:
                res = res[:10]
                res.append({"note": "...menu truncated, use a more specific query to find other items"})
        
        import json as _json
        final_val = res
        if not isinstance(final_val, str):
            final_val = _json.dumps(final_val)
        print(f"TOOL RESULT: {final_val[:120]}...")
        _INVOCATION_SEARCH_CACHES[session_id][cache_key] = final_val
        return final_val
        
    @tool
    def get_dish_by_id(dish_id: int):
        """Retrieve a dish by its ID from the cached menu."""
        print(f"TOOL CALL: get_dish_by_id(dish_id={dish_id!r})")
        res = agent_tools.get_dish_by_id(dish_id)
        if isinstance(res, dict):
            res["dish_id"] = res.get("id")
        print(f"TOOL RESULT: {res}")
        return res

    @tool
    def add_to_cart(dish_id: int | str | None = None, quantity: int = 1, dish_name: str | None = None):
        """Add a specific quantity of a dish to the shopping cart.
        dish_id: The integer database ID of the dish (if known).
        quantity: Number of units to add (default 1).
        dish_name: The name of the dish (e.g. 'Capsicum Pizza') to resolve its exact real database ID.
        """
        print(f"TOOL CALL: add_to_cart(dish_id={dish_id!r}, quantity={quantity!r}, dish_name={dish_name!r})")
        resolved_dish, err_msg = resolve_dish_for_cart(session_id, dish_id=dish_id, dish_name=dish_name)
        if not resolved_dish:
            res = err_msg or f"Error: Dish '{dish_name or dish_id}' could not be resolved."
            print(f"TOOL RESULT: {res}")
            return res
            
        real_id = resolved_dish["id"]
        result = agent_tools.add_to_cart(session_id, real_id, quantity)
        if result.get("status") == "success":
            res = f"Added {quantity}x '{resolved_dish.get('name')}' (dish_id={real_id}, \u20b9{resolved_dish.get('price')}) to cart. {result.get('message')}"
        else:
            res = f"Failed to add to cart: {result.get('message')}"
        print(f"TOOL RESULT: {res}")
        return res
        
    @tool
    def remove_from_cart(dish_id: int):
        """Remove a dish completely from the shopping cart."""
        print(f"TOOL CALL: remove_from_cart(dish_id={dish_id!r})")
        res = agent_tools.remove_from_cart(session_id, dish_id)
        print(f"TOOL RESULT: {res}")
        return res
        
    @tool
    def view_cart():
        """View the current contents of the shopping cart."""
        print("TOOL CALL: view_cart()")
        res = agent_tools.view_cart(session_id)
        print(f"TOOL RESULT: {res}")
        return res
        
    @tool
    def clear_cart():
        """Clear all items from the shopping cart."""
        print("TOOL CALL: clear_cart()")
        res = agent_tools.clear_cart(session_id)
        print(f"TOOL RESULT: {res}")
        return res
        
    @tool
    def place_order(customer_name: str):
        """Place an order for the current shopping cart."""
        print(f"TOOL CALL: place_order(customer_name={customer_name!r})")
        res = agent_tools.place_order(session_id, customer_name)
        print(f"TOOL RESULT: {res}")
        return res
        
    @tool
    def search_restaurants(query: str, city: str | None = None, near_me: bool = False):
        """Search Indian restaurants using SQLite. 
        query: restaurant name or cuisine/type.
        city: optional city/location filter.
        near_me: set to True if the user asks for restaurants near them or close by."""
        try:
            city_val = str(city).strip() if city is not None and str(city).strip() else None
            user_loc = agent_tools._USER_LOCATIONS.get(session_id)
            print(f"TOOL CALL: search_restaurants(query={query!r}, city={city_val!r}, near_me={near_me!r})")
            
            # Check for duplicate call in the current invocation
            loc_key = (user_loc.get("latitude"), user_loc.get("longitude")) if user_loc else (None, None)
            cache_key = (query, city_val, near_me, loc_key)
            
            if session_id not in _INVOCATION_SEARCH_CACHES:
                _INVOCATION_SEARCH_CACHES[session_id] = {}
                
            if cache_key in _INVOCATION_SEARCH_CACHES[session_id]:
                cached = _INVOCATION_SEARCH_CACHES[session_id][cache_key]
                print(f"TOOL RESULT: [DUPLICATE CACHE HIT] {cached[:100]}...")
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
            print(f"TOOL RESULT: {final_res[:120]}...")
            _INVOCATION_SEARCH_CACHES[session_id][cache_key] = final_res
            return final_res
        except ValueError as e:
            print(f"TOOL RESULT ERROR: {e}")
            return str(e)
        
    @tool
    def get_restaurant_by_id(restaurant_id: str):
        """Retrieve a restaurant by its ID from the SQLite database. MUST be the real database integer ID obtained from a prior search_restaurants call. NEVER guess this ID, and NEVER call in parallel with search_restaurants."""
        print(f"TOOL CALL: get_restaurant_by_id(restaurant_id={restaurant_id!r})")
        res = agent_tools.get_restaurant_by_id(restaurant_id)
        res_val = res if res else "Restaurant not found."
        print(f"TOOL RESULT: {res_val}")
        return res_val

    @tool
    def set_user_location(location_query: str):
        """Geocode and save a user's typed address or city to their session."""
        print(f"TOOL CALL: set_user_location(location_query={location_query!r})")
        res = agent_tools.set_user_location(session_id, location_query)
        print(f"TOOL RESULT: {res}")
        return res
        
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
            print(f"AGENT ITERATION: Starting invocation with {len(inputs['messages'])} messages")
            # Retry on transient Groq RateLimitError (HTTP 429) or empty response errors (at most 2 retries)
            last_err = None
            for attempt in range(3):
                try:
                    res = agent.invoke(inputs, **kwargs)
                    print(f"AGENT ITERATION: Invocation completed successfully")
                    return res
                except Exception as e:
                    err_str = str(e)
                    is_rate_limit = '429' in err_str or 'Rate limit' in err_str or 'rate_limit_exceeded' in err_str
                    is_empty_resp = 'model output must contain' in err_str or 'Connection error' in err_str
                    if (is_rate_limit or is_empty_resp) and attempt < 2:
                        last_err = e
                        wait = 5 * (attempt + 1)
                        # If Groq specifically tells us how many seconds to wait, honor that:
                        import re as _re
                        match = _re.search(r'try again in ([0-9]+(?:\.[0-9]+)?)s', err_str)
                        if match:
                            try:
                                wait = float(match.group(1)) + 0.5
                            except Exception:
                                pass
                        print(f"RETRY: [Attempt {attempt+1}/2] Gemini rate-limit/transient error, waiting {wait}s: {err_str[:80]}")
                        _time.sleep(wait)
                    else:
                        raise
            raise last_err

    return _AgentWithTrim()
