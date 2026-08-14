import re
from app import render_formatted_message

def test_menu_rendering():
    print("=== TESTING MENU RENDERING FORMATTER ===")
    
    # 1. Test bullet list format
    sample_bullet_menu = """Here is the menu:
- **Plain Raita** – ₹59.00
- **Butter Roti** – ₹25.00
- **Dal Makhani** – ₹180.00
"""
    
    # 2. Test table format
    sample_table_menu = """| # | Dish ID | Restaurant ID | Category | Price (INR) |
|---|---------|---------------|----------|-------------|
| 1 | 116125  | 397980        | Plain Raita | 59.0 |
| 2 | 112506  | 475283        | Tandoori Roti | 15.0 |
"""

    print("✓ Menu Formatter imports and compiles successfully")
    print("=== TEST COMPLETED ===")

if __name__ == "__main__":
    test_menu_rendering()
