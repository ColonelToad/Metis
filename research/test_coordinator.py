"""
Test Coordinator - Centralized test runner for AdminScreen
Provides test suites (ingesters, RAG scaling, chaos) with results stored in metrics DB

Usage:
    coordinator = TestCoordinator()
    
    # Run a test suite
    run_id = coordinator.run_suite("ingester_tests")
    
    # Check status
    status = coordinator.get_test_status(run_id)
    
    # Get results
    results = coordinator.get_test_results(run_id)
"""

import subprocess
import json
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum
import os
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from research.metrics import MetricsCollector


class TestStatus(Enum):
    """Test execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class TestCoordinator:
    """Runs test suites and tracks results in metrics DB"""
    
    # Test suite definitions
    SUITES = {
        "ingester_tests": {
            "name": "Ingester Tests (Mock Data)",
            "description": "Test all ingesters with mock/small datasets",
            "script": "research/test_ingesters_mock.py",
            "timeout": 300,
        },
        "rag_scaling": {
            "name": "RAG Scaling Study",
            "description": "Test RAG with increasing document sets (50, 100, 500, 1000)",
            "script": "research/test_rag_scaling.py",
            "timeout": 600,
        },
        "bridge_latency": {
            "name": "Bridge Latency Profiler",
            "description": "Measure Python-Rust message passing latency",
            "script": "profiling/measure_bridge_latency.py",
            "timeout": 120,
        },
        "chaos_ingest": {
            "name": "Chaos: Ingester Failures",
            "description": "Test graceful degradation when ingesters fail",
            "script": "research/test_chaos_ingester_failures.py",
            "timeout": 180,
        },
        "chaos_rag": {
            "name": "Chaos: RAG Unavailable",
            "description": "Test pipeline when RAG service is down",
            "script": "research/test_chaos_rag_unavailable.py",
            "timeout": 180,
        },
    }
    
    def __init__(self):
        """Initialize test coordinator with metrics collector"""
        self.collector = MetricsCollector()
        self.project_root = project_root
        self.test_runs: Dict[str, Dict[str, Any]] = {}  # run_id -> test state
    
    def list_suites(self) -> List[Dict[str, Any]]:
        """List all available test suites"""
        return [
            {
                "suite_id": suite_id,
                "name": config["name"],
                "description": config["description"],
                "timeout_seconds": config["timeout"],
            }
            for suite_id, config in self.SUITES.items()
        ]
    
    def run_suite(self, suite_id: str) -> str:
        """
        Start a test suite. Returns run_id immediately (async).
        Results stored in metrics DB as they complete.
        """
        if suite_id not in self.SUITES:
            raise ValueError(f"Unknown suite: {suite_id}")
        
        suite = self.SUITES[suite_id]
        
        # Create metrics run
        run_id = self.collector.start_run(
            environment="TEST",
            git_commit=self._get_git_commit()
        )
        
        # Initialize test run state
        self.test_runs[run_id] = {
            "suite_id": suite_id,
            "suite_name": suite["name"],
            "status": TestStatus.RUNNING.value,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "error": None,
            "metrics": {},
            "details": {},
        }
        
        # Track that test is running
        self.collector.add_metric("test_suite_status", 1.0)  # 1 = running
        
        # Run test suite (synchronous for now - can be async later with threads)
        try:
            self._run_test_script(run_id, suite_id, suite)
        except Exception as e:
            self._handle_test_error(run_id, e)
        
        # Finalize metrics run
        status = self.test_runs[run_id]["status"]
        self.collector.finalize_run(
            status=status,
            notes=f"Test Suite: {suite['name']}"
        )
        
        return run_id
    
    def _run_test_script(self, run_id: str, suite_id: str, suite: Dict[str, Any]):
        """Execute the test script and capture results"""
        script_path = self.project_root / suite["script"]
        
        # Check script exists
        if not script_path.exists():
            raise FileNotFoundError(f"Test script not found: {script_path}")
        
        start_time = datetime.now()
        
        try:
            # Run script with timeout
            result = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=suite["timeout"],
            )
            
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            # Parse results
            if result.returncode == 0:
                # Parse stdout as JSON with test metrics
                try:
                    metrics = json.loads(result.stdout)
                    self._record_test_metrics(run_id, metrics, duration_ms)
                    self.test_runs[run_id]["status"] = TestStatus.SUCCESS.value
                except json.JSONDecodeError:
                    # Not JSON - just record duration and output
                    self.collector.add_metric("test_duration_ms", duration_ms)
                    self.test_runs[run_id]["status"] = TestStatus.SUCCESS.value
                    self.test_runs[run_id]["details"]["output"] = result.stdout[:1000]
            else:
                # Test failed
                self.test_runs[run_id]["status"] = TestStatus.FAILED.value
                self.test_runs[run_id]["error"] = result.stderr[:500]
                self.collector.add_metric("test_duration_ms", duration_ms)
                self.collector.add_metric("test_exit_code", float(result.returncode))
        
        except subprocess.TimeoutExpired:
            self.test_runs[run_id]["status"] = TestStatus.FAILED.value
            self.test_runs[run_id]["error"] = f"Test timeout after {suite['timeout']}s"
            self.collector.add_metric("test_timeout_exceeded", 1.0)
    
    def _record_test_metrics(self, run_id: str, metrics: Dict[str, Any], duration_ms: float):
        """Record test metrics returned from test script"""
        # Standard metrics
        self.collector.add_metric("test_duration_ms", duration_ms)
        
        # Custom metrics from test
        for metric_name, value in metrics.items():
            if isinstance(value, (int, float)):
                self.collector.add_metric(f"test_{metric_name}", float(value))
        
        # Store details
        self.test_runs[run_id]["metrics"] = metrics
    
    def _handle_test_error(self, run_id: str, error: Exception):
        """Handle test execution errors"""
        self.test_runs[run_id]["status"] = TestStatus.FAILED.value
        self.test_runs[run_id]["error"] = str(error)
        self.collector.add_metric("test_execution_error", 1.0)
    
    def get_test_status(self, run_id: str) -> Dict[str, Any]:
        """Get current status of a test run"""
        if run_id not in self.test_runs:
            return {"error": f"Run not found: {run_id}"}
        
        run = self.test_runs[run_id]
        return {
            "run_id": run_id,
            "suite_id": run["suite_id"],
            "suite_name": run["suite_name"],
            "status": run["status"],
            "start_time": run["start_time"],
            "end_time": run["end_time"],
            "error": run["error"],
        }
    
    def get_test_results(self, run_id: str) -> Dict[str, Any]:
        """Get full results of a completed test run"""
        if run_id not in self.test_runs:
            return {"error": f"Run not found: {run_id}"}
        
        run = self.test_runs[run_id]
        
        # Get metrics from database
        recent_runs = self.collector.get_recent_runs(limit=1)
        metrics = {}
        if recent_runs:
            # Get metrics for this run from DB
            pass  # TODO: implement metrics query from DB
        
        return {
            "run_id": run_id,
            "suite_id": run["suite_id"],
            "suite_name": run["suite_name"],
            "status": run["status"],
            "start_time": run["start_time"],
            "end_time": run["end_time"],
            "error": run["error"],
            "metrics": run["metrics"],
            "details": run["details"],
        }
    
    def get_active_tests(self) -> List[Dict[str, Any]]:
        """Get list of currently running tests"""
        return [
            {
                "run_id": run_id,
                "suite_name": run["suite_name"],
                "status": run["status"],
                "start_time": run["start_time"],
            }
            for run_id, run in self.test_runs.items()
            if run["status"] == TestStatus.RUNNING.value
        ]
    
    def _get_git_commit(self) -> Optional[str]:
        """Get current git commit hash"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()[:8]
        except:
            pass
        return None


# ============================================================================
# EXAMPLE TEST SCRIPTS (to be created separately)
# ============================================================================

def create_example_test_scripts():
    """Show what each test script should look like"""
    
    # research/test_ingesters_mock.py
    example_ingester_test = '''
import json
results = {
    "ingesters_tested": 5,
    "ingesters_passed": 5,
    "total_rows_ingested": 50000,
    "avg_latency_ms": 234.5,
    "success_rate": 1.0,
}
print(json.dumps(results))
exit(0)
'''
    
    # research/test_rag_scaling.py
    example_rag_scaling = '''
import json
results = {
    "doc_counts": [50, 100, 500, 1000],
    "indexing_times_ms": [234, 421, 1923, 5234],
    "query_times_ms": [12, 15, 45, 120],
    "max_docs_before_timeout": 5000,
}
print(json.dumps(results))
exit(0)
'''
    
    # profiling/measure_bridge_latency.py (already exists, just outputs JSON)
    example_profiler = '''
import json
results = {
    "mean_latency_ms": 0.45,
    "p95_latency_ms": 0.89,
    "p99_latency_ms": 1.23,
    "messages_per_second": 2200,
}
print(json.dumps(results))
exit(0)
'''


if __name__ == "__main__":
    coordinator = TestCoordinator()
    
    print("Available test suites:")
    for suite in coordinator.list_suites():
        print(f"  {suite['suite_id']:20} - {suite['name']}")
    
    print("\nTo run a suite from Tauri:")
    print("  invoke('run_test_suite', { suite_id: 'ingester_tests' })")
