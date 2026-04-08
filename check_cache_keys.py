import json
import os
from pathlib import Path

path = r'C:\cli\PROJECT\부동산\data\address_cache.json'
with open(path, 'r', encoding='utf-8') as f:
    cache = json.load(f)

keys = list(cache.keys())
print("Cache Sample Keys:")
for k in keys[:10]:
    print(f"'{k}'")
