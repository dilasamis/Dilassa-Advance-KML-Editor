# Dilasa Advance KML Tool v4 (Beta)

## Description
Application for processing geographic data from mWater/CSVs, managing polygon records, generating KML files, visualizing selected polygons, and building a local cache of historical satellite imagery for defined areas. Built with Python and Qt (PySide6).

## Project Structure
- main_app.py: Main application entry point.
- ui/: Contains all Qt-based UI components (main window, dialogs, custom widgets).
- core/: Core application logic (data processing, KML generation, API handlers, GEE interactions).
- database/: SQLite database management.
- ssets/: Static files like logos and icons.
- local_historical_imagery/: Stores downloaded yearly composite images.

## Setup Instructions
1.  Ensure Python 3.8+ is installed.
2.  Clone this repository (if applicable) or extract the project files.
3.  Navigate to the project root directory (DilasaKMLTool_v4).
4.  **Create and activate a Python virtual environment (recommended):**
    `ash
    python -m venv venv
    # On Windows:
    .\venv\Scripts\activate
    # On macOS/Linux:
    # source venv/bin/activate
    `
5.  **Install dependencies:**
    `ash
    pip install -r requirements.txt
    `
6.  Place dilasa_logo.jpg and pp_icon.ico into the ssets/ directory.
7.  If using Google Earth Engine features, ensure you have authenticated: earthengine authenticate (run this once in your environment).
8.  **Run the application:**
    ##`ash
    python main_app.py
    `

## Building Executable (using PyInstaller)
(Detailed PyInstaller command to be finalized after development, will include data files from ssets/ and potentially GEE client secrets if needed for some auth flows).
Example:
pyinstaller --noconfirm --onefile --windowed --icon=assets/app_icon.ico --name "DilasaKMLTool" --add-data "assets:assets" main_app.py

