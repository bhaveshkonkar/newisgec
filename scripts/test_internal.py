import sys
sys.path.insert(0, 'app')
import reasoning

# Same call as internal_api
pages = reasoning.load_document_pages([
    '97d922b0-c1fe-4b07-875b-97a4b986adda',
])

result = reasoning.answer_project_question(
    question='What are the specs for B3-315?',
    selection={
        'model': 'B3-315-HN-HB-FAN',
        'power_kw': 252,
        'required_kw': 160,
        'ratio_iN': 25.6,
        'n1_rpm': 1500,
        'n2_actual': 58.59,
        'thermal_kw_effective': None,
        'warnings': []
    },
    pages=pages,
    history=[]
)

print('Result:', result)
print('last_failure_reason:', reasoning.last_failure_reason)