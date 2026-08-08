import streamlit as st
import uuid
from agent.agent_core import create_agent
from langchain_core.messages import HumanMessage, AIMessage

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
            if msg.content:
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
                inputs = {"messages": st.session_state.messages}
                result = st.session_state.agent.invoke(inputs)

                # Update the stored conversation history with the full returned sequence
                st.session_state.messages = result.get("messages", [])
                
                # The final assistant response is the last message
                final_message = st.session_state.messages[-1]
                if final_message.content:
                    st.markdown(final_message.content)

if __name__ == "__main__":
    init_app()
