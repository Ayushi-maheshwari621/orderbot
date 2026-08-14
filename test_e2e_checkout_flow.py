import uuid
import time
from agent import tools as agent_tools
from agent.agent_core import create_agent, reset_search_cache
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

def test_cart_to_checkout_e2e():
    print("=== STARTING END-TO-END CART-TO-CHECKOUT FLOW TEST ===")
    session_id = uuid.uuid4().hex
    
    # 1. Set Location
    loc_res = agent_tools.set_user_location(session_id, "Connaught Place, Delhi")
    assert loc_res["status"] == "success", "Setting location failed"
    print("✓ Step 1: User location set to Connaught Place, Delhi")
    
    # 2. Add dish items to cart directly using valid dish IDs from search_menu
    dishes = agent_tools.search_menu("pizza")
    assert dishes and isinstance(dishes, list) and len(dishes) > 0, "No menu items found"
    target_dish = dishes[0]
    dish_id = target_dish["id"]
    dish_name = target_dish["name"]
    dish_price = target_dish["price"]
    
    # Track dish ID as valid for session
    from agent.agent_core import _SESSION_VALID_DISH_IDS
    _SESSION_VALID_DISH_IDS[session_id] = {dish_id}
    
    add_res = agent_tools.add_to_cart(session_id, dish_id, quantity=2)
    assert add_res["status"] == "success", f"Add to cart failed: {add_res}"
    print(f"✓ Step 2: Added 2x '{dish_name}' (ID: {dish_id}, ₹{dish_price}) to cart")
    
    # 3. View Cart & Verify items and total
    cart = agent_tools.view_cart(session_id)
    assert cart["status"] == "success", "View cart failed"
    assert cart["item_count"] == 2, f"Expected 2 items in cart, got {cart['item_count']}"
    expected_total = dish_price * 2
    assert abs(cart["total"] - expected_total) < 0.01, f"Expected total {expected_total}, got {cart['total']}"
    print(f"✓ Step 3: Cart contains 2 items, total ₹{cart['total']:.2f}")
    
    # 4. Simulate user filling checkout form
    customer_name = "Ayushi Maheshwari"
    phone = "+91 9876543210"
    address = "Flat 102, Green Park"
    city = "Delhi"
    pincode = "110016"
    payment = "Cash on Delivery"
    
    prompt = f"Place my order. My name is {customer_name}. Phone: {phone}. Delivery Address: {address}, {city}, {pincode}. Payment: {payment}."
    print(f"✓ Step 4: User submitted checkout form with prompt: '{prompt}'")
    
    # 5. Invoke agent with the checkout prompt
    agent = create_agent(session_id)
    reset_search_cache(session_id)
    
    messages = [
        SystemMessage(content="Context: The user's current location is set to 'Connaught Place, Delhi'."),
        ("user", prompt)
    ]
    
    result = agent.invoke({"messages": messages})
    response_messages = result.get("messages", [])
    
    # Find AIMessage response
    ai_response = None
    for msg in response_messages:
        if isinstance(msg, AIMessage) and msg.content:
            ai_response = msg.content
            print(f"\n[Agent Response]:\n{ai_response}\n")
            
    assert ai_response is not None, "Agent produced no response"
    
    # Check for order placed keywords
    if isinstance(ai_response, list):
        text_parts = [part.get("text", "") if isinstance(part, dict) else str(part) for part in ai_response]
        content_str = " ".join(text_parts)
    else:
        content_str = str(ai_response)
    content_lower = content_str.lower()
    has_success_keyword = any(kw in content_lower for kw in ['order placed', 'order id', 'order created', 'order confirmed', 'successfully placed'])
    assert has_success_keyword, f"Response missing order success confirmation: {ai_response}"
    print("✓ Step 5: Agent executed place_order and returned order confirmation with customer details")
    
    # 6. Verify cart is now empty
    cart_after = agent_tools.view_cart(session_id)
    assert cart_after["item_count"] == 0, f"Cart should be empty after order placement, but has {cart_after['item_count']} items"
    print("✓ Step 6: Cart is now empty after successful order placement")
    
    print("\n=== ALL E2E CHECKOUT FLOW TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    test_cart_to_checkout_e2e()
