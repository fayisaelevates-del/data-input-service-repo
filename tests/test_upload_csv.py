import os
import requests

URL = 'http://127.0.0.1:5000/api/upload_csv'
TOKEN = os.environ.get('SUGGEST_API_TOKEN', '')

def run_upload_test(csv_path='test_upload.csv'):
    if not os.path.exists(csv_path):
        raise SystemExit('csv not found: ' + csv_path)
    with open(csv_path, 'rb') as fh:
        files = {'file': ('test_upload.csv', fh, 'text/csv')}
        headers = {'X-API-Token': TOKEN}
        r = requests.post(URL, headers=headers, files=files, timeout=10)
        print('status:', r.status_code)
        try:
            print('json:', r.json())
        except Exception:
            print('text:', r.text[:1000])

if __name__ == '__main__':
    run_upload_test()