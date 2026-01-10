#!/usr/bin/env python3
"""Fix imports in all new ingest scripts"""
import re
import os

files = [
    'research/data_ingest/ingest_fema_disasters.py',
    'research/data_ingest/ingest_storm_events.py',
    'research/data_ingest/ingest_drought.py',
    'research/data_ingest/ingest_census_permits.py',
    'research/data_ingest/ingest_bts_aviation.py',
    'research/data_ingest/ingest_scfi_freight.py'
]

for filepath in files:
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        
        # Remove the problematic import block
        content = re.sub(
            r'# Add project root for imports\s*\nsys\.path\.append\([^)]+\)\s*\nfrom research\.common import runtime_config as rc\s*\n',
            '',
            content
        )
        
        # Replace rc.require_real_mode with require_real_mode
        content = content.replace('rc.require_real_mode', 'require_real_mode')
        
        # Replace rc.log_mode with print
        content = re.sub(
            r'rc\.log_mode\(["\']([^"\']+)["\']\)',
            r'print(f"[{METIS_MODE}] \1")',
            content
        )
        
        # Add METIS_MODE and require_real_mode function after imports
        import_section_end = content.find('\nload_dotenv()')
        if import_section_end != -1:
            helper_code = '''
# Check METIS_MODE for real vs dev mode
METIS_MODE = os.getenv("METIS_MODE", "DEV")

def require_real_mode(source: str):
    """Only run in REAL mode, skip in DEV mode"""
    if METIS_MODE != "REAL":
        print(f"[DEV MODE] Skipping {source}")
        return False
    return True
'''
            content = content[:import_section_end] + helper_code + content[import_section_end:]
        
        with open(filepath, 'w') as f:
            f.write(content)
        
        print(f"✓ Fixed {filepath}")
    except Exception as e:
        print(f"✗ Error fixing {filepath}: {e}")

print("\nAll files updated!")
