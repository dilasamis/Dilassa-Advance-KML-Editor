# File: DilasaKMLTool_v4/ui/dialogs/historical_map_builder_dialog.py
# ----------------------------------------------------------------------
import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, 
                               QLineEdit, QListWidget, QListWidgetItem, QCheckBox, QSpinBox,
                               QFileDialog, QMessageBox, QProgressBar, QTextEdit, QScrollArea, QWidget, QGroupBox, QDialogButtonBox,
                               QAbstractItemView, QComboBox)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon

# Assuming these are correctly placed for import
from core.gee_handler import initialize_gee, get_ee_geometry_from_geojson, get_yearly_composite_image, get_image_download_url
from core.utils import resource_path
import geopandas as gpd # For reading shapefiles
import datetime
import requests

# Helper for centering, assuming it's available (e.g., from api_sources_dialog)
from .api_sources_dialog import center_dialog


class GEEProcessingThread(QThread):
    """Worker thread for long-running GEE tasks."""
    progress = Signal(int, str) # Overall progress (percentage, message)
    area_progress = Signal(str, int, str) # Area name, year progress (percentage, message)
    image_download_url = Signal(str, int, str, str) # Area name, year, download_url, format
    error = Signal(str)
    finished = Signal()

    def __init__(self, areas_data, years, satellite, composite_method, resolution, download_path_template):
        super().__init__()
        self.areas_data = areas_data # List of dicts: [{'name': 'Area1', 'ee_geometry': ee.Geometry, 'shapefile_path': '...'}, ...]
        self.years = years
        self.satellite = satellite
        self.composite_method = composite_method
        self.resolution = resolution
        self.download_path_template = download_path_template # e.g. "path/{area_name}/{year}.png"
        self._is_running = True

    def run(self):
        if not initialize_gee():
            self.error.emit("Failed to initialize Google Earth Engine. Please authenticate via command line ('earthengine authenticate') or check credentials.")
            self.finished.emit()
            return

        total_tasks = len(self.areas_data) * len(self.years)
        completed_tasks = 0

        for area_info in self.areas_data:
            if not self._is_running: break
            area_name = area_info['name']
            ee_geometry = area_info['ee_geometry']
            
            for year in self.years:
                if not self._is_running: break
                self.area_progress.emit(area_name, year, 0, f"Starting processing for {area_name} - {year}...")
                
                vis_params_s2 = {'bands': ['B4', 'B3', 'B2'], 'min': 0.0, 'max': 3000} # Sentinel-2 True Color
                vis_params_ls = {'bands': ['SR_B4', 'SR_B3', 'SR_B2'], 'min': 0.0, 'max': 0.3} # Landsat Surface Reflectance

                collection_id = "COPERNICUS/S2_SR_HARMONIZED" if self.satellite == "Sentinel-2 (10m)" else "LANDSAT/LC08/C02/T1_L2" # Example, adapt for Landsat 9 etc.
                bands = vis_params_s2['bands'] if "S2" in collection_id else vis_params_ls['bands']
                vis_p = vis_params_s2 if "S2" in collection_id else vis_params_ls


                processed_image = get_yearly_composite_image(
                    ee_geometry, year,
                    satellite_collection=collection_id,
                    bands_rgb=bands, # Pass the actual bands for processing
                    vis_params=vis_p, # Pass vis_params for the .visualize() call
                    resolution_meters=self.resolution,
                    compositing_method=self.composite_method.lower()
                )

                if not self._is_running: break
                if processed_image:
                    self.area_progress.emit(area_name, year, 50, f"Image processed for {area_name} - {year}. Getting download URL...")
                    
                    # We want a visual image (PNG) for display in map overlay later
                    # The get_yearly_composite_image should return the visualized image.
                    
                    # For downloading, we might want the raw bands or the visualized image.
                    # Let's assume get_yearly_composite_image already returns the visualized one.
                    file_format = 'PNG' 
                    
                    download_url = get_image_download_url(processed_image, ee_geometry, self.resolution, file_format)
                    
                    if not self._is_running: break
                    if download_url:
                        self.area_progress.emit(area_name, year, 75, f"Download URL obtained for {area_name} - {year}.")
                        self.image_download_url.emit(area_name, year, download_url, file_format)
                    else:
                        self.area_progress.emit(area_name, year, 75, f"Failed to get download URL for {area_name} - {year}.")
                        self.error.emit(f"Could not get download URL for {area_name} - {year}.")
                else:
                    self.area_progress.emit(area_name, year, 50, f"No image processed for {area_name} - {year}.")
                    self.error.emit(f"Failed to process image for {area_name} - {year}.")
                
                completed_tasks += 1
                overall_prog = int((completed_tasks / total_tasks) * 100)
                self.progress.emit(overall_prog, f"Processed {completed_tasks}/{total_tasks}...")
                self.area_progress.emit(area_name, year, 100, f"Finished task for {area_name} - {year}.")

        self.finished.emit()

    def stop(self):
        self._is_running = False


class HistoricalMapBuilderDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_main_window = parent # Assuming parent is MainWindow
        self.setWindowTitle("Historical Map Builder (GEE)")
        self.setMinimumSize(700, 550)
        self.setModal(True)

        self.shapefile_path = None
        self.geodataframe = None
        self.selected_area_geometries = [] # List of {'name': str, 'ee_geometry': ee.Geometry, 'shapefile_path': str}

        # --- Main Layout ---
        layout = QVBoxLayout(self)

        # --- Shapefile Selection ---
        shp_frame = QGroupBox("1. Select Area Definition (Shapefile)")
        shp_layout = QHBoxLayout(shp_frame)
        self.shp_path_edit = QLineEdit(); self.shp_path_edit.setPlaceholderText("Path to .shp file"); self.shp_path_edit.setReadOnly(True)
        self.shp_browse_button = QPushButton("Browse..."); self.shp_browse_button.clicked.connect(self.browse_shapefile)
        shp_layout.addWidget(self.shp_path_edit, 1); shp_layout.addWidget(self.shp_browse_button)
        layout.addWidget(shp_frame)

        # --- Area Selection (if multiple polygons in shapefile) ---
        area_frame = QGroupBox("2. Select Area(s) from Shapefile")
        area_layout = QVBoxLayout(area_frame)
        self.area_list_widget = QListWidget(); self.area_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        area_layout.addWidget(QLabel("Select one or more areas to process (Ctrl+Click):"))
        area_layout.addWidget(self.area_list_widget)
        layout.addWidget(area_frame)

        # --- Parameters ---
        params_frame = QGroupBox("3. Processing Parameters")
        params_layout = QGridLayout(params_frame)

        params_layout.addWidget(QLabel("Start Year:"), 0, 0)
        self.start_year_spin = QSpinBox(); self.start_year_spin.setRange(2000, datetime.datetime.now().year); self.start_year_spin.setValue(datetime.datetime.now().year - 11)
        params_layout.addWidget(self.start_year_spin, 0, 1)

        params_layout.addWidget(QLabel("End Year:"), 0, 2)
        self.end_year_spin = QSpinBox(); self.end_year_spin.setRange(2000, datetime.datetime.now().year); self.end_year_spin.setValue(datetime.datetime.now().year -1) # Default to last year
        params_layout.addWidget(self.end_year_spin, 0, 3)
        
        params_layout.addWidget(QLabel("Satellite:"), 1, 0)
        self.satellite_combo = QComboBox(); self.satellite_combo.addItems(["Sentinel-2 (10m)", "Landsat 8/9 (30m)"]) # Add more if needed
        params_layout.addWidget(self.satellite_combo, 1, 1)
        
        params_layout.addWidget(QLabel("Composite Method:"), 1, 2)
        self.composite_combo = QComboBox(); self.composite_combo.addItems(["Median", "Mosaic"]) # "Greenest" can be complex
        params_layout.addWidget(self.composite_combo, 1, 3)

        params_layout.addWidget(QLabel("Resolution (m):"), 2,0)
        self.resolution_spin = QSpinBox(); self.resolution_spin.setRange(10,1000); self.resolution_spin.setValue(10); self.resolution_spin.setSingleStep(10)
        params_layout.addWidget(self.resolution_spin, 2,1)

        layout.addWidget(params_frame)

        # --- Output & Progress ---
        output_frame = QGroupBox("4. Build & Download Status")
        output_layout = QVBoxLayout(output_frame)
        self.start_button = QPushButton("Start Building & Downloading Imagery"); self.start_button.clicked.connect(self.start_processing)
        self.stop_button = QPushButton("Stop Processing"); self.stop_button.clicked.connect(self.stop_processing); self.stop_button.setEnabled(False)
        output_layout.addWidget(self.start_button); output_layout.addWidget(self.stop_button)
        self.progress_bar = QProgressBar(); self.progress_bar.setValue(0)
        output_layout.addWidget(self.progress_bar)
        self.status_log = QTextEdit(); self.status_log.setReadOnly(True); self.status_log.setFixedHeight(100)
        output_layout.addWidget(self.status_log)
        layout.addWidget(output_frame)

        # --- Dialog Buttons ---
        self.dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.dialog_buttons.rejected.connect(self.reject_dialog) # Ensure thread stops if dialog closed early
        layout.addWidget(self.dialog_buttons)
        
        # GEE Thread
        self.gee_thread = None

        center_dialog(self, parent)

    def browse_shapefile(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Select Shapefile", "", "Shapefiles (*.shp)")
        if filepath:
            self.shapefile_path = filepath
            self.shp_path_edit.setText(filepath)
            self.load_areas_from_shapefile()

    def load_areas_from_shapefile(self):
        self.area_list_widget.clear()
        if not self.shapefile_path: return
        try:
            self.geodataframe = gpd.read_file(self.shapefile_path)
            # Assuming a column 'name' or 'ID' or similar exists for display
            # Try to find a suitable name column
            name_col_candidates = ['name', 'Name', 'NAME', 'ID', 'Block_Name', 'block_name']
            name_col = None
            for col_cand in name_col_candidates:
                if col_cand in self.geodataframe.columns:
                    name_col = col_cand
                    break
            
            for index, row in self.geodataframe.iterrows():
                display_name = str(row[name_col]) if name_col else f"Area {index + 1}"
                item = QListWidgetItem(display_name)
                item.setData(Qt.ItemDataRole.UserRole, index) # Store GeoDataFrame index
                self.area_list_widget.addItem(item)
            self.log_status(f"Loaded {len(self.geodataframe)} area(s) from {os.path.basename(self.shapefile_path)}.")
        except Exception as e:
            QMessageBox.critical(self, "Shapefile Error", f"Could not read Shapefile: {e}")
            self.log_status(f"Error reading Shapefile: {e}", error=True)
            self.geodataframe = None

    def start_processing(self):
        if not self.geodataframe:
            QMessageBox.warning(self, "Input Error", "Please load a valid Shapefile first.")
            return

        selected_items = self.area_list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Input Error", "Please select at least one area from the list.")
            return

        self.selected_area_geometries = []
        for item in selected_items:
            gdf_idx = item.data(Qt.ItemDataRole.UserRole)
            area_name = item.text()
            try:
                # Ensure geometry is in WGS84 (EPSG:4326) for GEE
                geom_wgs84 = self.geodataframe.iloc[gdf_idx].geometry.to_crs(epsg=4326)
                ee_geom = get_ee_geometry_from_geojson(geom_wgs84.__geo_interface__)
                if ee_geom:
                    self.selected_area_geometries.append({
                        'name': area_name.replace(" ", "_").replace("/", "_"), # Sanitize name for filename
                        'ee_geometry': ee_geom,
                        'shapefile_path': self.shapefile_path # For reference
                    })
                else:
                    self.log_status(f"Could not convert geometry for area '{area_name}' to GEE format. Skipping.", error=True)
            except Exception as e:
                 self.log_status(f"Error processing geometry for area '{area_name}': {e}. Skipping.", error=True)
        
        if not self.selected_area_geometries:
            QMessageBox.warning(self, "Processing Error", "No valid areas selected or geometries could be processed.")
            return

        start_y = self.start_year_spin.value()
        end_y = self.end_year_spin.value()
        if start_y > end_y:
            QMessageBox.warning(self, "Input Error", "Start year cannot be after end year.")
            return
        
        years_to_process = list(range(start_y, end_y + 1))
        satellite = self.satellite_combo.currentText()
        composite_method = self.composite_combo.currentText()
        resolution = self.resolution_spin.value()

        # Define download path (e.g., in AppData or a user-selected folder)
        # For this example, let's use a subfolder of the app's data directory
        base_download_path = os.path.join(os.getenv('APPDATA') or os.path.expanduser("~"), 
                                          "DilasaKMLTool_v4", "local_historical_imagery") # Match main app's constant
        os.makedirs(base_download_path, exist_ok=True)
        
        download_path_template = os.path.join(base_download_path, "{area_name}", "{year}.{format}")


        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_log.clear()
        self.log_status(f"Starting GEE processing for {len(self.selected_area_geometries)} area(s) from {start_y}-{end_y}...")

        self.gee_thread = GEEProcessingThread(
            self.selected_area_geometries, years_to_process, satellite, 
            composite_method, resolution, download_path_template
        )
        self.gee_thread.progress.connect(self.update_overall_progress)
        self.gee_thread.area_progress.connect(self.update_area_progress)
        self.gee_thread.image_download_url.connect(self.handle_image_download)
        self.gee_thread.error.connect(lambda msg: self.log_status(msg, error=True))
        self.gee_thread.finished.connect(self.on_processing_finished)
        self.gee_thread.start()


    def handle_image_download(self, area_name, year, download_url, file_format_str):
        self.log_status(f"Attempting to download: {area_name} - {year} from {download_url[:50]}...")
        try:
            response = requests.get(download_url, stream=True, timeout=300) # 5 min timeout for download
            response.raise_for_status()
            
            area_path = os.path.join(os.getenv('APPDATA') or os.path.expanduser("~"), 
                                     "DilasaKMLTool_v4", "local_historical_imagery", area_name)
            os.makedirs(area_path, exist_ok=True)
            
            filename = f"{year}.{file_format_str.lower()}" # e.g. 2023.png
            filepath = os.path.join(area_path, filename)

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            self.log_status(f"SUCCESS: Downloaded {area_name} - {year} to {filepath}", success=True)
        except requests.exceptions.RequestException as e_req:
            self.log_status(f"Download FAILED for {area_name} - {year}: {e_req}", error=True)
        except Exception as e:
            self.log_status(f"Unexpected error during download for {area_name} - {year}: {e}", error=True)

    def stop_processing(self):
        if self.gee_thread and self.gee_thread.isRunning():
            self.gee_thread.stop()
            self.log_status("Processing stop requested...")
            self.stop_button.setEnabled(False) # Prevent multiple clicks

    def on_processing_finished(self):
        self.log_status("All GEE processing tasks finished or stopped.", success=True)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setValue(100 if not (self.gee_thread and not self.gee_thread._is_running and self.progress_bar.value() < 100) else self.progress_bar.value()) # if stopped early, keep current progress
        QMessageBox.information(self, "Processing Complete", "Historical imagery processing tasks have finished.")
        # Trigger a refresh in the main window if needed so it knows new images are available
        self.parent_main_window.historical_imagery_cache_updated()


    def update_overall_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.log_status(message)

    def update_area_progress(self, area_name, year, percent, message):
        self.log_status(f"{area_name} ({year}) - {percent}%: {message}")

    def log_status(self, message, error=False, success=False):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        if error: self.status_log.append(f"<font color='red'>[{timestamp}] ERROR: {message}</font>")
        elif success: self.status_log.append(f"<font color='green'>[{timestamp}] SUCCESS: {message}</font>")
        else: self.status_log.append(f"[{timestamp}] INFO: {message}")
        self.status_log.ensureCursorVisible()

    def reject_dialog(self): # Handle closing the dialog
        self.stop_processing()
        self.reject()

    def closeEvent(self, event):
        self.stop_processing() # Ensure thread is stopped if dialog is closed
        super().closeEvent(event)
