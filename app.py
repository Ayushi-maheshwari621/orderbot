import streamlit as st
import uuid
import re
import json
from streamlit_geolocation import streamlit_geolocation
from agent.agent_core import create_agent, reset_search_cache
from agent.tools import _USER_LOCATIONS, set_user_gps_location, set_user_location
from agent import tools as agent_tools
from agent.geocoder import reverse_geocode
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

def render_restaurant_results(results: list):
    """
    Render a list of structured restaurant dicts as polished cards.
    Source of truth: name, rating, city, distance_km, cuisine, cost_for_two.
    """
    if not results:
        return

    # Sort results by distance ascending if distance_km is available
    sorted_results = sorted(
        results,
        key=lambda x: (x.get("distance_km") is None, x.get("distance_km") or 999999)
    )

    cards_html = []
    for r in sorted_results:
        name = r.get("name") or "Restaurant"
        cuisine = (r.get("cuisine") or "").strip()
        rating = r.get("rating")
        cost = (r.get("cost_for_two") or "").strip()
        dist = r.get("distance_km")
        city = (r.get("city") or "").strip()

        if cost and not str(cost).startswith("₹"):
            cost = f"₹{cost}"

        rating_html = f'<div class="resto-rating-badge">⭐ {rating}</div>' if rating and str(rating) != "–" else ""
        
        loc_html = ""
        if dist is not None:
            loc_html = f'<div class="resto-tag">📍 {dist} km away</div>'
        elif city:
            loc_html = f'<div class="resto-tag">📍 {city}</div>'
        
        cuisine_html = f'<div class="resto-tag">🍴 {cuisine}</div>' if cuisine else ""
        cost_html = f'<div class="resto-tag">💰 {cost} for two</div>' if cost else ""

        cards_html.append(
            f'<div class="restaurant-card">'
            f'<div class="restaurant-header">'
            f'<div class="restaurant-name">🍽️ {name}</div>'
            f'{rating_html}'
            f'</div>'
            f'<div class="restaurant-grid">'
            f'{loc_html}'
            f'{cuisine_html}'
            f'{cost_html}'
            f'</div>'
            f'</div>'
        )
    if cards_html:
        st.markdown("".join(cards_html), unsafe_allow_html=True)

# Alias for backwards compatibility
render_restaurant_cards = render_restaurant_results


def render_menu_results(dishes: list):
    """
    Render a list of structured dish dicts as polished food/dish cards.
    Displays: Dish Name, Price, Category, 🟢 VEG / 🔴 NON-VEG badge.
    """
    if not dishes:
        return

    cards_html = []
    for d in dishes:
        name = d.get("name") or "Dish Item"
        price = d.get("price")
        category = (d.get("category") or "").strip()
        is_veg = d.get("is_veg", 1)
        
        price_str = f"₹{price:.2f}" if isinstance(price, (int, float)) else (f"₹{price}" if price and not str(price).startswith("₹") else str(price or ""))
        
        # Check non-veg keywords if is_veg boolean is missing or 0
        is_nonveg = (is_veg == 0) or any(kw in name.lower() for kw in ['chicken', 'mutton', 'egg', 'fish', 'prawn', 'meat', 'non veg'])
        badge_icon = "🔴" if is_nonveg else "🟢"
        badge_text = "NON-VEG" if is_nonveg else "VEG"
        badge_class = "nonveg-badge" if is_nonveg else "veg-badge"
        
        cat_html = f'<span class="menu-tag" style="background: rgba(255, 255, 255, 0.06); color: #94A3B8; font-size: 0.78rem; font-weight: 700; padding: 3px 10px; border-radius: 12px;">{category}</span>' if category else ""
        
        cards_html.append(
            f'<div class="menu-item-card" style="background: #121620; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; padding: 16px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.2);">'
            f'<div class="menu-item-info" style="display: flex; flex-direction: column; gap: 6px;">'
            f'<div style="display: flex; align-items: center; gap: 8px;">'
            f'<span class="menu-badge {badge_class}" style="font-size: 0.8rem; font-weight: 800;">{badge_icon} {badge_text}</span>'
            f'{cat_html}'
            f'</div>'
            f'<div class="menu-item-name" style="font-family: \'Plus Jakarta Sans\', sans-serif; font-size: 1.05rem; font-weight: 700; color: #F8FAFC;">🍽️ {name}</div>'
            f'</div>'
            f'<div class="menu-item-price" style="font-family: \'Plus Jakarta Sans\', sans-serif; font-size: 1.15rem; font-weight: 800; color: #FF6B35; background: rgba(255, 107, 53, 0.12); padding: 6px 14px; border-radius: 12px;">{price_str}</div>'
            f'</div>'
        )

    if cards_html:
        st.markdown("".join(cards_html), unsafe_allow_html=True)


def parse_text_restaurants(content: str) -> list:
    """Extract restaurant info from text format if structured tool output isn't directly cached."""
    restos = []
    lines = content.split('\n')
    for line in lines:
        stripped = line.strip()
        m = re.match(r'^\d+\.\s+\*?\*?([^\(\*\-]+?)\*?\*?(?:\s*\((.*?)\))?\s*[\-\–]\s*(.*)$', stripped)
        if m:
            name = m.group(1).strip()
            city = m.group(2).strip() if m.group(2) else ''
            rest = m.group(3).strip()
            rating_m = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*(?:/\s*5|\s*stars?|\s*rating)', rest, re.IGNORECASE)
            rating = rating_m.group(1) if rating_m else None
            cost_m = re.search(r'(?:₹\s*([0-9]+(?:\.[0-9]+)?)|([0-9]+(?:\.[0-9]+)?)\s*for\s*two)', rest, re.IGNORECASE)
            cost = cost_m.group(0) if cost_m else None
            dist_m = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*km', rest, re.IGNORECASE)
            dist = dist_m.group(1) if dist_m else None
            cuisine = None
            for part in rest.split(','):
                part = part.strip()
                if not any(kw in part.lower() for kw in ['away', 'km', 'for two', 'rating', '/5', '₹']):
                    cuisine = part
            restos.append({
                'name': name,
                'city': city,
                'rating': rating,
                'cost_for_two': cost,
                'distance_km': dist,
                'cuisine': cuisine
            })
    return restos


def parse_text_dishes(content: str) -> list:
    """Extract dishes from text format if structured tool output isn't directly cached."""
    dishes = []
    lines = content.split('\n')
    for line in lines:
        stripped = line.strip()
        m = re.match(r'^(?:\d+\.|\-)\s+\*?\*?([^\*\(\-\–\:]+?)\*?\*?(?:\s*[\(\-\–\:]\s*₹?\s*([0-9]+(?:\.[0-9]+)?)\)?)(.*)$', stripped)
        if m:
            name = m.group(1).strip()
            price = m.group(2).strip()
            extra = m.group(3).strip(' ()')
            is_nonveg = any(kw in name.lower() for kw in ['chicken', 'mutton', 'egg', 'fish', 'prawn', 'meat', 'non veg'])
            try:
                price_val = float(price)
            except Exception:
                price_val = price
            dishes.append({
                'name': name,
                'price': price_val,
                'is_veg': 0 if is_nonveg else 1,
                'category': extra if extra else 'Menu Item'
            })
    return dishes


def render_formatted_message(content: str, session_id: str | None = None, structured_data: dict | None = None):
    """
    Renders the assistant response with visual card treatment for restaurant listings, menu items,
    cart summaries, and order confirmations while suppressing raw markdown tables.
    """
    if not content:
        return

    # Clean any markdown code block wrappers
    content = re.sub(r'```html\s*', '', content, flags=re.IGNORECASE)
    content = re.sub(r'```\s*', '', content)

    # 1. Order Confirmation Detection
    is_order_success = any(kw in content.lower() for kw in ['order placed', 'order id', 'order created', 'order confirmed', 'successfully placed'])
    if is_order_success:
        card_html = f'<div class="order-success-card"><div class="order-success-header">🎉 Order Successfully Placed!</div><div class="order-success-body">{content}</div><div><span class="order-delivery-pill">⚡ Est. Delivery: ~30-40 mins</span></div></div>'
        st.markdown(card_html, unsafe_allow_html=True)
        return

    # 2. Cart Summary Response Detection
    is_cart_summary = any(kw in content.lower() for kw in ['items in your cart', 'your cart currently', 'cart summary', 'here is your cart'])
    if is_cart_summary and '<div' not in content:
        card_html = f'<div class="sidebar-loc-card" style="border-color: rgba(255, 107, 53, 0.4); margin-bottom: 14px;"><div class="sidebar-loc-status" style="color: #FF6B35;">🛒 Live Cart Overview</div><div style="font-size: 0.95rem; color: #F8FAFC;">{content}</div></div>'
        st.markdown(card_html, unsafe_allow_html=True)
        return

    # 3. Direct HTML Detection: content already has card markup from a previous render pass
    if '<div class="menu-item-card"' in content or '<div class="restaurant-card"' in content or '<div class="' in content:
        clean_lines = []
        for line in content.split('\n'):
            clean_lines.append(line.strip() if line.strip().startswith('<') else line)
        st.markdown("\n".join(clean_lines), unsafe_allow_html=True)
        return

    # 4. Check for structured menu data (PRIORITIZED for menu requests)
    menu_results = []
    if structured_data and structured_data.get("menu"):
        menu_results = structured_data["menu"]
    elif getattr(st.session_state, "active_menu_results", None):
        menu_results = st.session_state.active_menu_results

    if menu_results:
        intro_lines = []
        for line in content.split('\n'):
            stripped = line.strip()
            if (stripped.startswith('|') or 
                re.match(r'^[\-_=]{3,}$', stripped) or 
                re.match(r'^[\d]+\.\s+', stripped) or 
                re.match(r'^[-\*]\s+', stripped) or
                stripped.lower().startswith('price:') or
                stripped.lower().startswith('category:') or
                any(kw in stripped.lower() for kw in ['would you like to order', 'search for something else', 'add anything', 'more items', 'please note that'])):
                continue
            intro_lines.append(line)
        intro_text = '\n'.join(intro_lines).strip()
        if intro_text:
            st.markdown(intro_text)
        else:
            st.markdown("### 🍽️ Menu Items")
        render_menu_results(menu_results)
        
        outro_lines = [l for l in content.split('\n') if any(kw in l.lower() for kw in ['would you like to order', 'search for something else', 'add anything', 'more items', 'order from'])]
        outro_text = '\n'.join(outro_lines).strip()
        if outro_text:
            st.markdown(outro_text)
        return

    # 5. Check for structured restaurant data
    resto_results = []
    if structured_data and structured_data.get("restaurants"):
        resto_results = structured_data["restaurants"]
    elif getattr(st.session_state, "active_restaurant_results", None):
        resto_results = st.session_state.active_restaurant_results

    if resto_results:
        intro_lines = []
        for line in content.split('\n'):
            stripped = line.strip()
            if (stripped.startswith('|') or 
                re.match(r'^[\-_=]{3,}$', stripped) or 
                re.match(r'^[\d]+\.\s+', stripped) or 
                re.match(r'^[-\*]\s+', stripped) or
                stripped.lower().startswith('cuisine:') or 
                stripped.lower().startswith('rating:') or 
                stripped.lower().startswith('cost for two:') or 
                stripped.lower().startswith('distance:') or
                stripped.lower().startswith('cost:') or
                stripped.startswith('*Cuisine*') or
                stripped.startswith('*Rating*') or
                stripped.startswith('*Cost') or
                stripped.startswith('*Distance*') or
                any(kw in stripped.lower() for kw in ['which one', 'like to order', 'help you with'])):
                continue
            intro_lines.append(line)
        intro_text = '\n'.join(intro_lines).strip()
        if intro_text:
            st.markdown(intro_text)
        else:
            st.markdown("### 🍽️ Nearby Restaurants")
        render_restaurant_results(resto_results)
        
        outro_lines = [l for l in content.split('\n') if any(kw in l.lower() for kw in ['which one', 'like to order', 'help you with', 'ready to order'])]
        outro_text = '\n'.join(outro_lines).strip()
        if outro_text:
            st.markdown(outro_text)
        return

    # 6. Fallback text parsing if structured state was empty but text contains numbered menu dishes list
    parsed_dishes = parse_text_dishes(content)
    if len(parsed_dishes) >= 2:
        intro_lines = [l for l in content.split('\n') if not re.match(r'^(?:\d+\.|\-)', l.strip()) and not any(kw in l.lower() for kw in ['would you like to order', 'search for something else', 'add anything', 'please note'])]
        outro_lines = [l for l in content.split('\n') if any(kw in l.lower() for kw in ['would you like to order', 'search for something else', 'add anything', 'more items', 'order from'])]
        intro_text = '\n'.join(intro_lines).strip()
        outro_text = '\n'.join(outro_lines).strip()
        if intro_text:
            st.markdown(intro_text)
        render_menu_results(parsed_dishes)
        if outro_text:
            st.markdown(outro_text)
        return

    # 7. Fallback text parsing if structured state was empty but text contains numbered restaurant list
    parsed_restos = parse_text_restaurants(content)
    if len(parsed_restos) >= 2:
        intro_lines = [l for l in content.split('\n') if not re.match(r'^\d+\.', l.strip()) and not any(kw in l.lower() for kw in ['which one', 'like to order', 'help you with'])]
        outro_lines = [l for l in content.split('\n') if any(kw in l.lower() for kw in ['which one', 'like to order', 'help you with', 'ready to order'])]
        intro_text = '\n'.join(intro_lines).strip()
        outro_text = '\n'.join(outro_lines).strip()
        if intro_text:
            st.markdown(intro_text)
        render_restaurant_results(parsed_restos)
        if outro_text:
            st.markdown(outro_text)
        return

    # 8. Fallback standard Markdown rendering
    st.markdown(content)


def init_app():
    st.set_page_config(page_title="OrderBot - AI Food Delivery", page_icon="🍽️", layout="centered")

    # Custom CSS for OrderBot Swiggy/Zomato-inspired Dark Aesthetic
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

    /* Hide Streamlit Default Elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stApp > header {background-color: transparent !important;}
    
    /* Scrollbar Polish */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    ::-webkit-scrollbar-track {
        background: #0B0E14;
    }
    ::-webkit-scrollbar-thumb {
        background: #222735;
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #FF6B35;
    }

    /* Main Container Padding */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 3rem !important;
        max-width: 920px !important;
    }

    /* Deep Obsidian Dark theme background */
    .stApp {
        background-color: #0B0E14 !important;
        background-image: radial-gradient(circle at 50% 0%, rgba(255, 107, 53, 0.08) 0%, transparent 60%) !important;
        color: #F8FAFC !important;
        font-family: 'Plus Jakarta Sans', 'Inter', -apple-system, sans-serif !important;
    }

    /* Sidebar customization */
    section[data-testid="stSidebar"] {
        background-color: #0E121A !important;
        border-right: 1px solid rgba(255, 255, 255, 0.08) !important;
    }
    section[data-testid="stSidebar"] hr {
        border-color: rgba(255, 255, 255, 0.08) !important;
    }
    section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {
        color: #F8FAFC !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-weight: 800 !important;
        letter-spacing: -0.3px !important;
    }

    /* Top Header Bar */
    .orderbot-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 1.3rem 1.8rem;
        background: #121620;
        border-radius: 22px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        margin-bottom: 2rem;
        transition: all 0.3s ease;
    }
    .orderbot-header:hover {
        border-color: rgba(255, 107, 53, 0.4);
        box-shadow: 0 12px 36px rgba(255, 107, 53, 0.12);
    }

    .orderbot-logo-box {
        display: flex;
        align-items: center;
        gap: 14px;
    }

    .orderbot-logo-icon {
        font-size: 2.5rem;
        line-height: 1;
        filter: drop-shadow(0 4px 8px rgba(255, 107, 53, 0.4));
    }

    .orderbot-title-text {
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-size: 1.95rem;
        font-weight: 800;
        background: linear-gradient(135deg, #FF6B35 0%, #FF9F1C 50%, #FFBF69 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
        line-height: 1.1;
        letter-spacing: -0.6px;
    }

    .orderbot-subtext {
        font-size: 0.85rem;
        font-weight: 500;
        color: #94A3B8;
        margin: 4px 0 0 0;
    }

    .header-badges-container {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .badge-loc {
        background: rgba(255, 159, 28, 0.12);
        border: 1px solid rgba(255, 159, 28, 0.3);
        color: #FF9F1C;
        padding: 8px 16px;
        border-radius: 30px;
        font-size: 0.85rem;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .badge-cart {
        background: linear-gradient(135deg, #FF6B35 0%, #E85A24 100%);
        color: #FFFFFF;
        padding: 8px 18px;
        border-radius: 30px;
        font-size: 0.85rem;
        font-weight: 700;
        box-shadow: 0 4px 16px rgba(255, 107, 53, 0.35);
        display: flex;
        align-items: center;
        gap: 6px;
    }

    /* Hero Craving Section */
    .hero-banner {
        background: linear-gradient(135deg, rgba(255, 107, 53, 0.12) 0%, rgba(255, 159, 28, 0.05) 100%);
        border: 1px solid rgba(255, 107, 53, 0.25);
        border-radius: 24px;
        padding: 2.2rem;
        margin-bottom: 2rem;
        text-align: center;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
    }

    .hero-title {
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-size: 1.9rem;
        font-weight: 800;
        color: #F8FAFC;
        margin-bottom: 0.5rem;
        letter-spacing: -0.5px;
    }

    .hero-desc {
        color: #94A3B8;
        font-size: 1rem;
        margin: 0;
        font-weight: 400;
        line-height: 1.5;
    }

    /* Restaurant Card Styling */
    .restaurant-card {
        background: #121620;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 18px;
        padding: 20px;
        margin: 14px 0;
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.3);
        transition: all 0.25s ease;
    }

    .restaurant-card:hover {
        border-color: #FF6B35;
        transform: translateY(-3px);
        box-shadow: 0 12px 28px rgba(255, 107, 53, 0.18);
    }

    .restaurant-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
    }

    .restaurant-name {
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-size: 1.25rem;
        font-weight: 800;
        color: #F8FAFC;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .restaurant-badge {
        background: rgba(46, 196, 182, 0.12);
        border: 1px solid rgba(46, 196, 182, 0.3);
        color: #2EC4B6;
        font-size: 0.75rem;
        font-weight: 700;
        padding: 4px 12px;
        border-radius: 20px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .restaurant-details {
        font-size: 0.92rem;
        color: #94A3B8;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .restaurant-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 12px;
    }

    .resto-tag {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
        padding: 6px 10px;
        font-size: 0.82rem;
        font-weight: 600;
        color: #CBD5E1;
        display: flex;
        align-items: center;
        gap: 6px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex-shrink: 0;
    }

    .resto-rating-badge {
        background: rgba(255, 159, 28, 0.15);
        border: 1px solid rgba(255, 159, 28, 0.35);
        color: #FF9F1C;
        font-size: 0.8rem;
        font-weight: 800;
        padding: 4px 10px;
        border-radius: 20px;
        display: inline-flex;
        align-items: center;
        gap: 4px;
    }

    /* Menu Item Card Styling */
    .menu-item-card {
        background: #0E121A;
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 16px;
        padding: 16px 20px;
        margin: 12px 0;
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: all 0.25s ease;
    }
    
    .menu-item-card:hover {
        background: #121620;
        border-color: rgba(255, 107, 53, 0.35);
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.2);
    }

    .menu-item-info {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .menu-item-name {
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-weight: 700;
        font-size: 1.02rem;
        color: #F8FAFC;
    }

    .menu-item-price {
        font-weight: 800;
        font-size: 1.1rem;
        color: #F8FAFC;
        background: rgba(255, 255, 255, 0.07);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 4px 14px;
        border-radius: 14px;
    }

    .menu-badge {
        font-size: 0.72rem;
        font-weight: 800;
        padding: 4px 10px;
        border-radius: 8px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .veg-badge {
        background: rgba(46, 196, 182, 0.15);
        color: #2EC4B6;
        border: 1px solid rgba(46, 196, 182, 0.3);
    }

    .nonveg-badge {
        background: rgba(239, 68, 68, 0.15);
        color: #F87171;
        border: 1px solid rgba(239, 68, 68, 0.3);
    }

    /* Sidebar Cart Panel */
    .sidebar-cart-card {
        background: #121620;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 18px;
        padding: 18px;
        margin-top: 16px;
        margin-bottom: 16px;
        box-shadow: 0 6px 16px rgba(0,0,0,0.3);
    }

    .cart-item-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }
    .cart-item-row:last-child {
        border-bottom: none;
    }

    .cart-item-name {
        font-size: 0.95rem;
        font-weight: 600;
        color: #F8FAFC;
    }

    .cart-item-qty {
        font-size: 0.85rem;
        color: #F8FAFC;
        background: #1E2430;
        padding: 2px 8px;
        border-radius: 6px;
        margin-left: 8px;
        font-weight: 700;
    }

    .cart-item-price {
        font-size: 0.95rem;
        font-weight: 800;
        color: #F8FAFC;
    }

    .cart-total-box {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding-top: 14px;
        margin-top: 10px;
        border-top: 2px dashed rgba(255, 255, 255, 0.12);
        font-size: 1.15rem;
        font-weight: 800;
        color: #F8FAFC;
    }

    /* Sidebar Location Status Card */
    .sidebar-loc-card {
        background: #121620;
        border: 1px solid rgba(255, 159, 28, 0.3);
        border-radius: 16px;
        padding: 14px 16px;
        margin-bottom: 16px;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
    }
    .sidebar-loc-status {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.78rem;
        font-weight: 800;
        color: #FF9F1C;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 4px;
    }
    .sidebar-loc-text {
        font-size: 0.95rem;
        font-weight: 700;
        color: #F8FAFC;
        word-break: break-word;
    }

    .cart-empty-card {
        text-align: center;
        padding: 32px 18px;
        background: #121620;
        border-radius: 20px;
        border: 1px dashed rgba(255, 255, 255, 0.14);
        margin-top: 16px;
    }
    .cart-empty-icon {
        font-size: 2.8rem;
        margin-bottom: 8px;
        filter: drop-shadow(0 4px 12px rgba(255, 107, 53, 0.25));
    }
    .cart-empty-title {
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-size: 1.1rem;
        font-weight: 800;
        color: #F8FAFC;
        margin-bottom: 6px;
    }
    .cart-empty-sub {
        font-size: 0.85rem;
        color: #94A3B8;
        line-height: 1.4;
    }

    /* Order Success Card */
    .order-success-card {
        background: linear-gradient(135deg, rgba(46, 196, 182, 0.14) 0%, rgba(16, 185, 129, 0.06) 100%);
        border: 1px solid rgba(46, 196, 182, 0.4);
        border-radius: 22px;
        padding: 26px;
        margin: 20px 0;
        box-shadow: 0 12px 36px rgba(46, 196, 182, 0.18);
        text-align: center;
        position: relative;
        overflow: hidden;
    }

    .order-success-header {
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-size: 1.65rem;
        font-weight: 800;
        color: #2EC4B6;
        margin-bottom: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        letter-spacing: -0.4px;
    }

    .order-success-body {
        color: #F8FAFC;
        font-size: 1.05rem;
        line-height: 1.65;
    }

    .order-delivery-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: rgba(255, 159, 28, 0.15);
        border: 1px solid rgba(255, 159, 28, 0.35);
        color: #FF9F1C;
        font-size: 0.85rem;
        font-weight: 800;
        padding: 6px 16px;
        border-radius: 20px;
        margin-top: 14px;
    }

    /* Checkout Card Layout & Styling */
    .checkout-card {
        background: #121620;
        border: 1px solid rgba(255, 107, 53, 0.45);
        border-radius: 22px;
        padding: 24px;
        margin-top: 16px;
        box-shadow: 0 14px 40px rgba(0, 0, 0, 0.5);
    }

    .checkout-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 18px;
        padding-bottom: 14px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }

    .checkout-card-title {
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-size: 1.3rem;
        font-weight: 800;
        color: #F8FAFC;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .checkout-secure-badge {
        background: rgba(46, 196, 182, 0.12);
        border: 1px solid rgba(46, 196, 182, 0.3);
        color: #2EC4B6;
        font-size: 0.75rem;
        font-weight: 800;
        padding: 4px 12px;
        border-radius: 20px;
    }

    .checkout-section-header {
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-size: 0.9rem;
        font-weight: 800;
        color: #FF9F1C;
        text-transform: uppercase;
        letter-spacing: 0.6px;
        margin: 18px 0 8px 0;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .required-star {
        color: #F87171;
        font-weight: 800;
        margin-left: 2px;
    }

    .checkout-summary-box {
        background: #0E121A;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 16px;
        margin-bottom: 16px;
    }

    .checkout-summary-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.92rem;
        color: #CBD5E1;
        padding: 5px 0;
    }

    .checkout-total-banner {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: linear-gradient(135deg, rgba(255, 107, 53, 0.18) 0%, rgba(232, 90, 36, 0.08) 100%);
        border: 1px solid rgba(255, 107, 53, 0.35);
        border-radius: 16px;
        padding: 14px 18px;
        margin: 18px 0;
    }

    .checkout-total-label {
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-size: 1.05rem;
        font-weight: 800;
        color: #F8FAFC;
    }

    .checkout-total-amount {
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-size: 1.35rem;
        font-weight: 800;
        color: #FF6B35;
        background: rgba(255, 107, 53, 0.18);
        padding: 4px 14px;
        border-radius: 12px;
    }

    /* Streamlit Chat Message Styling Overrides */
    .stChatMessage {
        background-color: #121620 !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 22px !important;
        padding: 18px 22px !important;
        margin-bottom: 1.3rem !important;
        box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25) !important;
    }

    /* User Message Styling */
    .stChatMessage[data-testid="stChatMessageUser"] {
        background: linear-gradient(135deg, #1A202C 0%, #121620 100%) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        color: #F8FAFC !important;
        border-bottom-right-radius: 4px !important;
    }

    /* Assistant Message Styling */
    .stChatMessage[data-testid="stChatMessageAssistant"] {
        background: #121620 !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-left: 3px solid #FF6B35 !important;
        border-bottom-left-radius: 4px !important;
        box-shadow: 0 8px 24px rgba(255, 107, 53, 0.08) !important;
    }

    /* Streamlit Container Border Overrides inside Sidebar */
    div[data-testid="stSidebar"] div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #121620 !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 16px !important;
    }

    /* Avatar styling */
    .stChatMessage .st-em {
        font-size: 1.4rem !important;
    }

    /* Streamlit Inputs and Buttons */
    div.stButton > button {
        background-color: #1A202C !important;
        color: #F8FAFC !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 14px !important;
        padding: 10px 18px !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 0.92rem !important;
        font-weight: 700 !important;
        transition: all 0.25s ease !important;
        width: 100% !important;
    }

    div.stButton > button:hover {
        background-color: #FF6B35 !important;
        border-color: #FF6B35 !important;
        color: #FFFFFF !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 20px rgba(255, 107, 53, 0.35) !important;
    }
    
    /* Primary Button Styling */
    div.stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #FF6B35 0%, #E85A24 100%) !important;
        color: #FFFFFF !important;
        border: none !important;
        box-shadow: 0 6px 18px rgba(255, 107, 53, 0.35) !important;
    }
    div.stButton > button[kind="primary"]:hover {
        box-shadow: 0 8px 24px rgba(255, 107, 53, 0.45) !important;
        transform: translateY(-2px) !important;
    }

    /* Text Input Styling */
    .stTextInput input {
        background-color: #121620 !important;
        color: #F8FAFC !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        border-radius: 14px !important;
        padding: 12px 16px !important;
        font-family: 'Inter', sans-serif !important;
    }
    .stTextInput input:focus {
        border-color: #FF6B35 !important;
        box-shadow: 0 0 0 2px rgba(255, 107, 53, 0.4) !important;
    }

    /* Chat Input Bar */
    .stChatInputContainer {
        border-radius: 18px !important;
        border: 1px solid rgba(255, 255, 255, 0.14) !important;
        background-color: #121620 !important;
        padding: 6px !important;
        box-shadow: 0 10px 30px rgba(0,0,0,0.4) !important;
    }

    .stChatInputContainer:focus-within {
        border-color: #FF6B35 !important;
        box-shadow: 0 0 0 2px rgba(255, 107, 53, 0.4), 0 10px 30px rgba(255,107,53,0.2) !important;
    }
    
    .stChatInputContainer textarea {
        color: #F8FAFC !important;
        font-family: 'Inter', sans-serif !important;
    }

    /* Footer */
    .orderbot-footer {
        text-align: center;
        color: #64748B;
        font-size: 0.85rem;
        padding: 2.5rem 0 1.5rem 0;
        margin-top: 3.5rem;
        font-weight: 500;
        letter-spacing: 0.3px;
    }
    .orderbot-footer b {
        color: #94A3B8;
    }
    
    /* Toast/Alerts & Spinners */
    .stAlert {
        border-radius: 14px !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25) !important;
    }

    /* Streamlit Spinner Polish */
    div[data-testid="stSpinner"] > div {
        border-top-color: #FF6B35 !important;
    }

    /* Mobile / Responsive Layout Polish */
    @media (max-width: 640px) {
        .block-container {
            padding-top: 1rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
        .orderbot-header {
            flex-direction: column;
            align-items: flex-start;
            gap: 12px;
            padding: 1.2rem;
        }
        .header-badges-container {
            width: 100%;
            justify-content: space-between;
        }
        .restaurant-grid {
            grid-template-columns: repeat(2, 1fr) !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    # Initialize a unique session_id for this user session
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex

    # Initialize agent and message history in session state
    if "agent" not in st.session_state:
        st.session_state.agent = create_agent(st.session_state.session_id)

    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "last_order_confirmation" not in st.session_state:
        st.session_state.last_order_confirmation = None    

    # Get current location & cart state for Header & Sidebar
    current_loc = _USER_LOCATIONS.get(st.session_state.session_id)
    loc_display = "Unknown"
    if current_loc:
        if current_loc.get("raw_query") == "Device GPS":
            loc_display = f"GPS ({current_loc['latitude']:.2f}, {current_loc['longitude']:.2f})"
        else:
            loc_display = current_loc.get("raw_query", "Location Set")

    cart_info = agent_tools.view_cart(st.session_state.session_id)
    cart_count = cart_info.get("item_count", 0) if isinstance(cart_info, dict) and cart_info.get("status") == "success" else 0

    selected_chip = None

    # 1. Top Header Component
    st.markdown(f"""
    <div class="orderbot-header">
        <div class="orderbot-logo-box">
            <div class="orderbot-logo-icon">🍽️</div>
            <div>
                <h1 class="orderbot-title-text">OrderBot</h1>
                <p class="orderbot-subtext">AI Restaurant & Food Ordering Assistant</p>
            </div>
        </div>
        <div class="header-badges-container">
            <div class="badge-loc">📍 {loc_display}</div>
            <div class="badge-cart">🛒 Cart ({cart_count})</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 2. Hero Section
    st.markdown("""
    <div class="hero-banner">
        <div class="hero-title">What are you craving today? 🍕🍔</div>
        <p class="hero-desc">Ask OrderBot to discover local restaurants, check live menus, manage your cart, and place orders.</p>
    </div>
    """, unsafe_allow_html=True)

    # 3. Sidebar Location & Cart Panel
    with st.sidebar:
        st.subheader("📍 Location")
        
        if current_loc:
            loc_name = current_loc.get("raw_query", "Location Set")
            if loc_name == "Device GPS":
                loc_name = f"GPS ({current_loc['latitude']:.4f}, {current_loc['longitude']:.4f})"
            st.markdown(f"""
            <div class="sidebar-loc-card">
                <div class="sidebar-loc-status">🟢 Active Location</div>
                <div class="sidebar-loc-text">📍 {loc_name}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="sidebar-loc-card" style="border-color: rgba(248, 113, 113, 0.3);">
                <div class="sidebar-loc-status" style="color: #F87171;">⚠️ Location Not Set</div>
                <div class="sidebar-loc-text" style="color: #94A3B8;">Set your location to see nearby restaurants</div>
            </div>
            """, unsafe_allow_html=True)

        st.caption("📡 **Option 1: Device GPS**")
        loc_res = streamlit_geolocation()
        if loc_res and loc_res.get('latitude') and loc_res.get('longitude'):
            lat, lon = loc_res['latitude'], loc_res['longitude']
            if not current_loc or current_loc.get("latitude") != lat or current_loc.get("longitude") != lon:
                with st.spinner("Finding your city..."):
                    rev_res = reverse_geocode(lat, lon)
                    city = rev_res.get("city") if rev_res else None
                    set_user_gps_location(st.session_state.session_id, lat, lon, "Device GPS", city)
                st.rerun()

        st.caption("✏️ **Option 2: Enter Address Manually**")
        manual_loc = st.text_input("Delivery Address / City", placeholder="e.g. Connaught Place, Delhi", label_visibility="collapsed", key="sidebar_loc_input")
        if st.button("📍 Set Location", key="btn_set_loc_sidebar", use_container_width=True) and manual_loc:
            with st.spinner("Geocoding location..."):
                res = set_user_location(st.session_state.session_id, manual_loc)
                if res["status"] == "success":
                    st.rerun()
                else:
                    st.error(res["message"])

        st.divider()
        
        # Shopping Cart Section
        st.subheader(f"🛒 Your Cart ({cart_count})")
        
        # Read live cart state from tools.py
        if isinstance(cart_info, dict) and cart_info.get("status") == "success" and cart_info.get("items"):
            items = cart_info["items"]
            total = cart_info.get("total", 0.0)
            
            for item in items:
                dish = item.get("dish", {})
                name = dish.get("name", "Dish Item")
                price = dish.get("price", 0.0)
                qty = item.get("quantity", 1)
                subtotal = item.get("subtotal", 0.0)
                dish_id = dish.get("id")
                restaurant_id = dish.get("restaurant_id")
                
                # Fetch restaurant name
                restaurant_name = "Unknown Restaurant"
                if restaurant_id:
                    resto = agent_tools.get_restaurant_by_id(str(restaurant_id))
                    if resto and isinstance(resto, dict):
                        restaurant_name = resto.get("name", "Unknown Restaurant")

                with st.container(border=True):
                    st.write(f"**{name}**")
                    st.caption(f"🏪 {restaurant_name}")
                    col1, col2 = st.columns([5, 3])
                    with col1:
                        st.write(f"{qty}× ₹{price:.2f} = **₹{subtotal:.2f}**")
                    with col2:
                        if st.button("🗑️", key=f"remove_{dish_id}", use_container_width=True, help="Remove item"):
                            agent_tools.remove_from_cart(st.session_state.session_id, dish_id)
                            st.rerun()
            
            # Cart Summary Breakdown (Subtotal, Delivery Fee, Total)
            subtotal_amt = total
            delivery_fee = 0.00
            grand_total = subtotal_amt + delivery_fee

            st.markdown(f"""
            <div class="checkout-summary-box" style="margin-top: 14px; margin-bottom: 14px;">
                <div class="checkout-summary-row"><span>Subtotal</span><span style="font-weight:700;">₹{subtotal_amt:.2f}</span></div>
                <div class="checkout-summary-row"><span>Delivery Fee</span><span style="color:#2EC4B6; font-weight:700;">FREE</span></div>
                <div class="checkout-total-banner" style="margin-top: 10px; margin-bottom: 0;">
                    <span class="checkout-total-label">Grand Total</span>
                    <span class="checkout-total-amount">₹{grand_total:.2f}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if not st.session_state.get("show_checkout_form", False):
                if st.button("🛍️ Checkout / Place Order", key="btn_sidebar_checkout", type="primary", use_container_width=True):
                    st.session_state.show_checkout_form = True
                    st.rerun()
            else:
                st.markdown("""
                <div class="checkout-card">
                    <div class="checkout-card-header">
                        <div class="checkout-card-title">🛍️ Express Checkout</div>
                        <div class="checkout-secure-badge">🔒 256-Bit Secure</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Live Order Summary Breakdown
                summary_rows = "".join([
                    f'<div class="checkout-summary-row"><span>{it.get("quantity",1)}× {it.get("dish",{}).get("name","Item")}</span><span style="font-weight:700;">₹{it.get("subtotal",0.0):.2f}</span></div>'
                    for it in items
                ])
                st.markdown(f"""
                <div class="checkout-summary-box">
                    <div style="font-weight:700; font-size:0.8rem; color:#94A3B8; margin-bottom:8px; text-transform:uppercase; letter-spacing:0.5px;">Order Items ({len(items)})</div>
                    {summary_rows}
                </div>
                """, unsafe_allow_html=True)

                st.markdown('<div class="checkout-section-header">👤 Contact Details <span class="required-star">*</span></div>', unsafe_allow_html=True)
                name = st.text_input("Full Name *", placeholder="e.g. Ayushi Maheshwari", key="co_name")
                phone = st.text_input("Mobile Number *", placeholder="e.g. 9876543210 or +91 9876543210", key="co_phone")

                st.markdown('<div class="checkout-section-header">📍 Delivery Location <span class="required-star">*</span></div>', unsafe_allow_html=True)
                address = st.text_input("Delivery Address *", placeholder="e.g. Flat 102, Green Park", key="co_addr")
                
                col_city, col_state = st.columns(2)
                with col_city:
                    city = st.text_input("City *", placeholder="e.g. Delhi", key="co_city")
                with col_state:
                    state = st.text_input("State *", placeholder="e.g. Delhi", key="co_state")
                    
                col_pin, col_dummy = st.columns(2)
                with col_pin:
                    pincode = st.text_input("Pincode *", placeholder="e.g. 110016", key="co_pin")

                instructions = st.text_input("Delivery Instructions (Optional)", placeholder="e.g. Leave at door", key="co_instr")

                st.markdown('<div class="checkout-section-header">💳 Payment Method <span class="required-star">*</span></div>', unsafe_allow_html=True)
                payment = st.radio(
                    "Payment Method", 
                    ["💵 Cash on Delivery", "💳 Online Payment — Coming Soon"], 
                    index=0, 
                    key="checkout_payment_radio"
                )
                
                if payment == "💳 Online Payment — Coming Soon":
                    st.info("ℹ️ Online payment is coming soon. Please select Cash on Delivery.")

                # Delivery Location and Restaurant Distance Check
                current_loc = _USER_LOCATIONS.get(st.session_state.session_id)
                active_city = (current_loc.get("city") or current_loc.get("raw_query") or "").strip() if current_loc else ""
                is_mismatch = bool(active_city and active_city.lower() != "unknown" and city.strip() and active_city.lower() != city.strip().lower())

                resto_dist_km = None
                resto_name = "Restaurant"
                if items:
                    first_dish = items[0].get("dish", {})
                    resto_id = first_dish.get("restaurant_id")
                    if resto_id:
                        resto_info = agent_tools.get_restaurant_by_id(resto_id)
                        if resto_info:
                            resto_name = resto_info.get("name", "Restaurant")
                            r_lat = resto_info.get("latitude")
                            r_lon = resto_info.get("longitude")
                            if r_lat is not None and r_lon is not None and current_loc:
                                u_lat = current_loc.get("latitude")
                                u_lon = current_loc.get("longitude")
                                if u_lat is not None and u_lon is not None:
                                    try:
                                        resto_dist_km = agent_tools.haversine_distance(float(u_lat), float(u_lon), float(r_lat), float(r_lon))
                                    except Exception:
                                        pass

                is_too_far = bool(resto_dist_km is not None and resto_dist_km > 25.0)
                confirm_distance = True
                if is_too_far:
                    st.warning(f"📍 **Distance Alert**: **{resto_name}** is **{resto_dist_km:.1f} km** away from your location. Standard delivery zone is up to 25 km.")
                    confirm_distance = st.checkbox("I acknowledge this distance and wish to proceed with the order", key="confirm_dist_chk")
                elif resto_dist_km is not None:
                    st.markdown(f'<div style="color: #94A3B8; font-size: 0.85rem; margin-bottom: 8px;">📍 <b>{resto_name}</b> is <b>{resto_dist_km:.2f} km</b> from your location.</div>', unsafe_allow_html=True)

                confirm_loc = True
                if is_mismatch:
                    st.warning(f"⚠️ Your active location is **{active_city.title()}**, but your delivery address is in **{city.strip().title()}**. Do you want to place the order for **{city.strip().title()}**?")
                    confirm_loc = st.checkbox(f"Yes, confirm delivery to {city.strip().title()}", key="confirm_delivery_loc_mismatch_chk")

                col_cancel, col_submit = st.columns([1, 2])
                with col_cancel:
                    cancel = st.button("Cancel", key="btn_checkout_cancel", use_container_width=True)
                with col_submit:
                    submit = st.button("🚀 Place Order", key="btn_checkout_submit", type="primary", use_container_width=True)

                if submit:
                    clean_phone = phone.strip().replace(" ", "").replace("-", "")
                    phone_valid = bool(re.match(r'^(?:\+91)?[6-9]\d{9}$', clean_phone))
                    pin_valid = bool(re.match(r'^\d{6}$', pincode.strip()))

                    if not name.strip():
                        st.error("⚠️ Please enter your Full Name.")
                    elif not phone_valid:
                        st.error("⚠️ Please enter a valid 10-digit Indian Mobile Number.")
                    elif not address.strip():
                        st.error("⚠️ Please enter your Delivery Address.")
                    elif not city.strip():
                        st.error("⚠️ Please enter your City.")
                    elif not state.strip():
                        st.error("⚠️ Please enter your State.")
                    elif not pin_valid:
                        st.error("⚠️ Please enter a valid 6-digit Pincode.")
                    elif payment == "💳 Online Payment — Coming Soon":
                        st.error("⚠️ Online payment is coming soon. Please select Cash on Delivery.")
                    elif is_too_far and not confirm_distance:
                        st.error(f"⚠️ Delivery distance ({resto_dist_km:.1f} km) is outside the standard delivery area. Please check the distance confirmation box to proceed.")
                    elif is_mismatch and not confirm_loc:
                        st.error(f"⚠️ Active location is {active_city.title()}, but delivery address is {city.strip().title()}. Please check the confirmation box above to proceed.")
                    else:
                        order_res = agent_tools.place_order(st.session_state.session_id, customer_name=name.strip())
                        if order_res.get("status") == "success":
                            order_id = order_res.get("order_id", "N/A")
                            total_val = order_res.get("total", grand_total)
                            instr_str = (
                                f"\n• **Instructions**: {instructions.strip()}"
                                if instructions.strip()
                                else ""
                            )

                            success_msg = (
                                f"🎉 **Order placed successfully!**\n\n"
                                f"• **Order ID**: #{order_id}\n"
                                f"• **Customer**: {name.strip()} ({phone.strip()})\n"
                                f"• **Delivery Address**: "
                                f"{address.strip()}, {city.strip()}, {state.strip()} - {pincode.strip()}"
                                f"{instr_str}\n"
                                f"• **Payment Method**: 💵 Cash on Delivery\n"
                                f"• **Total Amount**: ₹{total_val:.2f}"
                            )

                            # Persist confirmation independently of cart state
                            st.session_state.last_order_confirmation = success_msg
                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": success_msg,
                                "structured": None
                            })

                            # Close checkout after successful order
                            st.session_state.show_checkout_form = False

                            st.rerun()
                        else:
                            st.error(order_res.get("message", "Failed to place order."))
                if cancel:
                    st.session_state.show_checkout_form = False
                    st.rerun()
        else:
            st.markdown("""
            <div class="cart-empty-card">
                <div class="cart-empty-icon">🍽️</div>
                <div class="cart-empty-title">Your cart is empty</div>
                <div class="cart-empty-sub">Discover local restaurants & add delicious dishes to get started!</div>
            </div>
            """, unsafe_allow_html=True)

    if st.session_state.get("last_order_confirmation"):
        st.success(
            st.session_state.last_order_confirmation,
            icon="🎉"
        )
        

    # 4. Display Existing Chat History
    for item in st.session_state.messages:
        if isinstance(item, tuple):
            role, content = item
            if role in ["user", "assistant"] and content:
                avatar = "👤" if role == "user" else "🤖"
                with st.chat_message(role, avatar=avatar):
                    if role == "assistant":
                        render_formatted_message(content, st.session_state.session_id)
                    else:
                        st.markdown(content)
        elif isinstance(item, dict):
            role = item.get("role", "assistant")
            content = item.get("content", "")
            structured = item.get("structured", None)
            avatar = "👤" if role == "user" else "🤖"
            with st.chat_message(role, avatar=avatar):
                if role == "assistant":
                    render_formatted_message(content, st.session_state.session_id, structured_data=structured)
                else:
                    st.markdown(content)
        elif isinstance(item, HumanMessage):
            if item.content and not item.content.startswith("[System:"):
                with st.chat_message("user", avatar="👤"):
                    st.markdown(item.content)
        elif isinstance(item, AIMessage):
            if item.content:
                with st.chat_message("assistant", avatar="🤖"):
                    render_formatted_message(item.content, st.session_state.session_id)

    # 5. Quick Suggestion Chips above input
    st.write("**Quick suggestions:**")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("🍕 Find pizza", key="chip_pizza"):
            selected_chip = "Find pizza restaurants near me"
    with col2:
        if st.button("🍔 Find burgers", key="chip_burgers"):
            selected_chip = "Find burger restaurants near me"
    with col3:
        if st.button("⭐ Top rated", key="chip_top"):
            selected_chip = "Show me the top rated restaurants"
    with col4:
        if st.button("💰 Under ₹300", key="chip_budget"):
            selected_chip = "Find food items under 300 rupees"

    # Determine user input source (typed input, chip button click, or checkout CTA click)
    chat_input = st.chat_input("Ask OrderBot to search food, menus, or manage cart...")
    user_input = selected_chip if selected_chip else chat_input

    # 6. Handle New User Input
    if user_input:
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        st.session_state.messages.append({"role": "user", "content": user_input})

        current_loc = _USER_LOCATIONS.get(st.session_state.session_id)
        loc_str = current_loc.get("raw_query", "Unknown") if current_loc else "Unknown"
        
        trimmed_history = [
            SystemMessage(content=f"Context: The user's current location is set to '{loc_str}'.")
        ]
        
        # Keep past messages for LLM context
        for msg in st.session_state.messages[-5:-1]:
            if isinstance(msg, dict):
                r, c = msg.get("role"), msg.get("content", "")
                if r == "user":
                    trimmed_history.append(HumanMessage(content=c))
                elif r == "assistant":
                    trimmed_history.append(AIMessage(content=c))
            elif isinstance(msg, tuple):
                r, c = msg
                if r == "user":
                    trimmed_history.append(HumanMessage(content=c))
                elif r == "assistant":
                    trimmed_history.append(AIMessage(content=c))
            elif isinstance(msg, HumanMessage):
                if msg.content and not msg.content.startswith("[System:"):
                    trimmed_history.append(msg)
            elif isinstance(msg, AIMessage):
                if msg.content:
                    trimmed_history.append(msg)
        
        trimmed_history.append(HumanMessage(content=user_input))
        inputs = {"messages": trimmed_history}

        # Dynamic spinner label based on user intent
        _ui = user_input.lower()
        if any(kw in _ui for kw in ["near me", "nearby", "find restaurant", "find pizza", "find burger", "find food", "restaurants"]):
            _spinner_msg = "🔎 Finding restaurants near you..."
        elif any(kw in _ui for kw in ["menu", "dishes", "food items", "what do they serve"]):
            _spinner_msg = "🍽️ Fetching the menu..."
        elif any(kw in _ui for kw in ["cart", "add", "remove", "order", "checkout", "place order", "buy"]):
            _spinner_msg = "🛒 Updating your cart..."
        else:
            _spinner_msg = "🤖 OrderBot is thinking..."

        res_messages = []
        invocation_error = None
        try:
            with st.spinner(_spinner_msg):
                result = st.session_state.agent.invoke(inputs)
            res_messages = result.get("messages", [])
        except Exception as e:
            invocation_error = e
            print("=== AGENT INVOCATION EXCEPTION ===", e)

        # Extract final content from agent output
        final_content = ""
        found_restaurants = None
        found_menu = None
        is_cart_op = False

        def _extract_text(c):
            if isinstance(c, str):
                return c.strip()
            if isinstance(c, list):
                parts = []
                for p in c:
                    if isinstance(p, str):
                        parts.append(p)
                    elif isinstance(p, dict) and "text" in p:
                        parts.append(p["text"])
                return "".join(parts).strip()
            return str(c or "").strip()

        for m in res_messages:
            tool_name = getattr(m, "name", "")
            if tool_name in ["add_to_cart", "remove_from_cart", "view_cart", "clear_cart", "place_order"]:
                is_cart_op = True

            if type(m).__name__ == "ToolMessage" or isinstance(m, ToolMessage):
                c = getattr(m, "content", "")
                if isinstance(c, str) and c.strip().startswith("[") and c.strip().endswith("]"):
                    try:
                        parsed_json = json.loads(c)
                        if isinstance(parsed_json, list) and len(parsed_json) > 0 and isinstance(parsed_json[0], dict):
                            if "cuisine" in parsed_json[0] or "cost_for_two" in parsed_json[0]:
                                found_restaurants = parsed_json
                            elif "price" in parsed_json[0] or "dish_id" in parsed_json[0]:
                                found_menu = parsed_json
                    except Exception:
                        pass
            elif type(m).__name__ == "AIMessage" or isinstance(m, AIMessage):
                c = getattr(m, "content", "")
                extracted = _extract_text(c)
                if extracted:
                    final_content = extracted

        structured_data = {}
        if not is_cart_op:
            if found_menu:
                structured_data["menu"] = found_menu
            elif found_restaurants:
                structured_data["restaurants"] = found_restaurants

        if not final_content:
            if structured_data.get("menu"):
                final_content = "🍽️ Here are the menu items:"
            elif structured_data.get("restaurants"):
                final_content = "🍽️ Here are the restaurants found:"
            elif invocation_error:
                err_str = str(invocation_error).lower()
                if "rate_limit" in err_str or "429" in err_str or "tpm" in err_str:
                    final_content = "⚠️ OrderBot is currently experiencing high demand (rate limit reached). Please wait a few seconds and try your request again."
                else:
                    final_content = "I couldn't get a response from the service right now. Please try again."
            else:
                final_content = "I have processed your request. How else can I help you with your order?"

        # Save into session state
        st.session_state.messages.append({
            "role": "assistant",
            "content": final_content,
            "structured": structured_data if structured_data else None
        })

        with st.chat_message("assistant", avatar="🤖"):
            render_formatted_message(final_content, st.session_state.session_id, structured_data=structured_data)
        st.rerun()

    # 7. Footer Component
    st.markdown("""
    <div class="orderbot-footer">
        Powered by <b>OrderBot AI</b> • Premium Food Delivery Assistant
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    init_app()
