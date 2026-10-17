import sys, json, requests
sys.path.insert(0, 'app')

with open('D:\\gearbox-selector\\.env') as f:
    for line in f:
        if line.startswith('GROQ_API_KEY'):
            key = line.split('=', 1)[1].strip().strip('"').strip("'")
            break

headers = {'X-Internal-Token': key, 'Content-Type': 'application/json'}

# Test direct LLM call
payload = {
    'model': 'openai/gpt-oss-120b',
    'temperature': 0.2,
    'max_tokens': 1200,
    'messages': [
        {'role': 'system', 'content': 'You are a test assistant.'},
        {'role': 'user', 'content': 'Reply with OK'}
    ]
}

r = requests.post('https://api.groq.com/openai/v1/chat/completions', json=payload, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}, timeout=30)
print(f'Status: {r.status_code}')
print(f'Response: {json.dumps(r.json(), indent=2)[:500]}')