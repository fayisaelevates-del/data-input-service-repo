import os
from vrp_prototype import validate_shifts_and_write, SHIFT_START, SHIFT_END

# simple 2-stop route (depot=0, stop=1)
stops = [(32.257254, -110.9723225), (32.2723617, -110.9674986)]
# travel time 30 minutes each way
time_matrix = [[0, 1800], [1800, 0]]
routes = [[0, 1, 0]]

print('PWD:', os.getcwd())
print('SHIFT_START', SHIFT_START, 'SHIFT_END', SHIFT_END)
try:
	print('Calling validator...')
	validate_shifts_and_write(routes, stops, time_matrix)
	print('Validator completed')
except Exception as e:
	print('Validator exception:', repr(e))
print('End of test script')
