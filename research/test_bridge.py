"""
Bridge between Tauri and test_coordinator
Provides async test invocation via Python subprocess
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional


async def run_test_suite(suite_id: str) -> Dict[str, Any]:
    """Start a test suite asynchronously via coordinator"""
    try:
        result = await _call_coordinator("run_suite", {"suite_id": suite_id})
        return result
    except Exception as e:
        return {"error": str(e)}


async def list_test_suites() -> Dict[str, Any]:
    """Get list of available test suites"""
    try:
        result = await _call_coordinator("list_suites", {})
        return {"suites": result}
    except Exception as e:
        return {"error": str(e)}


async def get_test_status(run_id: str) -> Dict[str, Any]:
    """Get status of a running test"""
    try:
        result = await _call_coordinator("get_status", {"run_id": run_id})
        return result
    except Exception as e:
        return {"error": str(e)}


async def get_test_results(run_id: str) -> Dict[str, Any]:
    """Get results of a completed test"""
    try:
        result = await _call_coordinator("get_results", {"run_id": run_id})
        return result
    except Exception as e:
        return {"error": str(e)}


async def get_active_tests() -> Dict[str, Any]:
    """Get list of currently running tests"""
    try:
        result = await _call_coordinator("get_active", {})
        return {"tests": result}
    except Exception as e:
        return {"error": str(e)}


async def _call_coordinator(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Call test coordinator via Python subprocess"""
    project_root = Path(__file__).parent.parent
    
    python_code = f"""
import sys
sys.path.insert(0, r'{project_root}')
from research.test_coordinator import TestCoordinator
import json

coordinator = TestCoordinator()

try:
    if '{method}' == 'run_suite':
        result = coordinator.run_suite('{params.get("suite_id", "")}')
        print(json.dumps({{"run_id": result}}))
    elif '{method}' == 'list_suites':
        result = coordinator.list_suites()
        print(json.dumps(result))
    elif '{method}' == 'get_status':
        result = coordinator.get_test_status('{params.get("run_id", "")}')
        print(json.dumps(result))
    elif '{method}' == 'get_results':
        result = coordinator.get_test_results('{params.get("run_id", "")}')
        print(json.dumps(result))
    elif '{method}' == 'get_active':
        result = coordinator.get_active_tests()
        print(json.dumps(result))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
    sys.exit(1)
"""
    
    try:
        result = subprocess.run(
            [sys.executable, "-c", python_code],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project_root),
        )
        
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            return {"error": result.stderr}
    
    except subprocess.TimeoutExpired:
        return {"error": "Coordinator request timeout"}
    except json.JSONDecodeError:
        return {"error": f"Invalid coordinator response: {result.stdout}"}
    except Exception as e:
        return {"error": str(e)}
