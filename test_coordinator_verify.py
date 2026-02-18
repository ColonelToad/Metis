"""Quick test of test coordinator"""
from research.test_coordinator import TestCoordinator

c = TestCoordinator()
print("Available test suites:")
for suite in c.list_suites():
    print(f"  {suite['suite_id']:25} - {suite['name']}")
