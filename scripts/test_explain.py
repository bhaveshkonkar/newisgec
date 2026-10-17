import sys, json, requests
sys.path.insert(0, 'app')

with open('D:\\gearbox-selector\\.env') as f:
    for line in f:
        if line.startswith('GROQ_API_KEY'):
            key = line.split('=', 1)[1].strip().strip('"').strip("'")
            break

headers = {'X-Internal-Token': key, 'Content-Type': 'application/json'}

# Test explain with vendor catalogue context
payload = {
    'question': 'What are the specs for B3-315?',
    'selection': None,
    'documents': [
        {'document_id': '97d922b0-c1fe-4b07-875b-97a4b986adda', 'file_name': 'Premium helical gearboxes catalogue.pdf', 'page_count': 95}
    ],
    'history': []
}

r = requests.post('http://127.0.0.1:8000/api/gearbox/explain', json=payload, headers=headers, timeout=60)
print(f'Status: {r.status_code}')
data = r.json()
print(f'Answer: {data.get("answer", "")[:300]}')
print(f'Citations: {json.dumps(data.get("citations", []), indent=2)}')
print(f'Degraded: {data.get("degraded")}')
print(f'Reason: {data.get("reason")}')