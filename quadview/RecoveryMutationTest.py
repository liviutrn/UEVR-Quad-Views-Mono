"""Demand the specific deterministic Build47 failure, not any nonzero exit."""
import subprocess
import sys

result = subprocess.run([sys.argv[1], '--legacy'], capture_output=True, text=True, timeout=30)
if result.returncode != 2 or 'Reproduced incomplete-snapshot startup starvation' not in result.stderr:
    raise SystemExit(f'Legacy mutation failed unexpectedly: {result.returncode}: {result.stdout} {result.stderr}')
print('Unmodified Build47 incomplete-snapshot admission reproduces the expected starvation.')
