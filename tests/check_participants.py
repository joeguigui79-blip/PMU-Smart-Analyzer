import httpx, json
from collections import Counter

r = httpx.get('http://localhost:8000/api/courses/1', timeout=30)
data = r.json()
participants = data['participants']
print('Total participants:', len(participants))
print('Top 5 by score:')
for p in participants[:5]:
    print('  #' + str(p['num_pmu']) + ' ' + p['nom'] + ' - score=' + str(round(p['score_global'], 1)) + ', id=' + str(p['id']))
# Check for duplicate num_pmu
nums = [p['num_pmu'] for p in participants]
dups = {k: v for k, v in Counter(nums).items() if v > 1}
print('Duplicate num_pmu:', dups)
# Check for duplicate IDs
ids = [p['id'] for p in participants]
dup_ids = {k: v for k, v in Counter(ids).items() if v > 1}
print('Duplicate participant IDs:', dup_ids)
