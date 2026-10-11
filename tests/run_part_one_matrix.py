"""Run the Part 1 real-MongoDB compatibility matrix serially.

Requires mongo:7 at localhost:27028 and mongo:6 at localhost:27029, plus Docker
for the separate recovery-test container. Uses only disposable audit databases.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
artifacts = Path(tempfile.mkdtemp(prefix="candidate-kit-part1-matrix-"))
print(f"JUnit reports: {artifacts}", flush=True)
results = []
for major, port in ((7, 27028), (6, 27029)):
    for workers in (1, 2):
        for tz in ("UTC", "Asia/Kolkata"):
            label = f"mongo{major}-workers{workers}-{tz.replace('/', '-') }"
            print(f"\n{label}", flush=True)
            report = artifacts / f"{label}.xml"
            environment = {**os.environ, "TEST_MONGO_URI": f"mongodb://127.0.0.1:{port}",
                           "TEST_WORKERS": str(workers), "TEST_SERVER_TZ": tz}
            completed = subprocess.run([sys.executable, "-m", "pytest",
                "tests/test_starter_contract.py", "-q", "--tb=short", f"--junitxml={report}"],
                cwd=root, env=environment)
            if completed.returncode:
                raise SystemExit(completed.returncode)
            suite = ET.parse(report).getroot().find("testsuite")
            results.append((label, suite.attrib))
print("\nMatrix complete:", flush=True)
for label, result in results:
    print(f"{label}: {result['tests']} tests, {result['failures']} failures, {result['errors']} errors; {result['time']}s")
