"""
Run test suites via subprocess and return results to Tauri
Wrapper around test_coordinator using subprocess model
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any
import asyncio


async def invoke_run_test_suite(suite_id: str) -> Dict[str, Any]:
    """Tauri command: Start a test suite"""
    return await _run_coordinator("run_suite", {"suite_id": suite_id})


async def invoke_list_test_suites() -> Dict[str, Any]:
    """Tauri command: List available test suites"""
    return await _run_coordinator("list_suites", {})


async def invoke_get_test_status(run_id: str) -> Dict[str, Any]:
    """Tauri command: Get test status"""
    return await _run_coordinator("get_status", {"run_id": run_id})


async def invoke_get_test_results(run_id: str) -> Dict[str, Any]:
    """Tauri command: Get test results"""
    return await _run_coordinator("get_results", {"run_id": run_id})


async def invoke_get_active_tests() -> Dict[str, Any]:
    """Tauri command: Get active tests"""
    return await _run_coordinator("get_active", {})


async def _run_coordinator(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call test coordinator in subprocess
    This allows long-running tests to execute without blocking Tauri
    """
    project_root = Path(__file__).parent.parent.parent
    
    python_code = f"""
import json
import sys
sys.path.insert(0, r'{project_root}')

from research.test_coordinator import TestCoordinator

coordinator = TestCoordinator()

try:
    if '{method}' == 'run_suite':
        run_id = coordinator.run_suite('{params.get("suite_id", "")}')
        print(json.dumps({{"success": True, "run_id": run_id}}))
    elif '{method}' == 'list_suites':
        suites = coordinator.list_suites()
        print(json.dumps({{"success": True, "suites": suites}}))
    elif '{method}' == 'get_status':
        status = coordinator.get_test_status('{params.get("run_id", "")}')
        print(json.dumps({{"success": True, **status}}))
    elif '{method}' == 'get_results':
        results = coordinator.get_test_results('{params.get("run_id", "")}')
        print(json.dumps({{"success": True, **results}}))
    elif '{method}' == 'get_active':
        tests = coordinator.get_active_tests()
        print(json.dumps({{"success": True, "tests": tests}}))
except Exception as e:
    import traceback
    print(json.dumps({{"success": False, "error": str(e), "traceback": traceback.format_exc()}}))
    sys.exit(1)
"""
    
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            _run_sync,
            python_code,
            str(project_root),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def _run_sync(python_code: str, project_root: str) -> Dict[str, Any]:
    """Synchronous wrapper for subprocess call"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", python_code],
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes max per test
            cwd=project_root,
        )
        
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            return {
                "success": False,
                "error": result.stderr or "Unknown error",
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Test execution timeout (10 minutes)"}
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": f"Invalid response from coordinator: {e}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
