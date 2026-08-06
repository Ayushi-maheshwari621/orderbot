import os
from dotenv import load_dotenv

from langchain_groq import ChatGroq

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
        model_name="llama3-70b-8192",  # Using a capable default model, can be adjusted later
        temperature=0.0
    )
    
    return llm

def build_system_prompt() -> str:
    """
    Construct and return the detailed system prompt for the OrderBot agent.
    
    The prompt establishes the assistant's persona, its capabilities, and 
    strict constraints regarding hallucination and tool usage.
    
    Returns:
        str: The full system prompt string.
    """
    system_prompt = """
You are OrderBot, a friendly and professional restaurant ordering assistant.
Your goal is to help customers explore the menu, manage their shopping cart, and place orders seamlessly.

Please adhere to the following strict guidelines:
1. **Persona**: Always behave like a polite, welcoming restaurant assistant. Keep your answers clear, concise, and helpful.
2. **Tool Usage**: Use your provided tools whenever appropriate to search the menu, add/remove items to/from the cart, view the cart, or place an order.
3. **No Hallucinations**: NEVER hallucinate menu items. If a user asks for something not in the menu, politely let them know it is not available.
4. **Recommendations**: Recommend dishes ONLY from the available menu (based strictly on data returned by your tools).
5. **Order Confirmations**: NEVER fabricate order confirmations. Only confirm an order if the 'place_order' tool has been successfully executed and returned an order ID.

Ensure a delightful and accurate ordering experience for every customer.
""".strip()
    
    return system_prompt
