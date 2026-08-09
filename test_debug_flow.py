import uuid
from langchain_core.messages import SystemMessage
from agent.agent_core import create_agent
from agent.tools import set_user_location, _USER_LOCATIONS

session_id = uuid.uuid4().hex
agent = create_agent(session_id)

set_user_location(session_id, "Gurgaon")
print(f"Set location. _USER_LOCATIONS keys: {list(_USER_LOCATIONS.keys())}")

messages = [("user", "Find pizza restaurants near me")]
loc_str = _USER_LOCATIONS[session_id].get("raw_query", "Unknown")
messages.insert(-1, SystemMessage(content=f"Context: The user's current location is set to '{loc_str}'. Use this for any 'near me' searches."))

print("\n--- Invoking Agent ---")
res = agent.invoke({"messages": messages})
print("--- Agent Done ---")

for m in res["messages"][-2:]:
    if hasattr(m, 'tool_calls') and m.tool_calls:
        print("Tool Calls:", m.tool_calls)
    elif getattr(m, 'type', '') == 'ai' and m.content:
        print("[AI]:", m.content[:100], "...")
