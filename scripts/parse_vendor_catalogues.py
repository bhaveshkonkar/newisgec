import sys
sys.path.insert(0, 'app')
import requests

with open('D:\\gearbox-selector\\.env') as f:
    for line in f:
        if line.startswith('GROQ_API_KEY'):
            key = line.split('=', 1)[1].strip().strip('"').strip("'")
            break

headers = {'X-Internal-Token': key, 'Content-Type': 'application/json'}

docs = [
    ('29de1d97-1a82-4ded-bd2c-2920e38da314', 'Elecon_G_B_EON-Series.pdf'),
    ('97d922b0-c1fe-4b07-875b-97a4b986adda', 'Premium_helical_gearboxes_catalogue.pdf'),
]

sys_id = '00000000-0000-0000-0000-000000000001'

for doc_id, storage_path in docs:
    payload = {'project_id': sys_id, 'storage_path': storage_path, 'file_name': storage_path}
    r = requests.post('http://127.0.0.1:8000/api/pdf/parse', json=payload, headers=headers, timeout=180)
    print(f'{doc_id}: {r.status_code}')
    if r.status_code != 200:
        print(r.text)