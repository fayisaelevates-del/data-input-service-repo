import folium

# Example coordinate list (latitude, longitude)
coords = [
    (32.257254, -110.9723225),
    (32.1162014, -111.0419424),
    (32.4078759, -111.0204164),
    (32.2753731, -110.9443301),
    (32.1495514, -111.0237159),
    (32.5109786, -110.9222564),
    (32.2723617, -110.9674986),
    (32.3451874, -110.9872146),
]

m = folium.Map(location=coords[0], zoom_start=11)
for i, (lat, lon) in enumerate(coords, start=1):
    folium.Marker(location=(lat, lon), popup=f"Stop {i}").add_to(m)

m.save('stops_map.html')
print('Saved stops_map.html')
