"""Bounded private intake uploads, shared by portal and receiver."""
import hashlib
import re
from pathlib import PurePosixPath
from starlette.requests import Request
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

MAX_FILE = 10 * 1024 * 1024
MAX_BODY = 5 * MAX_FILE + 128 * 1024
TYPES = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg',
    '.pdf':'application/pdf', '.doc':'application/msword',
    '.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls':'application/vnd.ms-excel', '.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.txt':'text/plain'}

async def read_submission(request):
    multipart = request.headers.get('content-type','').lower().startswith('multipart/form-data')
    limit = MAX_BODY if multipart else 40000
    size = 0
    async def receive():
        nonlocal size
        message = await request.receive()
        size += len(message.get('body', b''))
        if size > limit:
            raise HTTPException(413, 'Submission is too large.')
        return message
    bounded = Request(request.scope, receive)
    if not multipart:
        return await bounded.body(), []
    async with bounded.form(max_files=5, max_fields=1) as form:
        parts = form.multi_items()
        payloads = [v for k,v in parts if k == 'payload' and isinstance(v,str)]
        if len(payloads)!=1 or any(k not in ('payload','files') or (k=='files' and not isinstance(v,UploadFile)) or (k=='payload' and not isinstance(v,str)) for k,v in parts):
            raise HTTPException(422, 'Invalid upload fields.')
        raw = payloads[0].encode()
        if len(raw)>40000:
            raise HTTPException(413, 'Submission details are too large.')
        uploads=[]
        for key, upload in parts:
            if key!='files': continue
            filename = PurePosixPath((upload.filename or '').replace('\\','/')).name
            filename = re.sub(r'[\x00-\x1f\x7f]', '', filename)
            suffix = PurePosixPath(filename).suffix.lower()
            if suffix not in TYPES:
                raise HTTPException(415, 'Unsupported attachment type.')
            filename = filename[:200-len(suffix)] + suffix if len(filename)>200 else filename
            data = await upload.read(MAX_FILE+1)
            if len(data)>MAX_FILE:
                raise HTTPException(413, 'Each file must be 10 MB or smaller.')
            if not data:
                raise HTTPException(422, 'Empty attachments are not supported.')
            uploads.append(dict(filename=filename,content_type=TYPES[suffix],size_bytes=len(data),data=data))
        return raw, uploads


def manifest(uploads):
    return [{k:v for k,v in f.items() if k!='data'} | {'sha256':hashlib.sha256(f['data']).hexdigest()} for f in uploads]
