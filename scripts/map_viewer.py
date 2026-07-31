"""BARRA2 map viewer module.

Generates interactive folium maps showing input coordinates
and nearest grid points with switchable basemaps.
"""
import os
import sys
import tempfile
import webbrowser
from pathlib import Path

# Ensure parent directory is in path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import folium
from folium.raster_layers import TileLayer

from scripts.grid_finder import normalize_longitude


def create_map_with_points(
    input_lat: float,
    input_lon: float,
    grid_points: list[dict],
    enable_click: bool = False,
    callback_file: str = None,
    map_title: str = 'BARRA2 Grid Points',
) -> str:
    """Create an interactive folium map with input coordinate and grid points.

    Args:
        input_lat: Input latitude in degrees.
        input_lon: Input longitude in degrees (-180~180).
        grid_points: List of grid point dicts from find_nearest_four_grid_points().
        enable_click: If True, add click event handler for adding new coordinates.
        callback_file: Path to file where clicked coordinates will be written.
        map_title: Title displayed on the map.

    Returns:
        Path to the generated HTML file.
    """
    # Create map centered on input coordinate
    m = folium.Map(
        location=[input_lat, input_lon],
        zoom_start=10,
        control_scale=True,
    )

    # Add title
    title_html = f'''
    <div style="position: fixed;
                top: 10px; left: 50px; width: 350px; height: 40px;
                background-color: white; border:2px solid grey;
                z-index:9999; font-size:16px; font-weight:bold;
                padding: 10px;">
        {map_title}
    </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))

    # Add switchable basemap layers
    basemaps = {
        'OpenStreetMap': folium.TileLayer('openstreetmap', name='OpenStreetMap', show=True),
        'CartoDB Positron': folium.TileLayer(
            'https://cartodb-basemaps-a.global.ssl.fastly.net/light_all/{z}/{x}/{y}.png',
            attr='CartoDB',
            name='CartoDB Positron',
            overlay=False,
        ),
        'CartoDB Dark': folium.TileLayer(
            'https://cartodb-basemaps-a.global.ssl.fastly.net/dark_all/{z}/{x}/{y}.png',
            attr='CartoDB',
            name='CartoDB Dark',
            overlay=False,
        ),
        'Esri Satellite': folium.TileLayer(
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Esri Satellite',
            overlay=False,
        ),
        'Esri Terrain': folium.TileLayer(
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Esri Terrain',
            overlay=False,
        ),
    }
    for name, layer in basemaps.items():
        if name != 'OpenStreetMap':
            m.add_child(layer)

    # Add layer control for basemap switching
    folium.LayerControl().add_to(m)

    # Marker icon colors
    # Red = input point, Blue = grid points, Green = selected
    input_icon = folium.Icon(color='red', icon='star', prefix='fa')
    grid_icon = folium.Icon(color='blue', icon='circle', prefix='fa')

    # Add input coordinate marker
    folium.Marker(
        [input_lat, input_lon],
        popup=folium.Popup(
            f"<b>Input Coordinate</b><br>"
            f"Lat: {input_lat:.4f}<br>"
            f"Lon: {input_lon:.4f}",
            max_width=250,
        ),
        icon=input_icon,
        tooltip='Input Point',
    ).add_to(m)

    # Add grid point markers
    for pt in grid_points:
        pt_lon = normalize_longitude(pt['lon'])
        folium.Marker(
            [pt['lat'], pt_lon],
        popup=folium.Popup(
            f"<b>{pt['label']}</b><br>"
            f"Lat: {pt['lat']:.2f}<br>"
            f"Lon: {pt_lon:.2f}<br>"
            f"Distance: {pt['distance_km']:.2f} km",
            max_width=250,
        ),
        icon=grid_icon,
        tooltip=f"{pt['label']} ({pt['distance_km']:.1f} km)",
    ).add_to(m)

    # Draw a rectangle connecting the 4 grid points
    if len(grid_points) == 4:
        tl = [grid_points[0]['lat'], normalize_longitude(grid_points[0]['lon'])]
        tr = [grid_points[1]['lat'], normalize_longitude(grid_points[1]['lon'])]
        bl = [grid_points[2]['lat'], normalize_longitude(grid_points[2]['lon'])]
        br = [grid_points[3]['lat'], normalize_longitude(grid_points[3]['lon'])]
        bbox = [tl[0], bl[0], br[1], tr[1]]  # [south, north, west, east]
        folium.Rectangle(
            bounds=[[bl[0], bl[1]], [tr[0], tr[1]]],
            color='blue',
            weight=2,
            fill=True,
            fill_color='blue',
            fill_opacity=0.1,
            popup='Grid Cell',
        ).add_to(m)

    # Add click event handler for adding new coordinates
    if enable_click and callback_file:
        click_js = f'''
        function onMapClick(e) {{
            var lat = e.latlng.lat.toFixed(6);
            var lon = e.latlng.lng.toFixed(6);
            var content = lat + "," + lon + "\\n";
            var xhr = new XMLHttpRequest();
            xhr.open("POST", "file:///{callback_file.replace(os.sep, '/').replace(':', '')}", false);
            // Write to a simpler location via the Python callback mechanism
            fetch('file:///' + '{callback_file.replace(os.sep, '/')}').catch(function() {{}});
            // Use a local storage approach or simple alert for now
            alert("Coordinates: " + lat + ", " + lon + "\\n(Copy and paste into the GUI)");
        }}
        map.on('click', onMapClick);
        '''
        # Alternative: use a simpler click handler that shows alert
        click_js_simple = '''
        function onMapClick(e) {{
            var lat = e.latlng.lat.toFixed(6);
            var lon = e.latlng.lng.toFixed(6);
            prompt("Copy this coordinate:", lat + "," + lon);
        }}
        map.on('click', onMapClick);
        '''
        click_element = folium.Element(f'<script>{click_js_simple}</script>')
        m.get_root().html.add_child(click_element)

    # Add a note about click-to-add
    if enable_click:
        note_html = '''
        <div style="position: fixed;
                    bottom: 10px; left: 50px; width: 350px; height: 30px;
                    background-color: lightyellow; border:1px solid grey;
                    z-index:9999; font-size:12px;
                    padding: 5px 10px;">
            Click on map to get coordinates (copy & paste into GUI)
        </div>
        '''
        m.get_root().html.add_child(folium.Element(note_html))

    # Save HTML to temp file
    tmp_dir = tempfile.mkdtemp(prefix='barra2_map_')
    html_path = os.path.join(tmp_dir, 'map.html')
    m.save(html_path)

    return html_path


def open_map_in_browser(html_path: str) -> None:
    """Open the generated HTML map in the default web browser.

    Args:
        html_path: Path to the HTML file.
    """
    file_url = 'file:///' + html_path.replace(os.sep, '/')
    webbrowser.open(file_url)


def create_map_html_string(
    input_lat: float,
    input_lon: float,
    grid_points: list[dict],
    enable_click: bool = False,
    map_title: str = 'BARRA2 Grid Points',
) -> str:
    """Create an interactive folium map and return as HTML string.

    Args:
        input_lat: Input latitude in degrees.
        input_lon: Input longitude in degrees (-180~180).
        grid_points: List of grid point dicts from find_nearest_four_grid_points().
        enable_click: If True, add click event handler for adding new coordinates.
        map_title: Title displayed on the map.

    Returns:
        HTML string of the map.
    """
    m = folium.Map(
        location=[input_lat, input_lon],
        zoom_start=10,
        control_scale=True,
    )

    title_html = f'''
    <div style="position: fixed;
                top: 10px; left: 50px; width: 350px; height: 40px;
                background-color: white; border:2px solid grey;
                z-index:9999; font-size:16px; font-weight:bold;
                padding: 10px;">
        {map_title}
    </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))

    basemaps = {
        'OpenStreetMap': folium.TileLayer('openstreetmap', name='OpenStreetMap', show=True),
        'CartoDB Positron': folium.TileLayer(
            'https://cartodb-basemaps-a.global.ssl.fastly.net/light_all/{z}/{x}/{y}.png',
            attr='CartoDB',
            name='CartoDB Positron',
            overlay=False,
        ),
        'CartoDB Dark': folium.TileLayer(
            'https://cartodb-basemaps-a.global.ssl.fastly.net/dark_all/{z}/{x}/{y}.png',
            attr='CartoDB',
            name='CartoDB Dark',
            overlay=False,
        ),
        'Esri Satellite': folium.TileLayer(
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Esri Satellite',
            overlay=False,
        ),
        'Esri Terrain': folium.TileLayer(
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Esri Terrain',
            overlay=False,
        ),
    }
    for name, layer in basemaps.items():
        if name != 'OpenStreetMap':
            m.add_child(layer)
    folium.LayerControl().add_to(m)

    input_icon = folium.Icon(color='red', icon='star', prefix='fa')
    grid_icon = folium.Icon(color='blue', icon='circle', prefix='fa')

    folium.Marker(
        [input_lat, input_lon],
        popup=folium.Popup(
            f"<b>Input Coordinate</b><br>"
            f"Lat: {input_lat:.4f}<br>"
            f"Lon: {input_lon:.4f}",
            max_width=250,
        ),
        icon=input_icon,
        tooltip='Input Point',
    ).add_to(m)

    for pt in grid_points:
        pt_lon = normalize_longitude(pt['lon'])
        folium.Marker(
            [pt['lat'], pt_lon],
            popup=folium.Popup(
                f"<b>{pt['label']}</b><br>"
                f"Lat: {pt['lat']:.2f}<br>"
                f"Lon: {pt_lon:.2f}<br>"
                f"Distance: {pt['distance_km']:.2f} km",
                max_width=250,
            ),
            icon=grid_icon,
            tooltip=f"{pt['label']} ({pt['distance_km']:.1f} km)",
        ).add_to(m)

    if len(grid_points) == 4:
        tl = [grid_points[0]['lat'], normalize_longitude(grid_points[0]['lon'])]
        tr = [grid_points[1]['lat'], normalize_longitude(grid_points[1]['lon'])]
        bl = [grid_points[2]['lat'], normalize_longitude(grid_points[2]['lon'])]
        br = [grid_points[3]['lat'], normalize_longitude(grid_points[3]['lon'])]
        folium.Rectangle(
            bounds=[[bl[0], bl[1]], [tr[0], tr[1]]],
            color='blue',
            weight=2,
            fill=True,
            fill_color='blue',
            fill_opacity=0.1,
            popup='Grid Cell',
        ).add_to(m)

    if enable_click:
        click_js_simple = '''
        function onMapClick(e) {
            var lat = e.latlng.lat.toFixed(6);
            var lon = e.latlng.lng.toFixed(6);
            prompt("Copy this coordinate:", lat + "," + lon);
        }
        map.on('click', onMapClick);
        '''
        click_element = folium.Element(f'<script>{click_js_simple}</script>')
        m.get_root().html.add_child(click_element)

        note_html = '''
        <div style="position: fixed;
                    bottom: 10px; left: 50px; width: 350px; height: 30px;
                    background-color: lightyellow; border:1px solid grey;
                    z-index:9999; font-size:12px;
                    padding: 5px 10px;">
            Click on map to get coordinates (copy & paste into GUI)
        </div>
        '''
        m.get_root().html.add_child(folium.Element(note_html))

    return m._repr_html_()


def create_map_for_multiple_points_html(
    points_data: list[dict],
    enable_click: bool = False,
    map_title: str = 'BARRA2 Grid Points',
) -> str:
    """Create a map showing multiple points and return as HTML string.

    Args:
        points_data: List of dicts with 'lat', 'lon', 'label', 'grid_points'.
        enable_click: If True, add click event for adding coordinates.
        map_title: Title displayed on the map.

    Returns:
        HTML string of the map.
    """
    if not points_data:
        raise ValueError("No points provided.")

    avg_lat = sum(p['lat'] for p in points_data) / len(points_data)
    avg_lon = sum(p['lon'] for p in points_data) / len(points_data)

    m = folium.Map(
        location=[avg_lat, avg_lon],
        zoom_start=6,
        control_scale=True,
    )

    title_html = f'''
    <div style="position: fixed;
                top: 10px; left: 50px; width: 400px; height: 40px;
                background-color: white; border:2px solid grey;
                z-index:9999; font-size:16px; font-weight:bold;
                padding: 10px;">
        {map_title}
    </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))

    basemaps = [
        ('CartoDB Positron', 'https://cartodb-basemaps-a.global.ssl.fastly.net/light_all/{z}/{x}/{y}.png', 'CartoDB'),
        ('CartoDB Dark', 'https://cartodb-basemaps-a.global.ssl.fastly.net/dark_all/{z}/{x}/{y}.png', 'CartoDB'),
        ('Esri Satellite', 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 'Esri'),
        ('Esri Terrain', 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', 'Esri'),
    ]
    for name, url, attr in basemaps:
        folium.TileLayer(url, attr=attr, name=name, overlay=False).add_to(m)
    folium.LayerControl().add_to(m)

    colors = ['red', 'green', 'purple', 'orange', 'pink', 'cadetblue']

    for i, pt_data in enumerate(points_data):
        color = colors[i % len(colors)]
        label = pt_data.get('label', f'Point {i+1}')
        lat = pt_data['lat']
        lon = pt_data['lon']

        folium.Marker(
            [lat, lon],
            popup=folium.Popup(
                f"<b>{label}</b><br>Lat: {lat:.4f}<br>Lon: {lon:.4f}",
                max_width=250,
            ),
            icon=folium.Icon(color=color, icon='star', prefix='fa'),
            tooltip=label,
        ).add_to(m)

        grid_points = pt_data.get('grid_points', [])
        for gp in grid_points:
            gp_lon = normalize_longitude(gp['lon'])
            folium.CircleMarker(
                [gp['lat'], gp_lon],
                radius=5,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.6,
                popup=folium.Popup(
                    f"<b>{label} - {gp['label']}</b><br>"
                    f"Lat: {gp['lat']:.2f}<br>"
                    f"Lon: {gp_lon:.2f}<br>"
                    f"Dist: {gp['distance_km']:.2f} km",
                    max_width=250,
                ),
            ).add_to(m)

        if len(grid_points) == 4:
            bl = [grid_points[2]['lat'], normalize_longitude(grid_points[2]['lon'])]
            tr = [grid_points[0]['lat'], normalize_longitude(grid_points[1]['lon'])]
            folium.Rectangle(
                bounds=[[bl[0], bl[1]], [tr[0], tr[1]]],
                color=color,
                weight=1.5,
                fill=True,
                fill_color=color,
                fill_opacity=0.08,
            ).add_to(m)

    if enable_click:
        click_js = '''
        function onMapClick(e) {
            var lat = e.latlng.lat.toFixed(6);
            var lon = e.latlng.lng.toFixed(6);
            prompt("Copy this coordinate:", lat + "," + lon);
        }
        map.on('click', onMapClick);
        '''
        m.get_root().html.add_child(folium.Element(f'<script>{click_js}</script>'))

        note_html = '''
        <div style="position: fixed;
                    bottom: 10px; left: 50px; width: 380px; height: 30px;
                    background-color: lightyellow; border:1px solid grey;
                    z-index:9999; font-size:12px;
                    padding: 5px 10px;">
            Click on map to get coordinates (copy & paste into GUI)
        </div>
        '''
        m.get_root().html.add_child(folium.Element(note_html))

    return m._repr_html_()


def create_map_for_multiple_points(
    points_data: list[dict],
    enable_click: bool = False,
    map_title: str = 'BARRA2 Grid Points',
) -> str:
    """Create a map showing multiple input coordinates and their grid points.

    Args:
        points_data: List of dicts, each with:
            - 'lat': input latitude
            - 'lon': input longitude
            - 'label': point label
            - 'grid_points': list of grid point dicts
        enable_click: If True, add click event for adding coordinates.
        map_title: Title displayed on the map.

    Returns:
        Path to the generated HTML file.
    """
    if not points_data:
        raise ValueError("No points provided.")

    # Use the center of all points as map center
    avg_lat = sum(p['lat'] for p in points_data) / len(points_data)
    avg_lon = sum(p['lon'] for p in points_data) / len(points_data)

    # Create map
    m = folium.Map(
        location=[avg_lat, avg_lon],
        zoom_start=6,
        control_scale=True,
    )

    # Title
    title_html = f'''
    <div style="position: fixed;
                top: 10px; left: 50px; width: 400px; height: 40px;
                background-color: white; border:2px solid grey;
                z-index:9999; font-size:16px; font-weight:bold;
                padding: 10px;">
        {map_title}
    </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))

    # Basemaps
    basemaps = [
        ('CartoDB Positron', 'https://cartodb-basemaps-a.global.ssl.fastly.net/light_all/{z}/{x}/{y}.png', 'CartoDB'),
        ('CartoDB Dark', 'https://cartodb-basemaps-a.global.ssl.fastly.net/dark_all/{z}/{x}/{y}.png', 'CartoDB'),
        ('Esri Satellite', 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 'Esri'),
        ('Esri Terrain', 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', 'Esri'),
    ]
    for name, url, attr in basemaps:
        folium.TileLayer(url, attr=attr, name=name, overlay=False).add_to(m)
    folium.LayerControl().add_to(m)

    # Colors for different input points
    colors = ['red', 'green', 'purple', 'orange', 'pink', 'cadetblue']

    for i, pt_data in enumerate(points_data):
        color = colors[i % len(colors)]
        label = pt_data.get('label', f'Point {i+1}')
        lat = pt_data['lat']
        lon = pt_data['lon']

        # Input point marker
        folium.Marker(
            [lat, lon],
            popup=folium.Popup(
                f"<b>{label}</b><br>Lat: {lat:.4f}<br>Lon: {lon:.4f}",
                max_width=250,
            ),
            icon=folium.Icon(color=color, icon='star', prefix='fa'),
            tooltip=label,
        ).add_to(m)

        # Grid points
        grid_points = pt_data.get('grid_points', [])
        for gp in grid_points:
            gp_lon = normalize_longitude(gp['lon'])
            folium.CircleMarker(
                [gp['lat'], gp_lon],
                radius=5,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.6,
                popup=folium.Popup(
                    f"<b>{label} - {gp['label']}</b><br>"
                    f"Lat: {gp['lat']:.2f}<br>"
                    f"Lon: {gp_lon:.2f}<br>"
                    f"Dist: {gp['distance_km']:.2f} km",
                    max_width=250,
                ),
            ).add_to(m)

        # Grid cell rectangle
        if len(grid_points) == 4:
            bl = [grid_points[2]['lat'], normalize_longitude(grid_points[2]['lon'])]
            tr = [grid_points[0]['lat'], normalize_longitude(grid_points[1]['lon'])]
            folium.Rectangle(
                bounds=[[bl[0], bl[1]], [tr[0], tr[1]]],
                color=color,
                weight=1.5,
                fill=True,
                fill_color=color,
                fill_opacity=0.08,
            ).add_to(m)

    # Click handler
    if enable_click:
        click_js = '''
        function onMapClick(e) {
            var lat = e.latlng.lat.toFixed(6);
            var lon = e.latlng.lng.toFixed(6);
            prompt("Copy this coordinate:", lat + "," + lon);
        }
        map.on('click', onMapClick);
        '''
        m.get_root().html.add_child(folium.Element(f'<script>{click_js}</script>'))

        note_html = '''
        <div style="position: fixed;
                    bottom: 10px; left: 50px; width: 380px; height: 30px;
                    background-color: lightyellow; border:1px solid grey;
                    z-index:9999; font-size:12px;
                    padding: 5px 10px;">
            Click on map to get coordinates (copy & paste into GUI)
        </div>
        '''
        m.get_root().html.add_child(folium.Element(note_html))

    # Save
    tmp_dir = tempfile.mkdtemp(prefix='barra2_map_')
    html_path = os.path.join(tmp_dir, 'map.html')
    m.save(html_path)
    return html_path


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from scripts.grid_finder import find_nearest_four_grid_points

    print("Testing map_viewer.py")
    lat, lon = -23.55, 133.40
    print(f"Generating map for Alice Springs ({lat}, {lon})...")

    grid_points = find_nearest_four_grid_points(lat, lon, 'AUS11')
    html_path = create_map_with_points(lat, lon, grid_points, enable_click=True)
    print(f"Map saved to: {html_path}")
    print("Opening in browser...")
    open_map_in_browser(html_path)
