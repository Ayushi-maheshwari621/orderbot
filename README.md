# 🍽️ OrderBot — AI Food Ordering Assistant

> An AI-powered food ordering assistant that helps users discover nearby restaurants, explore menus, manage their cart, and place food orders through natural language.

## 🚀 Overview

OrderBot is an AI-driven food ordering application built with **Python, Streamlit, LangChain, and Gemini**.

Instead of navigating through multiple screens, users can simply chat with OrderBot:

- "Find pizza restaurants near me"
- "Show me the menu of Pizza Hut"
- "Add 1 capsicum pizza to my cart"
- "Show me burger restaurants"
- "Place my order"

OrderBot understands the user's intent, calls the appropriate tools, retrieves restaurant/menu information, and manages the ordering workflow.

---

## ✨ Features

### 🤖 AI-Powered Conversational Ordering
Interact with OrderBot using natural language instead of manually navigating the application.

### 📍 Location-Based Restaurant Search
- Device GPS support
- Manual location input
- Nearby restaurant discovery
- Distance calculation and sorting

### 🍴 Restaurant Discovery
Search restaurants based on:
- Cuisine
- Food category
- Location
- Rating
- Budget

### 📋 Live Menu Exploration
Users can ask for a restaurant's menu and explore available dishes with prices and categories.

### 🛒 Smart Cart Management
Users can:
- Add items to cart
- Manage quantities
- View cart contents
- Remove items
- Calculate order totals

### 📦 Order Placement
Complete the ordering flow by providing:
- Customer details
- Delivery address
- City/state
- Pincode
- Delivery instructions

### 💵 Cash on Delivery
Cash on Delivery is currently supported.

> Online payment is marked as **Coming Soon** because a payment gateway has not yet been integrated.

### ⚡ Tool-Based AI Architecture
The AI agent can invoke backend tools for:
- Restaurant search
- Menu retrieval
- Cart operations
- Location handling
- Order processing

---

## 🏗️ Tech Stack

| Technology | Purpose |
|------------|---------|
| Python | Core application |
| Streamlit | Web interface |
| LangChain | AI agent orchestration |
| Gemini | LLM |
| SQLite | Local database |
| Pandas | Data processing |
| Geolocation | Location-based search |
| dotenv | Environment configuration |

---

## 🧠 Architecture

```text
                    ┌─────────────────────┐
                    │      User           │
                    │ Natural Language    │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │    Streamlit UI     │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   LangChain Agent   │
                    │   + Gemini LLM      │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
        Restaurant         Menu Tools       Cart/Order
          Search                              Tools
              │                │                │
              └────────────────┼────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   SQLite / Dataset  │
                    └─────────────────────┘