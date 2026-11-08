import asyncio, time, json
import httpx
async def main():
 async def handle(reader,writer):
  try:
   while await reader.readuntil(b'\r\n\r\n'):
    writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: application/json\r\n\r\n{}');await writer.drain()
  except (asyncio.IncompleteReadError,ConnectionError): pass
  finally: writer.close();await writer.wait_closed()
 server=await asyncio.start_server(handle,'127.0.0.1',0)
 url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/frame'
 results={}
 for mode in ('new-client','new-client-no-env','pooled'):
  started=time.perf_counter()
  async with httpx.AsyncClient(trust_env=False) as pool:
   for _ in range(20):
    for _ in range(5):
     if mode=='pooled': await pool.get(url)
     else:
      async with httpx.AsyncClient(trust_env=mode=='new-client') as client: await client.get(url)
  elapsed=time.perf_counter()-started
  results[mode]={'ms_per_5_calls':round(elapsed/20*1000,2),'frames_per_second':round(20/elapsed,2)}
 server.close();await server.wait_closed();print(json.dumps(results,indent=2))
asyncio.run(main())
