"""BARRA2 Data Downloader GUI.

A Windows desktop application for:
1. Entering coordinates and finding nearest BARRA2 grid points
2. Visualizing coordinates and grid points on an interactive map
3. Selecting variables and downloading BARRA2 reanalysis data

Usage:
    python scripts/barra2_gui.py
"""
import os
import re
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pandas as pd

# Ensure parent directory is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import barra2_dl
from barra2_dl.globals import (
    BARRA2_INDEX,
    BARRA2_URL_AUS11_1HR,
    BARRA2_URL_AUST04_1HR,
)
from scripts.grid_finder import (
    BARRA2_ENV_VARIABLES,
    BARRA2_WIND_VARIABLES,
    BARRA2_WIND_HEIGHTS,
    BARRA2_GRID_PARAMS,
    find_nearest_four_grid_points,
    normalize_longitude,
)
from scripts.map_viewer import (
    create_map_for_multiple_points,
    create_map_for_multiple_points_html,
    create_map_with_points,
    create_map_html_string,
    open_map_in_browser,
)

# Try to import pywebview, fall back to browser if not available
try:
    import webview
    HAS_PYWEBVIEW = True
except ImportError:
    HAS_PYWEBVIEW = False

# Map resolution key to URL
RESOLUTION_URL_MAP = {
    'AUS11': BARRA2_URL_AUS11_1HR,
    'AUST04': BARRA2_URL_AUST04_1HR,
}


class Barra2GUI:
    """Main GUI application class."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BARRA2 Data Downloader")
        self.root.geometry("1000x750")
        self.root.minsize(900, 700)

        # State: list of user coordinates
        # Each entry: {'label': str, 'lat': float, 'lon': float, 'grid_points': list, 'selected_grid_points': set}
        self.coordinates = []
        self.downloading = False
        self.map_window = None  # For pywebview window

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        """Construct the entire GUI layout."""
        # Menu
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

        # Main paned window
        main_pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pw.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Left panel: Coordinates ---
        left_frame = ttk.LabelFrame(main_pw, text="Coordinates & Grid Points", padding=5)
        main_pw.add(left_frame, weight=1)

        # Input row
        input_frame = ttk.Frame(left_frame)
        input_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(input_frame, text="Label:").pack(side=tk.LEFT)
        self.label_var = tk.StringVar(value="Point1")
        ttk.Entry(input_frame, textvariable=self.label_var, width=10).pack(side=tk.LEFT, padx=(2, 5))

        ttk.Label(input_frame, text="Lat:").pack(side=tk.LEFT)
        self.lat_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.lat_var, width=9).pack(side=tk.LEFT, padx=(2, 5))

        ttk.Label(input_frame, text="Lon:").pack(side=tk.LEFT)
        self.lon_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.lon_var, width=9).pack(side=tk.LEFT, padx=(2, 5))

        ttk.Button(input_frame, text="Add", command=self.add_coordinate).pack(side=tk.LEFT, padx=2)
        ttk.Button(input_frame, text="Remove", command=self.remove_coordinate).pack(side=tk.LEFT, padx=2)

        # Coordinate list with scrollbar
        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        columns = ('label', 'lat', 'lon', 'selected_grids')
        self.coord_tree = ttk.Treeview(list_frame, columns=columns, show='headings', selectmode='browse')
        self.coord_tree.heading('label', text='Label')
        self.coord_tree.heading('lat', text='Lat')
        self.coord_tree.heading('lon', text='Lon')
        self.coord_tree.heading('selected_grids', text='Selected Grids')

        self.coord_tree.column('label', width=80, anchor='center')
        self.coord_tree.column('lat', width=80, anchor='center')
        self.coord_tree.column('lon', width=80, anchor='center')
        self.coord_tree.column('selected_grids', width=120, anchor='center')

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.coord_tree.yview)
        self.coord_tree.configure(yscrollcommand=scrollbar.set)
        self.coord_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Bind selection event
        self.coord_tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # Buttons below list
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="Select All", command=self.select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Deselect All", command=self.deselect_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Show Map", command=self.show_map).pack(side=tk.LEFT, padx=2)

        # Grid point selection panel
        grid_sel_frame = ttk.LabelFrame(left_frame, text="Grid Points Selection (select 1-4)", padding=3)
        grid_sel_frame.pack(fill=tk.X, pady=(5, 0))

        # Use a canvas with scrollbar for grid checkboxes
        self.grid_canvas = tk.Canvas(grid_sel_frame, height=100)
        self.grid_scrollbar = ttk.Scrollbar(grid_sel_frame, orient=tk.VERTICAL, command=self.grid_canvas.yview)
        self.grid_inner_frame = ttk.Frame(self.grid_canvas)

        self.grid_inner_frame.bind(
            "<Configure>",
            lambda e: self.grid_canvas.configure(scrollregion=self.grid_canvas.bbox("all")),
        )
        self.grid_canvas.create_window((0, 0), window=self.grid_inner_frame, anchor="nw")
        self.grid_canvas.configure(yscrollcommand=self.grid_scrollbar.set)

        self.grid_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.grid_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.grid_check_vars = {}  # {coord_idx: {grid_label: tk.BooleanVar}}
        self.grid_checkboxes = {}  # {coord_idx: {grid_label: ttk.Checkbutton}}

        # Grid points detail
        detail_frame = ttk.LabelFrame(left_frame, text="Grid Points Detail", padding=3)
        detail_frame.pack(fill=tk.X, pady=(5, 0))
        self.detail_text = tk.Text(detail_frame, height=5, width=60, font=('Consolas', 9))
        self.detail_text.pack(fill=tk.X)
        self.detail_text.insert('1.0', 'Add coordinates and select a row to see grid point details.')
        self.detail_text.config(state='disabled')

        # --- Right panel: Settings ---
        right_frame = ttk.Frame(main_pw)
        main_pw.add(right_frame, weight=1)

        # Resolution
        res_frame = ttk.LabelFrame(right_frame, text="Resolution", padding=5)
        res_frame.pack(fill=tk.X, pady=(0, 5))
        self.resolution_var = tk.StringVar(value='AUS11')
        for key, params in BARRA2_GRID_PARAMS.items():
            ttk.Radiobutton(
                res_frame, text=f"{params['url']} ({params['spacing']} deg)",
                variable=self.resolution_var, value=key,
                command=self._on_resolution_change,
            ).pack(anchor='w')
        self.resolution_var.trace_add('write', lambda *_: self._on_resolution_change())

        # Variable selection
        var_frame = ttk.LabelFrame(right_frame, text="Variables", padding=5)
        var_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # Category buttons
        cat_frame = ttk.Frame(var_frame)
        cat_frame.pack(fill=tk.X, pady=(0, 3))
        ttk.Button(cat_frame, text="Select All", command=self.select_all_vars).pack(side=tk.LEFT, padx=1)
        ttk.Button(cat_frame, text="Deselect All", command=self.deselect_all_vars).pack(side=tk.LEFT, padx=1)
        ttk.Button(cat_frame, text="Select All Wind", command=self.select_all_wind).pack(side=tk.LEFT, padx=1)
        ttk.Button(cat_frame, text="Deselect All Wind", command=self.deselect_all_wind).pack(side=tk.LEFT, padx=1)

        # Variable list with checkboxes (classified)
        var_list_frame = ttk.Frame(var_frame)
        var_list_frame.pack(fill=tk.BOTH, expand=True)

        self.var_canvas = tk.Canvas(var_list_frame)
        var_scrollbar = ttk.Scrollbar(var_list_frame, orient=tk.VERTICAL, command=self.var_canvas.yview)
        self.var_inner_frame = ttk.Frame(self.var_canvas)

        self.var_inner_frame.bind(
            "<Configure>",
            lambda e: self.var_canvas.configure(scrollregion=self.var_canvas.bbox("all")),
        )
        self.var_canvas.create_window((0, 0), window=self.var_inner_frame, anchor="nw")
        self.var_canvas.configure(yscrollcommand=var_scrollbar.set)

        self.var_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        var_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.var_checkboxes = {}

        # Environment variables section
        ttk.Label(self.var_inner_frame, text="Environment Variables", font=('', 9, 'bold')).pack(anchor='w', pady=(3, 1))
        for var_name, (desc, unit) in BARRA2_ENV_VARIABLES.items():
            var_var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(
                self.var_inner_frame,
                text=f"{var_name} - {desc} ({unit})",
                variable=var_var,
            )
            cb.pack(anchor='w', padx=(10, 0), pady=1)
            self.var_checkboxes[var_name] = var_var

        # Wind variables section (grouped by height)
        ttk.Separator(self.var_inner_frame, orient='horizontal').pack(fill=tk.X, pady=4)
        ttk.Label(self.var_inner_frame, text="Wind Variables", font=('', 9, 'bold')).pack(anchor='w', pady=(0, 1))
        for height in BARRA2_WIND_HEIGHTS:
            ttk.Label(self.var_inner_frame, text=f"  Wind @ {height}m", font=('', 8)).pack(anchor='w', pady=(2, 0))
            ua_key = f'ua{height}m'
            va_key = f'va{height}m'
            for wkey in [ua_key, va_key]:
                desc, unit = BARRA2_WIND_VARIABLES[wkey]
                var_var = tk.BooleanVar(value=False)
                cb = ttk.Checkbutton(
                    self.var_inner_frame,
                    text=f"    {wkey} - {desc} ({unit})",
                    variable=var_var,
                )
                cb.pack(anchor='w', padx=(10, 0), pady=0)
                self.var_checkboxes[wkey] = var_var

        # Time range
        time_frame = ttk.LabelFrame(right_frame, text="Time Range", padding=5)
        time_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(time_frame, text="Start:").grid(row=0, column=0, sticky='w')
        self.start_date_var = tk.StringVar(value="2023-01-01")
        ttk.Entry(time_frame, textvariable=self.start_date_var, width=12).grid(row=0, column=1, padx=5, pady=2)

        ttk.Label(time_frame, text="End:").grid(row=1, column=0, sticky='w')
        self.end_date_var = tk.StringVar(value="2023-03-31")
        ttk.Entry(time_frame, textvariable=self.end_date_var, width=12).grid(row=1, column=1, padx=5, pady=2)

        # Output settings
        out_frame = ttk.LabelFrame(right_frame, text="Output", padding=5)
        out_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(out_frame, text="Output:").grid(row=0, column=0, sticky='w')
        self.output_dir_var = tk.StringVar(value='')
        output_entry = ttk.Entry(out_frame, textvariable=self.output_dir_var, width=20)
        output_entry.grid(row=0, column=1, padx=5, pady=2)
        ttk.Button(out_frame, text="...", width=3, command=self._browse_output).grid(row=0, column=2)

        ttk.Label(out_frame, text="Prefix:").grid(row=1, column=0, sticky='w')
        self.prefix_var = tk.StringVar(value='barra2')
        ttk.Entry(out_frame, textvariable=self.prefix_var, width=20).grid(row=1, column=1, padx=5, pady=2)

        # Download buttons
        dl_frame = ttk.Frame(right_frame)
        dl_frame.pack(fill=tk.X, pady=5)
        self.download_btn = ttk.Button(dl_frame, text="Download", command=self.start_download)
        self.download_btn.pack(fill=tk.X, pady=2)
        ttk.Button(dl_frame, text="Download & Convert", command=self.start_download_with_convert).pack(fill=tk.X, pady=2)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w')
        status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=5, pady=2)

    # -------------------------------------------------------- Actions
    def add_coordinate(self):
        """Add a coordinate from the input fields."""
        label = self.label_var.get().strip()
        lat_str = self.lat_var.get().strip()
        lon_str = self.lon_var.get().strip()

        if not lat_str or not lon_str:
            messagebox.showwarning("Input Error", "Please enter latitude and longitude.")
            return

        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            messagebox.showerror("Input Error", "Latitude and longitude must be numbers.")
            return

        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            messagebox.showerror("Input Error", "Lat: -90~90, Lon: -180~180.")
            return

        resolution = self.resolution_var.get()
        try:
            grid_points = find_nearest_four_grid_points(lat, lon, resolution)
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            return

        # Select all 4 grid points by default
        selected_grids = {gp['label'] for gp in grid_points}

        entry = {
            'label': label or f"Point{len(self.coordinates)+1}",
            'lat': lat,
            'lon': lon,
            'grid_points': grid_points,
            'selected_grid_points': selected_grids,
        }
        self.coordinates.append(entry)

        self._refresh_grid_checks(len(self.coordinates) - 1)
        self._refresh_tree()
        self.status_var.set(f"Added {entry['label']} ({lat}, {lon}) - 4 grid points available")

        # Auto-increment label
        self.label_var.set(f"Point{len(self.coordinates)+1}")
        self.lat_var.set('')
        self.lon_var.set('')

    def remove_coordinate(self):
        """Remove the selected coordinate."""
        sel = self.coord_tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Select a row to remove.")
            return
        idx = self.coord_tree.index(sel[0])
        removed = self.coordinates.pop(idx)
        # Clear and rebuild grid checkboxes
        for i in range(len(self.coordinates)):
            self._refresh_grid_checks(i)
        self._refresh_tree()
        self.status_var.set(f"Removed {removed['label']}")

    def select_all(self):
        """Select all grid points for download."""
        for coord in self.coordinates:
            coord['selected_grid_points'] = {gp['label'] for gp in coord['grid_points']}
        for i in range(len(self.coordinates)):
            self._update_grid_checks(i)
        self._refresh_tree()
        self.status_var.set("Selected all grid points.")

    def deselect_all(self):
        """Deselect all grid points."""
        for coord in self.coordinates:
            coord['selected_grid_points'] = set()
        for i in range(len(self.coordinates)):
            self._update_grid_checks(i)
        self._refresh_tree()
        self.status_var.set("Deselected all grid points.")

    def _on_tree_select(self, event):
        """Show grid point details and update checkboxes for selected row."""
        sel = self.coord_tree.selection()
        if not sel:
            return
        idx = self.coord_tree.index(sel[0])
        coord = self.coordinates[idx]

        # Update checkbox states for this coordinate
        self._update_grid_checks(idx)

        # Show detail
        self.detail_text.config(state='normal')
        self.detail_text.delete('1.0', tk.END)
        selected = coord['selected_grid_points']
        text = f"  {coord['label']}: ({coord['lat']:.4f}, {coord['lon']:.4f})\n"
        text += "-" * 55 + "\n"
        for gp in coord['grid_points']:
            gp_lon = normalize_longitude(gp['lon'])
            check_mark = "[√]" if gp['label'] in selected else "[ ]"
            text += f"  {check_mark} {gp['label']:12s}  ({gp['lat']:8.2f}, {gp_lon:9.2f})  dist={gp['distance_km']:.2f} km\n"
        self.detail_text.insert('1.0', text)
        self.detail_text.config(state='disabled')

    def _on_resolution_change(self):
        """Recalculate grid points when resolution changes."""
        if not self.coordinates:
            return
        resolution = self.resolution_var.get()
        for coord in self.coordinates:
            try:
                coord['grid_points'] = find_nearest_four_grid_points(coord['lat'], coord['lon'], resolution)
                coord['selected_grid_points'] = {gp['label'] for gp in coord['grid_points']}
            except ValueError:
                pass
        for i in range(len(self.coordinates)):
            self._refresh_grid_checks(i)
        self._refresh_tree()
        self.status_var.set(f"Resolution changed to {resolution}, grid points recalculated.")

    def _refresh_grid_checks(self, coord_idx: int):
        """Initialize grid checkboxes for a coordinate."""
        if coord_idx >= len(self.coordinates):
            return

        # Clear existing checkboxes for this coord_idx
        if coord_idx in self.grid_checkboxes:
            for cb in self.grid_checkboxes[coord_idx].values():
                cb.destroy()
        self.grid_checkboxes[coord_idx] = {}

        coord = self.coordinates[coord_idx]

        # Create checkbox row for each grid point
        for row_idx, gp in enumerate(coord['grid_points']):
            label = gp['label']
            lon_val = normalize_longitude(gp['lon'])
            dist = gp['distance_km']

            var = tk.BooleanVar(value=(label in coord['selected_grid_points']))
            if coord_idx not in self.grid_check_vars:
                self.grid_check_vars[coord_idx] = {}
            self.grid_check_vars[coord_idx][label] = var

            cb = ttk.Checkbutton(
                self.grid_inner_frame,
                text=f"{label}: ({gp['lat']:.2f}, {lon_val:.2f}) {dist:.1f}km",
                variable=var,
                command=lambda idx=coord_idx, lbl=label: self._on_grid_check_change(idx, lbl)
            )
            cb.grid(row=coord_idx * 4 + row_idx, column=0, sticky='w', padx=5, pady=1)
            self.grid_checkboxes[coord_idx][label] = cb

    def _update_grid_checks(self, coord_idx: int):
        """Update checkbox states to match selected grid points."""
        if coord_idx >= len(self.coordinates):
            return
        coord = self.coordinates[coord_idx]
        for row_idx, gp in enumerate(coord['grid_points']):
            label = gp['label']
            if label in self.grid_check_vars[coord_idx]:
                self.grid_check_vars[coord_idx][label].set(label in coord['selected_grid_points'])

    def _on_grid_check_change(self, coord_idx: int, grid_label: str):
        """Handle grid checkbox change."""
        if coord_idx >= len(self.coordinates):
            return
        coord = self.coordinates[coord_idx]
        is_selected = self.grid_check_vars[coord_idx][grid_label].get()
        if is_selected:
            coord['selected_grid_points'].add(grid_label)
        else:
            coord['selected_grid_points'].discard(grid_label)
        self._refresh_tree()

    def select_all_vars(self):
        """Select all variables."""
        for var in self.var_checkboxes.values():
            var.set(True)

    def deselect_all_vars(self):
        """Deselect all variables."""
        for var in self.var_checkboxes.values():
            var.set(False)

    def select_all_wind(self):
        """Select all wind variables only."""
        for key, var in self.var_checkboxes.items():
            if key.startswith('ua') or key.startswith('va'):
                var.set(True)

    def deselect_all_wind(self):
        """Deselect all wind variables only."""
        for key, var in self.var_checkboxes.items():
            if key.startswith('ua') or key.startswith('va'):
                var.set(False)

    def show_map(self):
        """Generate and display a folium map in GUI window."""
        if not self.coordinates:
            messagebox.showinfo("Info", "Add coordinates first.")
            return

        points_data = []
        for coord in self.coordinates:
            points_data.append({
                'lat': coord['lat'],
                'lon': coord['lon'],
                'label': coord['label'],
                'grid_points': coord['grid_points'],
            })

        self.status_var.set("Generating map...")
        self.root.update_idletasks()

        try:
            if HAS_PYWEBVIEW:
                # Use pywebview to display in GUI window
                html_string = create_map_for_multiple_points_html(points_data, enable_click=True)
                if self.map_window:
                    self.map_window.destroy()
                self.map_window = webview.create_window(
                    'BARRA2 Map',
                    html=html_string,
                    width=900,
                    height=700,
                )
                webview.start()
                self.status_var.set("Map displayed in GUI window.")
            else:
                # Fall back to browser
                html_path = create_map_for_multiple_points(points_data, enable_click=True)
                open_map_in_browser(html_path)
                self.status_var.set(f"Map opened in browser (pywebview not installed).")
                messagebox.showinfo("Info", "pywebview not installed. Map opened in browser.")
        except Exception as e:
            messagebox.showerror("Map Error", str(e))
            self.status_var.set("Map generation failed.")

    def _browse_output(self):
        """Browse for output directory."""
        d = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if d:
            self.output_dir_var.set(d)

    def _get_selected_variables(self) -> list[str]:
        """Return list of selected variable names."""
        return [name for name, var in self.var_checkboxes.items() if var.get()]

    def _get_selected_coords(self) -> list[dict]:
        """Return list of coordinates that have at least one grid point selected."""
        return [c for c in self.coordinates if c['selected_grid_points']]

    # -------------------------------------------------------- Download
    def start_download(self):
        """Start downloading in a background thread (download only)."""
        self._run_download_thread(convert=False)

    def start_download_with_convert(self):
        """Start downloading in a background thread (download + merge + convert)."""
        self._run_download_thread(convert=True)

    def _run_download_thread(self, convert: bool):
        """Run download in a background thread."""
        if self.downloading:
            messagebox.showinfo("Info", "A download is already in progress.")
            return

        vars_list = self._get_selected_variables()
        if not vars_list:
            messagebox.showwarning("Warning", "Please select at least one variable.")
            return

        selected_coords = self._get_selected_coords()
        if not selected_coords:
            messagebox.showwarning("Warning", "Please select at least one grid point for download.")
            return

        # Parse time
        try:
            start_dt = datetime.strptime(self.start_date_var.get(), "%Y-%m-%d")
            end_dt = datetime.strptime(self.end_date_var.get(), "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            messagebox.showerror("Error", "Invalid date format. Use YYYY-MM-DD.")
            return

        resolution = self.resolution_var.get()
        barra2_url = RESOLUTION_URL_MAP[resolution]
        base_dir = os.path.join(os.path.dirname(__file__), '..')
        output_dir = self.output_dir_var.get().strip()
        if not output_dir:
            messagebox.showwarning("Warning", "Please select an Output folder.")
            return
        output_dir = os.path.abspath(output_dir)
        cache_dir = os.path.join(output_dir, 'source')
        prefix = self.prefix_var.get()

        # Disable button
        self.downloading = True
        self.download_btn.config(state='disabled')
        self.status_var.set("Starting download...")

        thread = threading.Thread(
            target=self._download_worker,
            args=(selected_coords, vars_list, barra2_url, start_dt, end_dt,
                  cache_dir, output_dir, prefix, resolution, convert),
            daemon=True,
        )
        thread.start()

    def _download_worker(
        self,
        coords: list[dict],
        variables: list[str],
        barra2_url: str,
        start_dt: datetime,
        end_dt: datetime,
        cache_dir: str,
        output_dir: str,
        prefix: str,
        resolution: str,
        convert: bool,
    ):
        """Worker function that runs in background thread."""
        # Count total grid points to download
        total_grid_points = sum(len(c['selected_grid_points']) for c in coords)
        total_files = 0
        success_files = 0
        failed_files = 0

        try:
            grid_counter = 0
            for ci, coord in enumerate(coords):
                selected_grids = coord['selected_grid_points']
                if not selected_grids:
                    continue

                for grid_label in selected_grids:
                    grid_pt = next(gp for gp in coord['grid_points'] if gp['label'] == grid_label)
                    grid_lat = grid_pt['lat']
                    grid_lon = normalize_longitude(grid_pt['lon'])
                    grid_coord_str = f"{grid_lat:.2f}_{grid_lon:.2f}"

                    grid_counter += 1
                    self.root.after(0, self.status_var.set,
                        f"[{grid_counter}/{total_grid_points}] Downloading {coord['label']}/{grid_coord_str}...")

                    # Cache subfolder per grid point
                    subfolder_name = f"{coord['label']}_{grid_coord_str}"
                    subfolder_path = Path(cache_dir) / subfolder_name
                    subfolder_path.mkdir(parents=True, exist_ok=True)

                    fileout_prefix = f"{prefix}_{coord['label']}_{grid_coord_str}"

                    urlfilenames = barra2_dl.download.point_data_urlfilenames(
                        barra2_url=barra2_url,
                        barra2_vars=variables,
                        latitude=grid_lat,
                        longitude=grid_lon,
                        start_datetime=start_dt,
                        end_datetime=end_dt,
                        fileout_prefix=fileout_prefix,
                    )
                    total_files += len(urlfilenames)

                    for url, filename in urlfilenames:
                        try:
                            folder_file = subfolder_path / filename
                            if folder_file.exists():
                                success_files += 1
                                continue

                            import requests
                            response = requests.get(url)
                            if response.status_code == 200:
                                folder_file.write_bytes(response.content)
                                success_files += 1
                                self.root.after(0, self.status_var.set,
                                    f"[{grid_counter}/{total_grid_points}] Downloaded: {filename}")
                            else:
                                failed_files += 1
                                self.root.after(0, self.status_var.set,
                                    f"[{grid_counter}/{total_grid_points}] Failed: {filename} (HTTP {response.status_code})")
                        except Exception as e:
                            failed_files += 1
                            self.root.after(0, self.status_var.set,
                                f"[{grid_counter}/{total_grid_points}] Error: {filename} - {str(e)[:60]}")

                    # Pre-process timestamps: shift :30 variables (pr, rsds) by -30min
                    # before merge to avoid duplicate time rows from outer join
                    TIMESTAMP_SHIFT_VARS = {'pr', 'rsds'}
                    self.root.after(0, self.status_var.set,
                        f"[{grid_counter}/{total_grid_points}] Aligning timestamps for {grid_coord_str}...")
                    for csv_file in sorted(subfolder_path.glob(f'{fileout_prefix}*.csv')):
                        try:
                            df_pre = pd.read_csv(csv_file)
                            if df_pre['time'].str.contains(':30:', na=False).iloc[0]:
                                # Extract variable name: strip known prefix, match against shift vars
                                prefix_stripped = csv_file.stem[len(fileout_prefix)+1:]
                                var_name = next(
                                    (v for v in TIMESTAMP_SHIFT_VARS if prefix_stripped.startswith(v + '_')),
                                    None,
                                )
                                if var_name in TIMESTAMP_SHIFT_VARS:
                                    # Shift -30min to align :30 timestamps to :00
                                    df_pre['time'] = pd.to_datetime(df_pre['time']) - pd.Timedelta(minutes=30)
                                    df_pre['time'] = df_pre['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
                                    df_pre.to_csv(csv_file, index=False)
                        except Exception:
                            pass  # skip files that don't need shifting or fail

                    # Merge this grid point's CSVs into one file
                    self.root.after(0, self.status_var.set,
                        f"[{grid_counter}/{total_grid_points}] Merging {coord['label']}/{grid_coord_str}...")
                    try:
                        df = barra2_dl.merge.merge_csvs_to_df(
                            filein_folder=str(subfolder_path),
                            filename_pattern=f'{fileout_prefix}*.csv',
                            index_for_join=BARRA2_INDEX,
                        )

                        if df.empty:
                            self.root.after(0, self.status_var.set,
                                f"[{grid_counter}/{total_grid_points}] No data to merge for {grid_coord_str}")
                            continue

                        if convert:

                            df = barra2_dl.convert.convert_environment_variables(df)
                            df = barra2_dl.convert.convert_wind_components(df)

                            # Keep only: index columns, converted env vars, wind speed/direction, hurs, ta50m
                            index_cols = ['time', 'station',
                                'latitude[unit="degrees_north"]',
                                'longitude[unit="degrees_east"]']
                            keep_patterns = [
                                '_celsius', '_hPa', '_mmhr', '_gkg',   # converted env vars
                                'v\\d+m\\[unit="m s-1"\\]',             # wind speed v*h
                                'phi_met',                               # wind direction
                                'hurs', 'ta50m', 'rsds',                    # no conversion needed
                            ]
                            keep_cols = [c for c in df.columns if c in index_cols]
                            for pat in keep_patterns:
                                keep_cols.extend([c for c in df.columns if re.search(pat, c)])
                            # deduplicate while preserving order
                            seen = set()
                            final_cols = []
                            for c in keep_cols:
                                if c not in seen:
                                    seen.add(c)
                                    final_cols.append(c)
                            df = df[final_cols]

                        output_path = Path(output_dir)
                        output_path.mkdir(parents=True, exist_ok=True)
                        outfile = output_path / f"{fileout_prefix}_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}.csv"
                        df.to_csv(outfile, index=False)
                        self.root.after(0, self.status_var.set,
                            f"[{grid_counter}/{total_grid_points}] Saved: {outfile.name} ({len(df)} rows, {len(df.columns)} cols)")
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        self.root.after(0, self.status_var.set,
                            f"[{grid_counter}/{total_grid_points}] Merge/convert error: {str(e)[:120]}")

            # Summary
            msg = f"Download complete: {success_files} success, {failed_files} failed (total {total_files})"
            self.root.after(0, self.status_var.set, msg)

        except Exception as e:
            self.root.after(0, self.status_var.set, f"Download error: {str(e)[:80]}")
        finally:
            self.root.after(0, self._download_finished)

    def _download_finished(self):
        """Re-enable download button after completion."""
        self.downloading = False
        self.download_btn.config(state='normal')

    # -------------------------------------------------------- Tree
    def _refresh_tree(self):
        """Refresh the coordinate treeview."""
        for item in self.coord_tree.get_children():
            self.coord_tree.delete(item)

        for coord in self.coordinates:
            selected_grids = coord['selected_grid_points']
            selected_count = len(selected_grids)
            selected_str = f"{selected_count}/4" if selected_count > 0 else "None"

            self.coord_tree.insert('', 'end', values=(
                coord['label'],
                f"{coord['lat']:.4f}",
                f"{coord['lon']:.4f}",
                selected_str,
            ))


def main():
    root = tk.Tk()
    app = Barra2GUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
