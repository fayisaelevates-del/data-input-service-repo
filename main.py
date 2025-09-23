import os
import json
import logging
import pandas as pd
import googlemaps
from google.cloud import storage
import psycopg2
import base64

#configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Environment Variables (set in Cloud Run) ---
PUBSUB_TOPIC = os.environ.get("projects/saferidestar-trip-management/topics/transport-app-csv-upload-topic") # The Pub/Sub topic to subscribe to
DATABASE_URL = os.environ.get("postgresql://postgres:*ez:\\T)yY=j-6L%E@10.118.192.2:5432/postgres") # Connection string for Cloud SQL
GOOGLE_MAPS_API_KEY = os.environ.get("AIzaSyAnAnjQtJ96KRWHDSkfyKHsRQaYatUM1Bc") # API key for Google Maps
STORAGE_BUCKET = os.environ.get("transport-app-raw-data") # Cloud Storage bucket name
# --- Helper Functions ---

def download_csv_from_gcs(bucket_name, blob_name, destination_file_name):
    """Downloads a CSV file from Google Cloud Storage."""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.download_to_filename(destination_file_name)
        logging.info(f"Downloaded {blob_name} from gs://{bucket_name} to {destination_file_name}")
        return True
    except Exception as e:
        logging.error(f"Error downloading {blob_name} from gs://{bucket_name}: {e}")
        return False

def geocode_address(address, api_key):
    """Geocodes an address using the Google Maps Geocoding API."""
    try:
        gmaps = googlemaps.Client(key=api_key)
        geocode_result = gmaps.geocode(address)
        if geocode_result:
            latitude = geocode_result[0]['geometry']['location']['lat']
            longitude = geocode_result[0]['geometry']['location']['lng']
            return latitude, longitude
        else:
            logging.warning(f"Geocoding failed for address: {address}")
            return None, None
    except Exception as e:
        logging.error(f"Error geocoding address {address}: {e}")
        return None, None

import logging
import psycopg2
from psycopg2 import Error

def store_trip_data_in_db(db_url, trip_data):
    """
    Stores trip data in the PostgreSQL database.

    Args:
        db_url (str): The database connection URL.
        trip_data (tuple): A tuple containing all trip details in the following order:
                           (trip_id, origin_address, destination_address,
                            origin_latitude, origin_longitude,
                            destination_latitude, destination_longitude,
                            pickup_time, dropoff_time,
                            passenger_count, special_requirements)
    Returns:
        bool: True if data was stored successfully, False otherwise.
    """
    conn = None
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        # Unpack the trip_data tuple - make sure the order matches the tuple created in main()
        # from the CSV data.
        (trip_id, origin_address, destination_address,
         origin_latitude, origin_longitude,
         destination_latitude, destination_longitude,
         pickup_time, dropoff_time,
         passenger_count, special_requirements) = trip_data

        insert_query = """
        INSERT INTO trips (
            trip_id, origin_address, destination_address,
            origin_latitude, origin_longitude,
            destination_latitude, destination_longitude,
            pickup_time, dropoff_time,
            passenger_count, special_requirements
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (trip_id) DO UPDATE SET
            origin_address = EXCLUDED.origin_address,
            destination_address = EXCLUDED.destination_address,
            origin_latitude = EXCLUDED.origin_latitude,
            origin_longitude = EXCLUDED.origin_longitude,
            destination_latitude = EXCLUDED.destination_latitude,
            destination_longitude = EXCLUDED.destination_longitude,
            pickup_time = EXCLUDED.pickup_time,
            dropoff_time = EXCLUDED.dropoff_time,
            passenger_count = EXCLUDED.passenger_count,
            special_requirements = EXCLUDED.special_requirements,
            created_at = CURRENT_TIMESTAMP;
        """
        cur.execute(insert_query, trip_data) # trip_data is passed directly here
        conn.commit()
        logging.info(f"Successfully stored/updated trip_id: {trip_id}")
        return True

    except (Exception, Error) as error:
        logging.error(f"Error while connecting to PostgreSQL or inserting data: {error}")
        if conn:
            conn.rollback() # Rollback in case of error
        return False
    finally:
        if conn:
            cur.close()
            conn.close()
            logging.debug("PostgreSQL connection closed.")


# --- Main Function ---

 
