# DilasaKMLTool_v4/core/gee_handler.py
# ----------------------------------------------------------------------
# File: DilasaKMLTool_v4/core/gee_handler.py
# Purpose: Handles all interactions with Google Earth Engine (GEE)
#          for fetching and processing historical satellite imagery.
# ----------------------------------------------------------------------

import ee
import datetime
# import geopandas # Potentially used by the UI layer to read shapefiles
                  # and pass geometry to these functions. This module
                  # might receive GeoJSON or coordinate lists.

# --- GEE Initialization and Authentication Helper ---

def initialize_gee():
    """
    Initializes the Earth Engine API.
    Tries to initialize without explicit authentication first (uses stored credentials).
    If that fails, it attempts authentication (which will open a browser).
    
    Returns:
        bool: True if initialization was successful, False otherwise.
    """
    try:
        ee.Initialize()
        print("GEE Initialized successfully using existing credentials.")
        return True
    except ee.EEException as e:
        print(f"GEE Normal initialization failed: {e}. Attempting authentication...")
        try:
            ee.Authenticate()  # Opens a browser for user to authenticate
            ee.Initialize()    # Initialize again after authentication
            print("GEE Authenticated and Initialized successfully.")
            return True
        except Exception as auth_e:
            print(f"GEE Authentication/Initialization failed: {auth_e}")
            return False
    except Exception as general_e:
        print(f"An unexpected error occurred during GEE initialization: {general_e}")
        return False

# --- Geometry Conversion (Example - UI layer would typically handle Shapefile parsing) ---

def get_ee_geometry_from_geojson(geojson_geometry):
    """
    Converts a GeoJSON geometry dictionary to an ee.Geometry object.
    The UI layer would be responsible for reading a Shapefile (e.g., with geopandas)
    and converting one of its feature's geometry to GeoJSON.

    Args:
        geojson_geometry (dict): A GeoJSON geometry dictionary.
                                 (e.g., from geopandas: gdf.iloc[0].geometry.__geo_interface__)
    
    Returns:
        ee.Geometry: An Earth Engine geometry object, or None if conversion fails.
    """
    if not geojson_geometry or not isinstance(geojson_geometry, dict):
        print("Error: Invalid GeoJSON geometry provided.")
        return None
    try:
        # GEE can directly ingest GeoJSON-like structures for geometries
        if geojson_geometry['type'] == 'Polygon':
            return ee.Geometry.Polygon(geojson_geometry['coordinates'])
        elif geojson_geometry['type'] == 'MultiPolygon':
            return ee.Geometry.MultiPolygon(geojson_geometry['coordinates'])
        # Add other types if needed (Point, LineString, etc.)
        else:
            print(f"Unsupported GeoJSON geometry type: {geojson_geometry['type']}")
            return None
    except Exception as e:
        print(f"Error converting GeoJSON to ee.Geometry: {e}")
        return None

# --- Image Fetching and Processing Core Function ---

def get_yearly_composite_image(area_ee_geometry, year,
                               satellite_collection="COPERNICUS/S2_SR_HARMONIZED", # Sentinel-2 L2A (Surface Reflectance)
                               bands_rgb=['B4', 'B3', 'B2'], # Sentinel-2 RGB bands
                               vis_params={'min': 0.0, 'max': 3000}, # Typical for S2 SR
                               resolution_meters=10,
                               compositing_method='median', # 'median', 'mosaic', 'greenest'
                               cloud_cover_max_percentage=20): # Filter scenes with less than this cloud cover
    """
    Generates a yearly composite satellite image for a given area and year using GEE.

    Args:
        area_ee_geometry (ee.Geometry): The area of interest.
        year (int): The target year.
        satellite_collection (str): GEE ImageCollection ID.
        bands_rgb (list): List of strings for RGB bands.
        vis_params (dict): Visualization parameters (min, max, gamma, etc.).
        resolution_meters (int): Target resolution for processing/export.
        compositing_method (str): 'median', 'mosaic' (simple), or 'greenest' (more complex).
        cloud_cover_max_percentage (int): Maximum cloud cover percentage for input scenes.

    Returns:
        ee.Image: The processed yearly composite ee.Image, or None if an error occurs.
    """
    if not area_ee_geometry:
        print("GEE Error: No area geometry provided.")
        return None

    try:
        start_date = f'{year}-01-01'
        end_date = f'{year}-12-31'

        image_collection = (ee.ImageCollection(satellite_collection)
                            .filterBounds(area_ee_geometry)
                            .filterDate(start_date, end_date)
                            .filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE', cloud_cover_max_percentage))) # Pre-filter by cloud cover

        # Basic cloud masking (example for Sentinel-2 using SCL band if available, or simpler methods)
        # This needs to be adapted based on the chosen satellite_collection
        def mask_s2_clouds(image):
            qa = image.select('QA60') # Sentinel-2 QA60 band for cloud mask
            # Bits 10 and 11 are clouds and cirrus, respectively.
            cloud_bit_mask = 1 << 10
            cirrus_bit_mask = 1 << 11
            # Both flags should be set to zero, indicating clear conditions.
            mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
            # For Sentinel-2 SR HARMONIZED, SCL band is better if available
            scl = image.select('SCL')
            # Values for cloud_medium_probability, cloud_high_probability, cirrus
            cloud_mask = scl.eq(8).Or(scl.eq(9)).Or(scl.eq(10)) 
            return image.updateMask(cloud_mask.Not()).divide(10000).select(bands_rgb) # Divide by 10000 for SR collections

        # Apply cloud masking (this is a placeholder, actual function depends on collection)
        if "S2_SR" in satellite_collection: # Example specific to Sentinel-2 Surface Reflectance
             processed_collection = image_collection.map(mask_s2_clouds)
        else: # General case, might need different/no explicit masking if collection is already cloud-free
             processed_collection = image_collection.select(bands_rgb).map(lambda img: img.divide(10000)) # Example scaling for SR

        if processed_collection.size().getInfo() == 0:
            print(f"Warning: No images found for {year} in {satellite_collection} for the given area and filters.")
            return None

        yearly_composite = None
        if compositing_method == 'median':
            yearly_composite = processed_collection.median()
        elif compositing_method == 'mosaic': # Simple mosaic (takes most recent pixel by default)
            yearly_composite = processed_collection.mosaic()
        # Add 'greenest' or other methods if needed - more complex to define generally
        else:
            print(f"Unsupported compositing method: {compositing_method}. Defaulting to median.")
            yearly_composite = processed_collection.median()
        
        if not yearly_composite.bandNames().containsAll(bands_rgb).getInfo():
            print(f"Error: Composite for {year} does not contain all required bands: {bands_rgb}. Available: {yearly_composite.bandNames().getInfo()}")
            # Attempt to select available bands if some are missing but others are there
            available_bands = yearly_composite.bandNames().filter(ee.Filter.InList('item', bands_rgb))
            if available_bands.size().getInfo() >= 1: # Check if at least one target band is present
                yearly_composite = yearly_composite.select(available_bands)
            else: # If no target bands are present at all
                return None


        # Clip to the exact geometry and apply visualization
        visualized_image = yearly_composite.clip(area_ee_geometry).visualize(**vis_params)
        
        return visualized_image

    except ee.EEException as e:
        print(f"GEE Error processing image for year {year}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error in get_yearly_composite_image for year {year}: {e}")
        return None

# --- Image Export/Download URL ---

def get_image_download_url(ee_image, region_ee_geometry, resolution_meters=10, file_format='GEO_TIFF'):
    """
    Gets a download URL for a given ee.Image.
    For larger images, GEE might require exporting to Google Drive/Cloud Storage first.
    getDownloadURL is suitable for moderately sized images/previews.

    Args:
        ee_image (ee.Image): The image to download.
        region_ee_geometry (ee.Geometry): The geometry defining the region for download.
                                          Use image.geometry() if downloading the full processed image.
        resolution_meters (int): Resolution in meters.
        file_format (str): 'PNG', 'JPEG', 'GEO_TIFF', 'NPY'.

    Returns:
        str: The download URL, or None if an error occurs.
    """
    if not ee_image:
        print("GEE Export Error: No image provided.")
        return None
    try:
        params = {
            'image': ee_image, # Should be the non-visualized image if downloading data
            'region': region_ee_geometry, # Or ee_image.geometry() for the image's footprint
            'scale': resolution_meters,
            'format': file_format,
            # 'crs': 'EPSG:4326' # Or your target CRS
        }
        # If ee_image is already visualized (e.g., an RGB image from .visualize())
        # then the bands are already selected.
        # If it's a multi-band data image, you might need to select bands:
        # params['bands'] = ['B4', 'B3', 'B2'] # Example

        download_url = ee_image.getDownloadURL(params)
        return download_url
    except ee.EEException as e:
        print(f"GEE Error getting download URL: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error in get_image_download_url: {e}")
        return None

def get_image_tile_url(ee_image_visualized):
    """
    Gets an XYZ tile URL template for a visualized ee.Image.
    Use with Folium/Leaflet. Remember MapId and token are temporary.

    Args:
        ee_image_visualized (ee.Image): A visualized ee.Image (e.g., result of .visualize()).

    Returns:
        str: The XYZ tile URL template, or None if an error occurs.
             Or a dict containing mapid, token, tileurl if getMapId() is used.
    """
    if not ee_image_visualized:
        print("GEE Tile URL Error: No visualized image provided.")
        return None
    try:
        map_id_dict = ee_image_visualized.getMapId()
        # Example: map_id_dict = {'mapid': '...', 'token': '...', 'tile_fetcher.url_format': '...' }
        # The tile_fetcher.url_format is the template for XYZ tiles.
        # It will look like: https://earthengine.googleapis.com/v1alpha/projects/earthengine-public/maps/{mapid}/tiles/{z}/{x}/{y}?token={token}
        
        # Some GEE versions might return tile_fetcher.url_format, others just mapid and token
        # and you construct the URL template.
        # The folium library can often take mapid directly if using GEE plugin,
        # or you construct the URL.
        
        # For direct use with folium.TileLayer:
        tile_url_template = map_id_dict['tile_fetcher.url_format']
        # Or, if it's the newer format (check GEE documentation for getMapId response)
        # tile_url_template = f"https://earthengine.googleapis.com/v1alpha/{map_id_dict['mapid']}/tiles/{{z}}/{{x}}/{{y}}?token={map_id_dict['token']}"

        return tile_url_template # Or return map_id_dict for more flexibility
    except ee.EEException as e:
        print(f"GEE Error getting tile URL (getMapId): {e}")
        return None
    except Exception as e:
        print(f"Unexpected error in get_image_tile_url: {e}")
        return None


# --- Example Usage (for testing this module directly) ---
if __name__ == '__main__':
    if initialize_gee():
        print("\n--- Testing GEE Handler ---")
        
        # Example: A small polygon in Maharashtra (replace with actual GeoJSON from Shapefile)
        sample_geojson_polygon = {
            "type": "Polygon",
            "coordinates": [[
                [73.80, 18.55], [73.90, 18.55],
                [73.90, 18.45], [73.80, 18.45],
                [73.80, 18.55]
            ]]
        }
        
        area_geom = get_ee_geometry_from_geojson(sample_geojson_polygon)
        
        if area_geom:
            test_year = 2023
            print(f"\nFetching yearly composite for {test_year}...")
            # Using Sentinel-2 by default
            yearly_rgb_image = get_yearly_composite_image(area_geom, test_year) 
            
            if yearly_rgb_image:
                print(f"Successfully processed image for {test_year}.")
                
                # Test getting tile URL for Folium
                tile_info = get_image_tile_url(yearly_rgb_image) # Pass the visualized image
                if tile_info:
                    print(f"Tile URL template (or MapID dict): {tile_info}")

                # Test getting download URL (for the visualized RGB image)
                # For actual data download, you might pass a non-visualized, multi-band image.
                # The region for getDownloadURL should ideally be tight to the image content.
                # Using area_geom here.
                download_url = get_image_download_url(yearly_rgb_image, area_geom, resolution_meters=10, file_format='PNG')
                if download_url:
                    print(f"Download URL (PNG preview): {download_url}")
                else:
                    print("Failed to get download URL.")
            else:
                print(f"Failed to process image for {test_year}.")
        else:
            print("Failed to create GEE geometry from sample GeoJSON.")
    else:
        print("GEE could not be initialized. Please check authentication and configuration.")

