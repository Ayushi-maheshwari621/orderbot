import streamlit as st
import uuid
from streamlit_geolocation import streamlit_geolocation
from agent.agent_core import create_agent, reset_search_cache
from agent.tools import _USER_LOCATIONS, set_user_gps_location, set_user_location
from agent.geocoder import reverse_geocode
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

def init_app():
    st.set_page_config(page_title="OrderBot", page_icon="🍽️")
    st.title("🍽️ OrderBot")
    st.subheader("AI Restaurant Ordering Assistant")

    # Initialize a unique session_id for this user session
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex

    # Initialize agent and message history in session state
    if "agent" not in st.session_state:
        st.session_state.agent = create_agent(st.session_state.session_id)

    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Handle sidebar for location management
    with st.sidebar:
        st.header("📍 Current Location")
        
        # Read current location from backend
        current_loc = _USER_LOCATIONS.get(st.session_state.session_id)
        if current_loc:
            if current_loc.get("raw_query") == "Device GPS":
                st.success(f"Device GPS ({current_loc['latitude']:.4f}, {current_loc['longitude']:.4f})")
            else:
                st.success(current_loc.get("raw_query", "Location Set"))
        else:
            st.warning("Unknown")
            
        st.divider()
        st.write("**Option 1: Use Device Location**")
        loc_res = streamlit_geolocation()
        if loc_res and loc_res.get('latitude') and loc_res.get('longitude'):
            # Only update if the location actually changed
            lat, lon = loc_res['latitude'], loc_res['longitude']
            if not current_loc or current_loc.get("latitude") != lat or current_loc.get("longitude") != lon:
                with st.spinner("Finding your city..."):
                    rev_res = reverse_geocode(lat, lon)
                    city = rev_res.get("city") if rev_res else None
                    set_user_gps_location(st.session_state.session_id, lat, lon, "Device GPS", city)
                st.rerun()
                
        st.write("**Option 2: Enter manually**")
        manual_loc = st.text_input("Address, Locality, or City")
        if st.button("Set Location") and manual_loc:
            with st.spinner("Geocoding..."):
                res = set_user_location(st.session_state.session_id, manual_loc)
                if res["status"] == "success":
                    st.rerun()
                else:
                    st.error(res["message"])

    # Display existing chat history
    for msg in st.session_state.messages:
        # Handle initial tuples before they are processed by the agent
        if isinstance(msg, tuple):
            role, content = msg
            if role in ["user", "assistant"] and content:
                with st.chat_message(role):
                    st.markdown(content)
        # Handle processed HumanMessages
        elif isinstance(msg, HumanMessage):
            if msg.content and not msg.content.startswith("[System:"):
                with st.chat_message("user"):
                    st.markdown(msg.content)
        # Handle processed AIMessages
        elif isinstance(msg, AIMessage):
            # Only display AI messages that have text content (ignore internal tool calls)
            if msg.content:
                with st.chat_message("assistant"):
                    st.markdown(msg.content)

    # Handle new user input
    if user_input := st.chat_input("Type your message here..."):
        # Display user message immediately
        with st.chat_message("user"):
            st.markdown(user_input)

        # Append to conversation history
        st.session_state.messages.append(("user", user_input))

        # Invoke the agent
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                # Construct the trimmed history: keep only HumanMessage and conversational AIMessages
                trimmed_history = []
                history = st.session_state.messages[:-1]
                for msg in history:
                    if isinstance(msg, tuple):
                        trimmed_history.append(msg)
                    elif isinstance(msg, HumanMessage):
                        if msg.content and not msg.content.startswith("[System:"):
                            trimmed_history.append(msg)
                    elif isinstance(msg, AIMessage):
                        if msg.content and not getattr(msg, "tool_calls", None):
                            trimmed_history.append(msg)
                
                # Inject a temporary SystemMessage so the agent knows the current location
                current_loc = _USER_LOCATIONS.get(st.session_state.session_id)
                loc_str = current_loc.get("raw_query", "Unknown") if current_loc else "Unknown"
                trimmed_history.append(SystemMessage(content=f"Context: The user's current location is set to '{loc_str}'. Use this for any 'near me' searches."))
                
                # Append the new user request
                trimmed_history.append(st.session_state.messages[-1])
                
                print("APP SESSION:", st.session_state.session_id)
                print("APP LOCATION:", _USER_LOCATIONS.get(st.session_state.session_id))
                
                inputs = {"messages": trimmed_history}
                print("=== LLM REQUEST DIAGNOSTIC ===")
                print("messages count:", len(inputs["messages"]))
                print("message types:", [type(m).__name__ if not isinstance(m, tuple) else f"tuple({m[0]})" for m in inputs["messages"]])
                print("total chars:", sum(len(str(getattr(m, "content", m[1] if isinstance(m, tuple) else ""))) for m in inputs["messages"]))
                for i, m in enumerate(inputs["messages"]):
                    content = getattr(m, "content", m[1] if isinstance(m, tuple) else "")
                    print(i, type(m).__name__ if not isinstance(m, tuple) else "tuple", len(str(content)))
                
                reset_search_cache(st.session_state.session_id)
                result = st.session_state.agent.invoke(inputs)

                # Update the stored conversation history with the full returned sequence, EXCLUDING our temporary SystemMessage
                st.session_state.messages = [m for m in result.get("messages", []) if not isinstance(m, SystemMessage)]
                
                # The final assistant response is the last message
                final_message = st.session_state.messages[-1]
                if final_message.content:
                    st.markdown(final_message.content)

if __name__ == "__main__":
    init_app()
