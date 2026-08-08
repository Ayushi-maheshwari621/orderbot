from agent.agent_core import create_agent

def run_test():
    print("Creating agent...")
    agent = create_agent("test_session_123")
    
    user_requests = [
        "Add one Margherita Pizza to my cart.",
        "Show me my cart.",
        "Place my order under the name Ayushi."
    ]
    
    # We will accumulate messages here to maintain conversation history
    # across the sequential requests without using a persistent checkpointer.
    conversation_history = []
    
    for request in user_requests:
        print(f"\nUser: {request}\n")
        conversation_history.append(("user", request))
        
        inputs = {"messages": conversation_history}
        result = agent.invoke(inputs)
        
        returned_messages = result.get("messages", [])
        
        # Only check the newly generated messages in this turn for tool calls
        new_messages = returned_messages[len(conversation_history):]
        for msg in new_messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    print(f"[Tool Called]: {tc.get('name')} with arguments: {tc.get('args')}")
                    
        # The final assistant response is the last message
        final_message = returned_messages[-1]
        print(f"\nAssistant: {final_message.content}")
        print("\n" + "="*50)
        
        # Update our history with the complete returned sequence to pass to the next turn
        conversation_history = returned_messages

if __name__ == "__main__":
    run_test()
