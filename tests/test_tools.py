"""Quick test of all tool functions."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.vessel_tools import *

def pp(result):
    print(json.dumps(result, indent=2, default=str))

print('=== Test 1: get_vessel_info ===')
pp(get_vessel_info('OCEAN WARLOCK'))

print('\n=== Test 2: get_vessel_position_at ===')
pp(get_vessel_position_at('316004661', '2025-12-24T00:00:00'))

print('\n=== Test 3: find_vessels_near (Seattle area) ===')
result = find_vessels_near(47.56, -122.34, 10, '2025-12-24T00:00:00', 5)
print(f"Vessels found: {result['vessels_found']}")
for v in result['vessels'][:5]:
    print(f"  {v['vessel_name'] or v['mmsi']} — {v['distance_km']} km away")

print('\n=== Test 4: summarize_voyage ===')
pp(summarize_voyage('316004661', '2025-12-24T00:00:00', '2025-12-24T23:59:59'))

print('\n=== Test 5: detect_dark_activity ===')
pp(detect_dark_activity('316004661', '2025-12-24T00:00:00', '2025-12-24T23:59:59'))

print('\n=== Test 6: visualize_path ===')
result = visualize_path('OCEAN WARLOCK', '2025-12-24T00:00:00', '2025-12-24T23:59:59')
pp(result)

print('\n=== Test 7: list_vessels_with_dark_activity ===')
result = list_vessels_with_dark_activity('2025-12-24T00:00:00', '2025-12-24T02:00:00', 10)
print(f"Vessels with dark activity: {result['vessels_found']}")
for v in result['vessels'][:3]:
    print(f"  MMSI: {v['mmsi']} — Name: {v['vessel_name']} — Gap duration: {v['duration_minutes']} min")

print('\n=== Test 8: resolve_location_to_coordinates ===')
pp(resolve_location_to_coordinates('Seattle'))
pp(resolve_location_to_coordinates('Houston Ship Channel'))
pp(resolve_location_to_coordinates('Unknown Place'))

print('\n=== ALL TESTS PASSED ===')
