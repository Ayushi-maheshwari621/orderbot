import csv
import os

def inspect_csv(file_path, num_rows=5):
    print(f"--- Inspecting {file_path} ---")
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return
        
    file_size = os.path.getsize(file_path)
    print(f"File size: {file_size / (1024*1024):.2f} MB")
    
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            print("File is empty.")
            return
            
        print("\nColumns:")
        for i, h in enumerate(headers):
            print(f"  {i}: {h}")
            
        print("\nSample Rows:")
        for _ in range(num_rows):
            try:
                row = next(reader)
                print(" | ".join(row))
            except StopIteration:
                break
                
        # Estimate row count by counting lines efficiently
        # Since restaurant-menus.csv is large, we can just do a quick count
        print("\nCounting total rows... (this might take a few seconds for large files)")
        f.seek(0)
        # Skip header
        next(f)
        row_count = sum(1 for _ in f)
        print(f"Approximate row count: {row_count}")

print("====================================")
inspect_csv('data/raw/restaurants.csv', 5)
print("====================================")
inspect_csv('data/raw/restaurant-menus.csv', 5)
