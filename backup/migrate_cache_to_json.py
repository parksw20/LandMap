import pickle
import json
from pathlib import Path
import sys

# Hardcoded path for convenience or passed as arg
target_dir = Path("x:/HDD1/Study/부동산/data/2025")

pkl_path = target_dir / "address_cache.pkl"
json_path = target_dir / "address_cache.json"

if pkl_path.exists():
    print(f"Loading {pkl_path}...")
    try:
        with open(pkl_path, "rb") as f:
            data = pickle.load(f)
        
        print(f"Loaded {len(data)} items. Saving to {json_path}...")
        
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                print(f"Merging with existing {len(existing)} items...")
                existing.update(data)
                data = existing
            except Exception as e:
                print(f"Error reading existing JSON: {e}. Overwriting.")
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("Migration complete.")
    except Exception as e:
        print(f"Error during migration: {e}")
else:
    print(f"No pickle file found at {pkl_path}")
