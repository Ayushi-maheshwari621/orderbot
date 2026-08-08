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

def get_tools() -> List[Any]:
    """
    Return a list of LangChain-compatible tools exposed from agent.tools.
    """
    return [
        tool(agent_tools.search_menu),
        tool(agent_tools.get_dish_by_id),
        tool(agent_tools.add_to_cart),
        tool(agent_tools.remove_from_cart),
        tool(agent_tools.view_cart),
        tool(agent_tools.clear_cart),
        tool(agent_tools.place_order)
    ]

def create_agent():
    """
    Create and return the LangGraph ReAct agent.
    """
    llm = get_llm()
    tools = get_tools()
    system_prompt = build_system_prompt()
    
    # Create the agent with tools and system prompt
    agent = create_react_agent(
        llm,
        tools,
        prompt=system_prompt
    )
    
    return agent
