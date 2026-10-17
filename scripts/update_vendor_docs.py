import sys
sys.path.insert(0, 'app')
import engine, json, requests

c = engine._conn()
cur = c.cursor()

with open('D:\\gearbox-selector\\.env') as f:
    for line in f:
        if line.startswith('GROQ_API_KEY'):
            key = line.split('=', 1)[1].strip().strip('"').strip("'")
            break

headers = {'X-Internal-Token': key, 'Content-Type': 'application/json'}
sys_id = '00000000-0000-0000-0000-000000000001'

docs = [
    ('29de1d97-1a82-4ded-bd2c-2920e38da314', 'Elecon_G_B_EON-Series.pdf', 1),
    ('97d922b0-c1fe-4b07-875b-97a4b986adda', 'Premium_helical_gearboxes_catalogue.pdf', 3),
]

for doc_id, storage_path, vendor_id in docs:
    payload = {'project_id': sys_id, 'storage_path': storage_path, 'file_name': storage_path}
    r = requests.post('http://127.0.0.1:8000/api/pdf/parse', json=payload, headers=headers, timeout=180)
    data = r.json()
    pages = data.get('pages', [])
    text = data.get('text', '')
    page_count = data.get('page_count')
    
    print(f'{doc_id}: pages={len(pages)}, text_len={len(text)}, page_count={page_count}')
    
    # Update document
    cur.execute('''
        UPDATE isgec.documents 
        SET status=%s, page_count=%s, extracted_text=%s, metadata=%s 
        WHERE id=%s
    ''', ['parsed', page_count, text, json.dumps({'vendor_id': vendor_id}), doc_id])
    
    # Insert pages
    if pages:
        cur.execute('DELETE FROM isgec.document_pages WHERE document_id=%s', [doc_id])
        for p in pages:
            cur.execute('''
                INSERT INTO isgec.document_pages (document_id, page_no, char_count, text)
                VALUES (%s, %s, %s, %s)
            ''', [doc_id, p['page_no'], p.get('char_count', len(p['text'])), p['text']])

c.commit()
print('Done')