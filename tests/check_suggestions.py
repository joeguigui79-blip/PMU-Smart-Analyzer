import httpx, json
from collections import Counter

r = httpx.get('http://localhost:8000/api/courses/1/suggestions', timeout=30)
data = r.json()
print('gagnant:', data['gagnant']['nom'], data['gagnant']['num_pmu'])
print('place:', data['place']['nom'], data['place']['num_pmu'])
if data['couple']:
    for i, h in enumerate(data['couple']):
        print('couple[' + str(i) + ']:', h['nom'], h['num_pmu'])
if data['tierce']:
    for i, h in enumerate(data['tierce']):
        print('tierce[' + str(i) + ']:', h['nom'], h['num_pmu'])
if data['deux_sur_quatre']:
    for i, h in enumerate(data['deux_sur_quatre']):
        print('d4[' + str(i) + ']:', h['nom'], h['num_pmu'])
