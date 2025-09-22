import serve_routes
from io import StringIO

SAMPLE = """lat,lon,label
37.7749,-122.4194,San Francisco
34.0522,-118.2437,Los Angeles
"""

def test_parse():
    trips = serve_routes.parse_csv_to_trips(StringIO(SAMPLE))
    assert isinstance(trips, list), 'expected list'
    assert len(trips) == 2, f'expected 2 trips, got {len(trips)}'
    assert trips[0]['lat'] == 37.7749
    assert trips[0]['lon'] == -122.4194
    print('parse_csv_to_trips: OK', len(trips))

if __name__ == '__main__':
    test_parse()