# Route Manager — local preview + CSV import

This workspace provides a simple manager UI and helper tools to convert pasted coordinate rows (or CSVs) into a previewable route assignment.

## Key files
- `serve_routes.py` — Flask app providing the manager UI and API (/api/drivers, /api/trips, /api/preview, /api/apply_preview, etc.). The UI includes a Preview panel with a Map and a right-hand sidebar. It now supports client-side CSV import.
- `convert_coords_to_trips.py` — utility to convert pasted rows (CSV/TSV/freeform) into `converted_trips.json` containing `drivers` and `trips` arrays.
- `converted_trips.json` — sample output produced by the converter.

## Quick start (Windows PowerShell)

1. Create and activate a virtual environment (recommended):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install flask requests
```

3. Run the Flask app:

```powershell
python .\serve_routes.py
```

4. Open the UI in your browser: http://127.0.0.1:5000/

## Using the CSV import button

- In the Preview panel, under "Quick paste/upload (managers)", there is an "Import CSV file" section.
- Supported formats:
  - CSV/TSV with headers containing `lat`/`lon` or `address`/`label` columns.
  - Freeform lines containing lat/lon pairs — the importer will attempt to extract numeric coordinate pairs.
- How it works: the browser parses the selected file, extracts lat/lon (and label when present), uploads a small drivers payload (first row as depot) and the trips payload to the server via the API. The preview is refreshed after import.

## Using the converter

```powershell
python .\convert_coords_to_trips.py input.tsv --out converted_trips.json
```

- Optionally use `--geocode nominatim` to attempt address geocoding (requires network; rate-limited).

## Notes

- Label cleaning is heuristic; if you need canonical address names, consider using geocoding.
- The development server is not intended for production use. Use a WSGI server for production deployments.

## Want help?

Tell me if you want any of the following added:
- Server-side CSV upload endpoint (so files can be uploaded to the server rather than parsed in-browser).
- Nominatim geocoding integration to canonicalize labels.
- CSV column mapping UI (select which column is lat, lon, label) in the sidebar.

