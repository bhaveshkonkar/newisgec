import sys, json, requests
sys.path.insert(0, 'app')

with open('D:\\gearbox-selector\\.env') as f:
    for line in f:
        if line.startswith('GROQ_API_KEY'):
            key = line.split('=', 1)[1].strip().strip('"').strip("'")
            break

headers = {'X-Internal-Token': key, 'Content-Type': 'application/json'}

# Test with selection and documents - longer prompt
payload = {
    'question': 'What are the specs for B3-315?',
    'selection': {
        'model': 'B3-315-HN-HB-FAN',
        'power_kw': 252,
        'required_kw': 160,
        'ratio_iN': 25.6,
        'n1_rpm': 1500,
        'n2_actual': 58.59,
        'thermal_kw_effective': None,
        'warnings': []
    },
    'documents': [
        {'document_id': '97d922b0-c1fe-4b07-875b-97a4b986adda', 'file_name': 'Premium helical gearboxes catalogue.pdf', 'page_count': 95}
    ],
    'history': []
}

r = requests.post('http://127.0.0.1:8000/api/gearbox/explain', json=payload, headers=headers, timeout=60)
print(f'Status: {r.status_code}')
data = r.json()
print(f'Answer: {data.get("answer", "")[:500]}')
print(f'Citations: {json.dumps(data.get("citations", []), indent=2)}')
print(f'Degraded: {data.get("degraded")}')
print(f'Reason: {data.get("reason")}')