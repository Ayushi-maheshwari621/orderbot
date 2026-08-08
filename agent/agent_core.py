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
    llm = ChatGroq(
        groq_api_key=api_key,
        model_name="openai/gpt-oss-120b",  # Using a capable default model, can be adjusted later
        temperature=0.0
    )
    
    return llm

def build_system_prompt() -> str:
    """
    Construct and return the detailed system prompt for the OrderBot agent.
    """
    system_prompt = """
You are OrderBot, a restaurant ordering assistant.
1. Never invent menu items, prices, availability, or order IDs.
2. Use the menu tools when the user asks about available food.
3. Use cart tools for cart operations.
4. Use place_order only when the user explicitly wants to place the order.
5. Never claim an order was successfully placed unless place_order actually succeeds.
6. Base recommendations on the actual menu returned by the tools.
7. Be concise and helpful.
8. Use restaurant search when the user asks to find restaurants.
9. Use get_restaurant_by_id when the user asks about a specific restaurant.
10. Never invent restaurant names, ratings, addresses, cuisines, or other restaurant information.
11. Base restaurant information on tool results.
12. When the user specifies both a restaurant type/cuisine and a city, use the city argument explicitly instead of combining them into one query string.
13. When the user asks for menu items from a specific restaurant AND the restaurant ID is already known in the conversation, use search_menu(query, restaurant_id).
14. Never fabricate a restaurant_id. Do not invent restaurant IDs.
15. If the user gives a restaurant name but no restaurant ID is known:
    - Use search_restaurants() to find the restaurant.
    - If multiple matches exist, present the options and ask the user which restaurant they mean.
    - Once the restaurant is unambiguous, use its actual database ID for restaurant-specific menu searches.
16. Do not combine restaurant name into the food query when the restaurant_id is available.
17. If the user asks for food generally without a restaurant, global search_menu is acceptable.
18. Menu search results are limited and must be treated as partial results, not the complete menu.
19. Never infer that an item is unavailable simply because it was absent from a previous search result.
20. When the user requests a specific food, category, or dish, always perform a fresh search_menu call.
21. When a restaurant_id is known, always pass it to search_menu for restaurant-specific requests.
22. Before adding a specific dish to the cart, verify the dish through the menu tools and obtain its real dish_id.
23. Only claim that an item is unavailable when the relevant search_menu call returned no matching results.
""".strip()
    
    return system_prompt

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
        res = agent_tools.search_menu(query, restaurant_id)
        return res if res else "No menu items found matching your query."
        
    @tool
    def get_dish_by_id(dish_id: int):
        """Retrieve a dish by its ID from the cached menu."""
        return agent_tools.get_dish_by_id(dish_id)

    @tool
    def add_to_cart(dish_id: int, quantity: int):
        """Add a specific quantity of a dish to the shopping cart."""
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
    def search_restaurants(query: str, city: str = None):
        """Search Indian restaurants using SQLite. 
        query: restaurant name or cuisine/type.
        city: optional city/location filter."""
        res = agent_tools.search_restaurants(query, city)
        return res if res else "No restaurants found matching your query."
        
    @tool
    def get_restaurant_by_id(restaurant_id: str):
        """Retrieve a restaurant by its ID from the SQLite database."""
        res = agent_tools.get_restaurant_by_id(restaurant_id)
        return res if res else "Restaurant not found."

        
    return [
        search_menu,
        get_dish_by_id,
        add_to_cart,
        remove_from_cart,
        view_cart,
        clear_cart,
        place_order,
        search_restaurants,
        get_restaurant_by_id
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
