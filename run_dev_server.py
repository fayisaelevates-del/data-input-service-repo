import os
from serve_routes import app

if __name__ == '__main__':
    port = int(os.environ.get('DEV_PORT', '5500'))
    # bind to localhost only for safety in this environment
    app.run(host='127.0.0.1', port=port, debug=False)
