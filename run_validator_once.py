import os
import json
import tempfile
from vrp_prototype import validate_shifts_and_write, SHIFT_START, SHIFT_END

print('Running validator runner')
print('CWD:', os.getcwd())
print('Module file:', __file__)
print('SHIFT_START', SHIFT_START, 'SHIFT_END', SHIFT_END)

stops = [(32.257254, -110.9723225), (32.2723617, -110.9674986)]
# travel time 30 minutes each way
time_matrix = [[0, 1800], [1800, 0]]
routes = [[0, 1, 0]]

try:
    validate_shifts_and_write(routes, stops, time_matrix)
    print('validate_shifts_and_write() returned successfully')
except Exception as e:
    print('Exception running validator:', repr(e))

# check for project file
proj_path = os.path.join(os.path.dirname(__file__), 'shift_validation.json')
if os.path.exists(proj_path):
    print('Found shift_validation.json in project:', proj_path)
    with open(proj_path) as f:
        print('--- shift_validation.json content ---')
        print(f.read())
else:
    print('No shift_validation.json in project dir')

# write fallback to TEMP
try:
    tmp = tempfile.gettempdir()
    tmp_path = os.path.join(tmp, 'shift_validation_fallback.json')
    summary = {'shift_start_seconds': SHIFT_START, 'shift_end_seconds': SHIFT_END, 'note': 'fallback'}
    with open(tmp_path, 'w') as tf:
        json.dump(summary, tf)
    print('Wrote fallback file to', tmp_path)
except Exception as e:
    print('Could not write fallback file:', repr(e))

print('Done')
