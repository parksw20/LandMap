import json
import os

path = r'C:\cli\PROJECT\부동산\data\2025\geojson\실거래_202511_v2512072311_apt_lite.geojson'

with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for feature in data['features']:
    name = feature['properties'].get('name', '')
    if '이지더원' in name or '붓들마을' in name:
        print(json.dumps(feature['properties'], ensure_ascii=False, indent=2))
