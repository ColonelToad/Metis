import requests
from requests.auth import HTTPBasicAuth

auth = HTTPBasicAuth('ChrisO', 'Tolugenius78@1')
r = requests.get('https://www.movebank.org/movebank/service/direct-read', 
                 params={'entity_type': 'study'}, 
                 auth=auth)

print(f'Status: {r.status_code}')
print(f'Content-Type: {r.headers.get("Content-Type")}')
print('\nFirst 500 chars:')
print(r.text[:500])
