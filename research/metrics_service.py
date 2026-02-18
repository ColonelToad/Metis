"""
Metrics Query Service for Tauri
Provides JSON-serializable query results for the UI

Usage from Tauri (via Python subprocess or HTTP):
    from research.metrics_service import get_recent_runs, get_ingester_health, etc.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional


class MetricsService:
    """Service to query metrics for Tauri AdminScreen"""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = Path(__file__).parent / "logs" / "metrics.db"
        self.db_path = Path(db_path)
    
    def _query(self, sql: str, params: tuple = ()) -> list:
        """Execute query and return results"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute(sql, params)
            results = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
        
        return results
    
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get summary for AdminScreen dashboard"""
        recent_runs = self.get_recent_runs(limit=20)
        ingester_health = self.get_ingester_health(days=7)
        pipeline_trend = self.get_metric_trend("pipeline_total_ms", days=7)
        
        # Calculate stats
        success_count = len([r for r in recent_runs if r.get('status') == 'success'])
        partial_count = len([r for r in recent_runs if r.get('status') == 'partial'])
        
        return {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_runs_last_20": len(recent_runs),
                "successful": success_count,
                "partial": partial_count,
                "success_rate": success_count / len(recent_runs) if recent_runs else 0.0,
            },
            "recent_runs": recent_runs[:5],  # Last 5
            "ingester_health": ingester_health,
            "pipeline_trend": pipeline_trend,
        }
    
    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent test runs"""
        results = self._query("""
            SELECT 
                run_id,
                start_time,
                end_time,
                environment,
                status,
                notes,
                CASE 
                    WHEN end_time IS NOT NULL 
                    THEN CAST((julianday(end_time) - julianday(start_time)) * 86400 AS INTEGER)
                    ELSE NULL
                END as duration_seconds
            FROM runs
            ORDER BY start_time DESC
            LIMIT ?
        """, (limit,))
        
        return results
    
    def get_run_details(self, run_id: str) -> Dict[str, Any]:
        """Get full details of a specific run"""
        # Get run info
        runs = self._query("""
            SELECT * FROM runs WHERE run_id = ?
        """, (run_id,))
        
        if not runs:
            return {"error": f"Run not found: {run_id}"}
        
        run = runs[0]
        
        # Get metrics
        metrics = self._query("""
            SELECT metric_name, value, unit FROM metrics WHERE run_id = ? ORDER BY metric_name
        """, (run_id,))
        
        # Get ingester results
        ingesters = self._query("""
            SELECT ingester_name, status, duration_ms, row_count, error_msg 
            FROM ingester_results 
            WHERE run_id = ? 
            ORDER BY ingester_name
        """, (run_id,))
        
        return {
            "run": run,
            "metrics": {m['metric_name']: m['value'] for m in metrics},
            "ingesters": ingesters,
        }
    
    def get_ingester_health(self, days: int = 7) -> Dict[str, Dict[str, Any]]:
        """Get success rate and avg latency per ingester"""
        results = self._query("""
            SELECT 
                ingester_name,
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_runs,
                AVG(CASE WHEN status = 'success' THEN duration_ms ELSE NULL END) as avg_duration_ms,
                MAX(CASE WHEN status != 'success' THEN error_msg ELSE NULL END) as last_error
            FROM ingester_results
            WHERE run_id IN (
                SELECT run_id FROM runs 
                WHERE start_time > datetime('now', '-' || ? || ' days')
            )
            GROUP BY ingester_name
            ORDER BY (100.0 * SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) / COUNT(*)) DESC
        """, (days,))
        
        health = {}
        for row in results:
            name = row['ingester_name']
            health[name] = {
                "total": row['total_runs'],
                "successful": row['successful_runs'],
                "success_rate": row['successful_runs'] / row['total_runs'] if row['total_runs'] > 0 else 0.0,
                "avg_duration_ms": row['avg_duration_ms'],
                "last_error": row['last_error'],
            }
        
        return health
    
    def get_metric_trend(self, metric_name: str, days: int = 7) -> List[Dict[str, Any]]:
        """Get metric values over time"""
        results = self._query("""
            SELECT 
                r.start_time as timestamp,
                m.value,
                m.unit,
                r.environment,
                r.status
            FROM metrics m
            JOIN runs r ON m.run_id = r.run_id
            WHERE m.metric_name = ? AND r.start_time > datetime('now', '-' || ? || ' days')
            ORDER BY r.start_time
        """, (metric_name, days))
        
        return results
    
    def get_metric_stats(self, metric_name: str, days: int = 7) -> Dict[str, Any]:
        """Get statistics for a metric"""
        results = self._query("""
            SELECT 
                COUNT(*) as count,
                MIN(m.value) as min_value,
                MAX(m.value) as max_value,
                AVG(m.value) as avg_value,
                (
                    SELECT m2.value FROM metrics m2
                    JOIN runs r2 ON m2.run_id = r2.run_id
                    WHERE m2.metric_name = ?
                    AND r2.start_time > datetime('now', '-' || ? || ' days')
                    ORDER BY r2.start_time DESC
                    LIMIT 1
                ) as latest_value
            FROM metrics m
            JOIN runs r ON m.run_id = r.run_id
            WHERE m.metric_name = ? AND r.start_time > datetime('now', '-' || ? || ' days')
        """, (metric_name, days, metric_name, days))
        
        if results:
            row = results[0]
            return {
                "metric": metric_name,
                "days": days,
                "count": row['count'],
                "min": row['min_value'],
                "max": row['max_value'],
                "avg": row['avg_value'],
                "latest": row['latest_value'],
                "trend": "up" if row['latest_value'] and row['avg_value'] and row['latest_value'] > row['avg_value'] else "down" if row['latest_value'] and row['avg_value'] else "neutral"
            }
        
        return {"error": f"No data for {metric_name}"}
    
    def get_failures(self, days: int = 7) -> Dict[str, Any]:
        """Get recent failures"""
        ingester_failures = self._query("""
            SELECT 
                run_id,
                ingester_name,
                error_msg,
                (SELECT start_time FROM runs WHERE run_id = ingester_results.run_id) as timestamp
            FROM ingester_results
            WHERE status = 'failed'
            AND run_id IN (
                SELECT run_id FROM runs 
                WHERE start_time > datetime('now', '-' || ? || ' days')
            )
            ORDER BY timestamp DESC
            LIMIT 20
        """, (days,))
        
        run_failures = self._query("""
            SELECT 
                run_id,
                start_time as timestamp,
                status,
                notes
            FROM runs
            WHERE status = 'partial'
            AND start_time > datetime('now', '-' || ? || ' days')
            ORDER BY start_time DESC
            LIMIT 20
        """, (days,))
        
        return {
            "ingester_failures": ingester_failures,
            "run_failures": run_failures,
        }


def json_response(func):
    """Decorator to ensure response is JSON-serializable"""
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        # Ensure all datetime objects are ISO formatted
        return json.loads(json.dumps(result, default=str))
    return wrapper


# Module-level service instance
_service = None

def get_service() -> MetricsService:
    """Get or create the metrics service"""
    global _service
    if _service is None:
        _service = MetricsService()
    return _service


# Exported functions for Tauri commands
@json_response
def query_dashboard_summary() -> Dict[str, Any]:
    """Dashboard summary for AdminScreen"""
    return get_service().get_dashboard_summary()


@json_response
def query_recent_runs(limit: int = 10) -> List[Dict[str, Any]]:
    """Recent runs"""
    return get_service().get_recent_runs(limit)


@json_response
def query_run_details(run_id: str) -> Dict[str, Any]:
    """Run details"""
    return get_service().get_run_details(run_id)


@json_response
def query_ingester_health(days: int = 7) -> Dict[str, Dict[str, Any]]:
    """Ingester health"""
    return get_service().get_ingester_health(days)


@json_response
def query_metric_trend(metric_name: str, days: int = 7) -> List[Dict[str, Any]]:
    """Metric trend"""
    return get_service().get_metric_trend(metric_name, days)


@json_response
def query_metric_stats(metric_name: str, days: int = 7) -> Dict[str, Any]:
    """Metric statistics"""
    return get_service().get_metric_stats(metric_name, days)


@json_response
def query_failures(days: int = 7) -> Dict[str, Any]:
    """Recent failures"""
    return get_service().get_failures(days)


if __name__ == "__main__":
    import sys
    
    service = MetricsService()
    
    # CLI for testing
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "dashboard":
            print(json.dumps(service.get_dashboard_summary(), default=str, indent=2))
        elif command == "recent":
            print(json.dumps(service.get_recent_runs(5), default=str, indent=2))
        elif command == "health":
            print(json.dumps(service.get_ingester_health(7), default=str, indent=2))
        elif command == "failures":
            print(json.dumps(service.get_failures(7), default=str, indent=2))
        else:
            print(f"Unknown command: {command}")
    else:
        print("metrics_service.py - Query metrics for AdminScreen")
        print("Commands: dashboard, recent, health, failures")
