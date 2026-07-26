import json
import os

path = r'C:\cli\PROJECT\부동산\data\address_cache.json'
if os.path.exists(path):
    with open(path, 'r', encoding='utf-8') as f:
        cache = json.load(f)
    
    fixed_cache = {}
    count = 0
    for addr, coords in cache.items():
        if coords and len(coords) == 2 and coords[0] is not None and coords[1] is not None:
            try:
                c1, c2 = float(coords[0]), float(coords[1])
                if c1 < c2: # [37.x, 127.x] 순서라면
                    fixed_cache[addr] = [c2, c1]
                    count += 1
                else:
                    fixed_cache[addr] = [c1, c2]
            except (TypeError, ValueError):
                fixed_cache[addr] = coords
        else:
            fixed_cache[addr] = coords
            
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(fixed_cache, f, ensure_ascii=False, indent=2)
    print(f"Cache fixed: {count} addresses reordered.")
