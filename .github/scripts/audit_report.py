"""Accept informative findings only after a complete, consistent pip-audit scan."""
import json
import re
import sys
from pathlib import Path


def validate(inventory, report, exit_code):
    expected = {}
    for line in inventory.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)", line)
        if not match:
            raise ValueError("inventory must contain exact public package pins")
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        if name in expected:
            raise ValueError("duplicate inventory package")
        expected[name] = match[2]
    if not expected or type(report) is not dict:
        raise ValueError("empty inventory or invalid report")
    if set(report) != {"dependencies", "fixes"} or report["fixes"] != []:
        raise ValueError("unexpected audit schema or fixes")
    rows = report["dependencies"]
    if type(rows) is not list or not rows:
        raise ValueError("empty audit report")
    observed, findings = {}, 0
    for row in rows:
        if type(row) is not dict or set(row) != {"name", "version", "vulns"}:
            raise ValueError("skipped dependency or unexpected dependency schema")
        if not isinstance(row["name"], str) or not isinstance(row["version"], str):
            raise TypeError("invalid package identity")
        name = re.sub(r"[-_.]+", "-", row["name"]).lower()
        if name in observed or expected.get(name) != row["version"]:
            raise ValueError("duplicate or mismatched audit dependency")
        observed[name] = row["version"]
        if type(row["vulns"]) is not list:
            raise ValueError("invalid vulnerability list")
        for vuln in row["vulns"]:
            if (type(vuln) is not dict or not isinstance(vuln.get("id"), str)
                    or not vuln["id"] or type(vuln.get("fix_versions")) is not list
                    or not all(isinstance(v, str) for v in vuln["fix_versions"])):
                raise ValueError("invalid vulnerability record")
        findings += len(row["vulns"])
    if observed != expected or type(exit_code) is not int or exit_code != int(findings > 0):
        raise ValueError("incomplete audit or inconsistent scanner exit")
    return {"packages": len(observed), "findings": findings, "skipped": False}


def main():
    inventory, report, code = sys.argv[1:]
    try:
        summary = validate(Path(inventory).read_text(), json.loads(Path(report).read_text()),
                           int(code))
    except (OSError, ValueError, TypeError, KeyError):
        print("::error::Dependency audit failed or was incomplete", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    if summary["findings"]:
        print(f"::warning::Dependency audit found {summary['findings']} vulnerabilities; see artifact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
