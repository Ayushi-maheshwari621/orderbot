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
""".strip()
    
    return system_prompt

def get_tools(session_id: str) -> List[Any]:
    """
    Return a list of LangChain-compatible tools exposed from agent.tools.
    The tools are bound to the specific session_id.
    """
    @tool
    def search_menu(query: str):
        """Search the menu for items matching the given query case-insensitively."""
        return agent_tools.search_menu(query)
        
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
        
    return [
        search_menu,
        get_dish_by_id,
        add_to_cart,
        remove_from_cart,
        view_cart,
        clear_cart,
        place_order
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
