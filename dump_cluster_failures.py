"""Scan existing cluster_*.stderr.log files for OR-Tools failures and write per-cluster JSON dumps

This is best-effort: previous runs didn't record the cluster payloads, so dumps will include
stderr/stdout excerpts and file paths. New runs (with updated vrp_prototype.py) will also
produce richer dumps with subproblem inputs.
"""
import re
import json
from pathlib import Path

LOG_DIR = Path('.')
FAIL_DIR = LOG_DIR / 'failures'
FAIL_DIR.mkdir(exist_ok=True)

pattern = re.compile(r'(SetRange|CP Solver fail|CumulVar|Exception: CP Solver fail)', re.IGNORECASE)

created = 0
for p in LOG_DIR.glob('cluster_*.stderr.log'):
    try:
        text = p.read_text(errors='replace')
    except Exception:
        continue
    if not pattern.search(text):
        continue
    tag = p.stem.split('_', 1)[1] if '_' in p.stem else p.stem
    out_path = FAIL_DIR / f'cluster_{tag}.json'
    if out_path.exists():
        # don't overwrite
        continue
    # try to read stdout file for context
    stdout_file = LOG_DIR / f'cluster_{tag}.stdout.log'
    stdout_excerpt = ''
    if stdout_file.exists():
        try:
            stdout_excerpt = stdout_file.read_text(errors='replace')[:4096]
        except Exception:
            stdout_excerpt = ''
    stderr_excerpt = text[:8192]
    dump = {
        'tag': tag,
        'stderr_path': str(p.resolve()),
        'stdout_path': str(stdout_file.resolve()) if stdout_file.exists() else None,
        'stderr_excerpt': stderr_excerpt,
        'stdout_excerpt': stdout_excerpt,
        'note': 'Payload for historical runs not available; run newer vrp_prototype.py to get full inputs'
    }
    try:
        out_path.write_text(json.dumps(dump, indent=2))
        created += 1
    except Exception:
        pass

print(f'Created {created} failure dumps in {FAIL_DIR}')
