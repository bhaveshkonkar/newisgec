import sys
sys.path.insert(0, 'app')
import reasoning

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
    pages=[
        {'document_id': '97d922b0-c1fe-4b07-875b-97a4b986adda', 'file_name': 'Premium helical gearboxes catalogue.pdf', 'page_no': 1, 'text': 'B3-315 rated power 252 kW', 'paginated': True},
        {'document_id': '97d922b0-c1fe-4b07-875b-97a4b986adda', 'file_name': 'Premium helical gearboxes catalogue.pdf', 'page_no': 2, 'text': 'thermal capacity fan 150 kW', 'paginated': True},
    ],
    history=[]
)
print('Result:', result)