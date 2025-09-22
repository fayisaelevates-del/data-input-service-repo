"""
Small FastAPI wrapper to trigger solves and download outputs.
Endpoints:
- POST /solve : runs solver using optional uploaded input.json (multipart)
- GET /download/{filename} : download generated files
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
import shutil
import os

app = FastAPI()

@app.post('/solve')
async def solve(input_file: UploadFile = File(None)):
    # save uploaded input.json if provided
    if input_file:
        path = 'input_uploaded.json'
        with open(path, 'wb') as f:
            shutil.copyfileobj(input_file.file, f)
        # move to input.json for the solver
        os.replace(path, 'input.json')
    # run solver
    ret = os.system('.venv\\Scripts\\python.exe vrp_prototype.py')
    if ret != 0:
        raise HTTPException(status_code=500, detail='Solver failed')
    return {'status': 'ok'}

@app.get('/download/{filename}')
def download(filename: str):
    if not os.path.exists(filename):
        raise HTTPException(status_code=404, detail='Not found')
    return FileResponse(filename, media_type='application/octet-stream', filename=filename)
