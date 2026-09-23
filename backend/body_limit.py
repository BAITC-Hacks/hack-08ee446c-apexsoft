"""Bound bytes received before FastAPI parses JSON/multipart, even without Content-Length."""
from starlette.responses import JSONResponse
from .attachments import MAX_BYTES

class BodyLimit:
    def __init__(self,app): self.app=app

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('method')!='POST':
            return await self.app(scope,receive,send)
        limit=MAX_BYTES+65536 if scope.get('path')=='/api/attachments' else 50000
        chunks=[]; size=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect': return
            chunk=message.get('body',b''); size+=len(chunk)
            if size>limit:
                response=JSONResponse({'error':{'code':'attachment_too_large','message':'Запрос слишком большой.'}},status_code=413)
                return await response(scope,receive,send)
            chunks.append(chunk)
            if not message.get('more_body',False): break
        body=b''.join(chunks); delivered=False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered=True
                return {'type':'http.request','body':body,'more_body':False}
            return await receive()
        await self.app(scope,bounded_receive,send)
