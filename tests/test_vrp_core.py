from vrp_prototype import haversine, sweep_partition


def test_haversine_symmetry():
    a = (32.0, -111.0)
    b = (32.1, -111.1)
    d1 = haversine(a, b)
    d2 = haversine(b, a)
    assert abs(d1 - d2) < 1e-6
    assert d1 > 0


def test_sweep_partition_counts():
    # create 13 stops including depot
    stops = [(32.0, -111.0)] + [(32.0 + i*0.01, -111.0 + i*0.01) for i in range(1, 13)]
    demands = [0] + [1]*12
    clusters = sweep_partition(stops, 3, demands)
    # expecting approximately 3 clusters
    assert len(clusters) == 3
    total = sum(len(c) for c in clusters)
    assert total == 12
