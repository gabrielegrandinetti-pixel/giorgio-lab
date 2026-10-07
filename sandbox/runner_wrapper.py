from __future__ import annotations

import hashlib
import json
import subprocess
import sys

BEGIN = "---BEGIN_G5P_RESULT---"
END = "---END_G5P_RESULT---"


def run(argv: list[str]) -> int:
    # argv is supplied by the trusted orchestrator from a fixed SUITE_ID mapping.
    p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    report = p.stdout
    sys.stdout.buffer.write(report)
    marker = {
        "suite_status": "PASS" if p.returncode == 0 else "FT",
        "report_sha256": hashlib.sha256(report).hexdigest(),
        "child_exit_code": p.returncode,
    }
    sys.stdout.write("\n" + BEGIN + "\n")
    sys.stdout.write(json.dumps(marker, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n" + END + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
