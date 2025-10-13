from serve_routes import app

# Gunicorn entrypoint expects a module-level variable named `application` or `app`.
application = app

if __name__ == "__main__":
    # For local debug only
    app.run(host="0.0.0.0", port=8080)
