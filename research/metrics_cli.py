"""
Metis Metrics CLI
Simple command-line tool to query and display metrics

Usage:
    python -m research.metrics_cli recent        # Last 10 runs
    python -m research.metrics_cli run <run_id>  # Details of specific run
    python -m research.metrics_cli trend pipeline_total_ms --days 7
    python -m research.metrics_cli health        # Ingester success rates (last 7 days)
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
from tabulate import tabulate

from research.metrics import MetricsCollector


def format_timestamp(ts_str):
    """Format ISO timestamp to readable format"""
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return ts_str


def cmd_recent(args):
    """Show recent runs"""
    collector = MetricsCollector()
    runs = collector.get_recent_runs(limit=args.limit)
    
    if not runs:
        print("No runs found")
        return
    
    # Format for display
    display_data = []
    for run in runs:
        display_data.append([
            run['run_id'][-16:],  # Last 16 chars (timestamp)
            format_timestamp(run['start_time']),
            run['environment'],
            run['status'] or "???"
        ])
    
    print(tabulate(display_data, headers=["Run ID", "Start Time", "Env", "Status"]))
    print(f"\nShowing {len(runs)} most recent runs")


def cmd_run(args):
    """Show details of a specific run"""
    collector = MetricsCollector()
    
    # Get metrics
    metrics = collector.get_run_metrics(args.run_id)
    if not metrics:
        print(f"Run not found: {args.run_id}")
        return
    
    # Display metrics
    print(f"\n=== Run: {args.run_id} ===\n")
    print("METRICS:")
    metrics_data = sorted([(k, f"{v:.1f}") for k, v in metrics.items()])
    print(tabulate(metrics_data, headers=["Metric", "Value"]))
    
    # Display ingesters
    ingesters = collector.get_run_ingesters(args.run_id)
    if ingesters:
        print("\n\nINGESTERS:")
        ingester_data = [
            [
                ing['ingester_name'],
                ing['status'],
                f"{ing['duration_ms']:.1f}ms" if ing['duration_ms'] else "N/A",
                ing['row_count'] or 0,
                ing['error_msg'] or ""
            ]
            for ing in ingesters
        ]
        print(tabulate(ingester_data, headers=["Ingester", "Status", "Duration", "Rows", "Error"]))


def cmd_trend(args):
    """Show metric trend over time"""
    collector = MetricsCollector()
    trend = collector.get_metric_trend(args.metric, days=args.days)
    
    if not trend:
        print(f"No data found for metric: {args.metric}")
        return
    
    # Display trend
    print(f"\n{args.metric} (last {args.days} days):\n")
    trend_data = [
        [format_timestamp(t['timestamp']), f"{t['value']:.1f}"]
        for t in trend
    ]
    print(tabulate(trend_data, headers=["Timestamp", "Value"]))
    
    # Show basic stats
    if trend:
        values = [t['value'] for t in trend]
        print(f"\nMin: {min(values):.1f}, Max: {max(values):.1f}, Avg: {sum(values)/len(values):.1f}")


def cmd_health(args):
    """Show ingester health over time"""
    collector = MetricsCollector()
    health = collector.get_ingester_health(days=args.days)
    
    if not health:
        print("No ingester data found")
        return
    
    # Display health
    print(f"\nIngester Health (last {args.days} days):\n")
    health_data = [
        [
            name,
            h['successful'],
            h['total'],
            f"{h['success_rate']*100:.0f}%",
            f"{h['avg_duration_ms']:.1f}ms" if h['avg_duration_ms'] else "N/A"
        ]
        for name, h in sorted(health.items())
    ]
    print(tabulate(health_data, headers=["Ingester", "Success", "Total", "Rate", "Avg Duration"]))


def main():
    parser = argparse.ArgumentParser(description="Metis Metrics CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # recent command
    recent_parser = subparsers.add_parser("recent", help="Show recent runs")
    recent_parser.add_argument("--limit", type=int, default=10, help="Number of runs to show")
    recent_parser.set_defaults(func=cmd_recent)
    
    # run command
    run_parser = subparsers.add_parser("run", help="Show details of a specific run")
    run_parser.add_argument("run_id", help="Run ID to display")
    run_parser.set_defaults(func=cmd_run)
    
    # trend command
    trend_parser = subparsers.add_parser("trend", help="Show metric trend")
    trend_parser.add_argument("metric", help="Metric name (e.g., pipeline_total_ms)")
    trend_parser.add_argument("--days", type=int, default=7, help="Days to look back")
    trend_parser.set_defaults(func=cmd_trend)
    
    # health command
    health_parser = subparsers.add_parser("health", help="Show ingester health")
    health_parser.add_argument("--days", type=int, default=7, help="Days to look back")
    health_parser.set_defaults(func=cmd_health)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    args.func(args)


if __name__ == "__main__":
    main()
