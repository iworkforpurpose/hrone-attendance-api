"""Run all implemented groups against test-owned MongoDB 6/7 instances.

Use localhost ports 27038/27039 with enableTestCommands=1. Serial execution
keeps controlled server failpoints isolated from other tests. Docker is needed
for independently owned outage/recovery containers.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
artifacts = Path(tempfile.mkdtemp(prefix="candidate-kit-runtime-matrix-"))
print(f"Evidence directory: {artifacts}", flush=True)
results = []
for major, port in ((7, 27038), (6, 27039)):
    uri = f"mongodb://127.0.0.1:{port}"
    with MongoClient(uri, serverSelectionTimeoutMS=2000) as client:
        version = client.server_info()['version']
        assert version.split('.')[0] == str(major), version
        assert client.admin.command('getParameter', 1, enableTestCommands=1)['enableTestCommands']
    for workers in (1, 2):
        for tz in ("UTC", "Asia/Kolkata"):
            label = f"mongo{major}-workers{workers}-{tz.replace('/', '-')}"
            print(f"\n{label}", flush=True)
            report = artifacts / f"{label}.xml"
            environment = {**os.environ, "TEST_MONGO_URI": uri,
                           "TEST_WORKERS": str(workers), "TEST_SERVER_TZ": tz}
            completed = subprocess.run([sys.executable, "-m", "pytest", "tests",
                "-q", "--tb=short", f"--junitxml={report}"],
                cwd=ROOT, env=environment, capture_output=True, text=True)
            (artifacts / f"{label}.log").write_text(completed.stdout + completed.stderr)
            print(completed.stdout.strip(), flush=True)
            if completed.returncode:
                print(completed.stderr, flush=True)
                raise SystemExit(completed.returncode)
            suite = ET.parse(report).getroot().find("testsuite")
            result = {"configuration": label, "mongo_version": version, **suite.attrib,
                      "properties": {p.attrib['name']: p.attrib['value']
                                     for p in suite.findall('properties/property')}}
            assert all(int(result[key]) == 0 for key in ('failures', 'errors', 'skipped')), result
            results.append(result)
            (artifacts / "summary.json").write_text(json.dumps(results, indent=2))
print("\nMatrix complete:", flush=True)
for result in results:
    print(f"{result['configuration']}: {result['tests']} passed; {result['time']}s; {result['properties']}", flush=True)
