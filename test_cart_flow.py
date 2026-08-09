import uuid
import time
from agent.agent_core import create_agent, reset_search_cache
from agent.tools import set_user_location, _USER_LOCATIONS
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

session_id = uuid.uuid4().hex
agent = create_agent(session_id)

set_user_location(session_id, "Delhi")
loc_str = _USER_LOCATIONS[session_id].get("raw_query", "Unknown")

def run_query(user_query):
    # In Streamlit, app.py cleanses previous ToolMessages
    # We will simulate this by keeping only conversational messages in history.
    global messages
    
    # Trim history to conversational only
    trimmed_history = []
    for msg in messages:
        if isinstance(msg, tuple):
            trimmed_history.append(msg)
        elif isinstance(msg, HumanMessage):
            trimmed_history.append(msg)
        elif isinstance(msg, AIMessage):
            if msg.content and not getattr(msg, "tool_calls", None):
                trimmed_history.append(msg)
                
    # Add SystemMessage for location and the new user query
    trimmed_history.append(SystemMessage(content=f"Context: The user's current location is set to '{loc_str}'. Use this for any 'near me' searches."))
    trimmed_history.append(("user", user_query))
    
    # Reset search cache
    reset_search_cache(session_id)
    
    print(f"\n--- User: {user_query} ---")
    res = agent.invoke({"messages": trimmed_history})
    
    # Update global messages list with the full returned list
    messages = [m for m in res.get("messages", []) if not isinstance(m, SystemMessage)]
    
    # Print tool calls and final content
    for m in messages[-3:]:
        mtype = type(m).__name__
        tool_calls = getattr(m, "tool_calls", None)
        content = getattr(m, "content", "")
        if tool_calls:
            print(f"  [{mtype}] calls tool: {[tc['name'] for tc in tool_calls]} with args: {[tc['args'] for tc in tool_calls]}")
        elif mtype == "ToolMessage":
            # Print truncated tool output
            print(f"  [{mtype}] returned: {str(content)[:200]}...")
        elif content:
            print(f"  [{mtype} Response]: {content}")
            
    print("Sleeping 15 seconds to avoid Groq TPM limits...")
    time.sleep(15)

messages = []

# Run the test queries
run_query("add 1 plain raita")
run_query("add 1 tandoori roti")
run_query("add 1 dal makhani")
run_query("add 2 plain raita")
run_query("show my cart")
