"""Every workflow file must parse, and say what it is.

A workflow with a YAML error does not fail loudly — GitHub simply does not
register it. The keeper's Run button never appeared for exactly this reason:
one inline `run:` whose value contained ": " turned the file into an invalid
mapping, and the only symptom was a missing button and a sidebar entry showing
a file path instead of a name.

This also asserts a `name:` is present, because that is what distinguishes a
registered workflow from an unregistered one in the UI.

Run:  python3 tools/check_workflows.py
"""

import glob
import sys

import yaml

failures = 0
for path in sorted(glob.glob(".github/workflows/*.yml")):
    try:
        doc = yaml.safe_load(open(path))
    except Exception as e:
        print(f"FAIL {path}: {e}")
        failures += 1
        continue
    if not isinstance(doc, dict) or not doc.get("name"):
        print(f"FAIL {path}: parsed but has no name")
        failures += 1
        continue
    # PyYAML reads a bare `on:` key as the boolean True.
    triggers = doc.get("on", doc.get(True))
    if not triggers:
        print(f"FAIL {path}: no triggers")
        failures += 1
        continue
    print(f"ok   {path}  {doc['name']!r}")

print(f"\n{failures} unparseable or unnamed workflow(s)")
sys.exit(1 if failures else 0)
