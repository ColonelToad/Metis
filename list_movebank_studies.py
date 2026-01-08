import requests
from requests.auth import HTTPBasicAuth
import pandas as pd
from io import StringIO

auth = HTTPBasicAuth('ChrisO', 'Tolugenius78@1')

# Get all accessible studies
r = requests.get('https://www.movebank.org/movebank/service/direct-read', 
                 params={'entity_type': 'study'}, 
                 auth=auth)

if r.status_code == 200:
    df = pd.read_csv(StringIO(r.text))
    
    # Filter for studies with data access and recent activity
    accessible = df[(df['i_have_download_access'] == True) & (df['number_of_deployments'] > 0)]
    
    print(f"Found {len(accessible)} accessible studies with data")
    print("\nTop 10 studies by deployment count:")
    print(accessible[['id', 'name', 'number_of_deployments', 'number_of_individuals']].head(10))
