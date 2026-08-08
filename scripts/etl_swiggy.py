import csv
import os
import sys
import html
import time
import sqlite3
import argparse

# Add parent directory to path so we can import from db
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.database import get_connection, initialize_database

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'raw', 'swiggy.csv')
BATCH_SIZE = 100000

def parse_price(price_str):
    if not price_str:
        return None
    try:
        return float(price_str.strip())
    except ValueError:
        return None

def parse_rating(rating_str):
    r = rating_str.strip()
    if not r or r == '--':
        return None
    try:
        return float(r)
    except ValueError:
        return None

def parse_veg(veg_str):
    v = veg_str.strip().lower()
    if v == 'veg':
        return True
    elif v == 'non-veg':
        return False
    return None

def run_etl(limit=None):
    print("Initializing database schema...")
    initialize_database()
    
    print("Clearing existing menu data to ensure idempotency (orders are protected)...")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # Safely clear the tables we are about to populate, leaving 'orders' alone.
    cursor.execute("DELETE FROM menu_items")
    cursor.execute("DELETE FROM restaurants")
    conn.commit()
    
    if not os.path.exists(CSV_PATH):
        print(f"Error: {CSV_PATH} not found.")
        sys.exit(1)
        
    print(f"Starting streaming ETL from {CSV_PATH}")
    start_time = time.time()
    
    total_processed = 0
    menu_items_inserted = 0
    skipped_invalid_price = 0
    skipped_malformed = 0
    
    restaurant_batch = []
    menu_batch = []
    
    # We will track seen restaurant IDs in memory to reduce redundant SQLite INSERT OR IGNORE calls.
    # A set of 60,000-100,000 IDs takes negligible memory (< 10MB).
    seen_restaurants = set()
    
    try:
        with open(CSV_PATH, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            
            # Skip header
            try:
                next(reader)
            except StopIteration:
                print("CSV is empty.")
                return
                
            for row in reader:
                if limit is not None and total_processed >= limit:
                    break
                
                total_processed += 1
                
                # Check for malformed rows (expecting at least 17 columns based on inspection)
                if len(row) < 17:
                    skipped_malformed += 1
                    continue
                    
                # 0: city, 1: city link, 2: subcity, 3: subcity link, 4: restaurant code
                # 5: restaurant, 6: rating, 7: rating count, 8: cost, 9: address
                # 10: cuisine, 11: licension no, 12: restaurant link, 13: menu
                # 14: item, 15: price, 16: veg_or_non_veg
                
                restaurant_id = row[4].strip()
                if not restaurant_id:
                    skipped_malformed += 1
                    continue
                
                # --- PRICE VALIDATION ---
                price = parse_price(row[15])
                if price is None:
                    skipped_invalid_price += 1
                    continue
                    
                # --- RESTAURANT DEDUPLICATION & BATCHING ---
                if restaurant_id not in seen_restaurants:
                    r_name = html.unescape(row[5].strip())
                    city = html.unescape(row[0].strip())
                    subcity = html.unescape(row[2].strip())
                    address = html.unescape(row[9].strip())
                    cuisine = html.unescape(row[10].strip())
                    rating = parse_rating(row[6])
                    rating_count = row[7].strip()
                    cost_for_two = html.unescape(row[8].strip())
                    license_no = row[11].strip()
                    restaurant_link = row[12].strip()
                    
                    restaurant_batch.append((
                        restaurant_id, r_name, city, subcity, address, cuisine,
                        rating, rating_count, cost_for_two, license_no, restaurant_link,
                        None, None # latitude and longitude are explicitly NULL
                    ))
                    seen_restaurants.add(restaurant_id)
                
                # --- MENU ITEM BATCHING ---
                m_name = html.unescape(row[14].strip())
                m_category = html.unescape(row[13].strip())
                is_veg = parse_veg(row[16])
                
                menu_batch.append((
                    restaurant_id, m_name, m_category, price, is_veg, 'INR'
                ))
                
                # --- BATCH INSERTION ---
                if len(menu_batch) >= BATCH_SIZE:
                    execute_batches(conn, cursor, restaurant_batch, menu_batch)
                    menu_items_inserted += len(menu_batch)
                    restaurant_batch.clear()
                    menu_batch.clear()
                    
                    # Log progress
                    print(f"Processed: {total_processed:,} | "
                          f"Restaurants seen: {len(seen_restaurants):,} | "
                          f"Menu items inserted: {menu_items_inserted:,} | "
                          f"Skipped invalid prices: {skipped_invalid_price:,}")
            
            # Process remaining rows
            if menu_batch:
                execute_batches(conn, cursor, restaurant_batch, menu_batch)
                menu_items_inserted += len(menu_batch)
                
    except Exception as e:
        print(f"ETL failed during execution: {e}")
    finally:
        conn.close()
        
    elapsed = time.time() - start_time
    print("\n" + "="*40)
    print("ETL COMPLETED")
    print("="*40)
    print(f"Total rows processed: {total_processed:,}")
    print(f"Unique restaurants inserted: {len(seen_restaurants):,}")
    print(f"Menu items inserted: {menu_items_inserted:,}")
    print(f"Rows skipped because of invalid/missing price: {skipped_invalid_price:,}")
    print(f"Rows skipped/malformed: {skipped_malformed:,}")
    print(f"Elapsed time: {elapsed:.2f} seconds")

def execute_batches(conn, cursor, restaurant_batch, menu_batch):
    # Use INSERT OR IGNORE just in case a duplicate slipped through or was already in DB
    if restaurant_batch:
        cursor.executemany('''
            INSERT OR IGNORE INTO restaurants (
                id, name, city, subcity, address, cuisine, rating, 
                rating_count, cost_for_two, license_no, restaurant_link, 
                latitude, longitude
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', restaurant_batch)
    
    if menu_batch:
        cursor.executemany('''
            INSERT INTO menu_items (
                restaurant_id, name, category, price, is_veg, currency
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', menu_batch)
    
    # Commit the transaction block
    conn.commit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Swiggy ETL")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N rows")
    args = parser.parse_args()
    
    run_etl(limit=args.limit)
