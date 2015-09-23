import asyncio
import collections
import json
import logging
import os

from aiohttp import web
from aiohttp.log import access_logger

from .events import CommentEvent, Event, RetryEvent
from .utils import generate_random_color, json_encode


logger = logging.getLogger(__name__)


class Client:
    def __init__(self, client_id, queue):
        self.client_id = client_id
        self.queue = queue
        server_name = os.environ.get('USER', "aioserver")
        self.data = dict(
            id=client_id,
            color=generate_random_color(),
            server=server_name,
            text="{}/{}".format(server_name, client_id),
        )


class Server:
    timeout = 30

    def __init__(self, address, port, loop=None):
        self.address = address
        self.port = port
        self.loop = loop or asyncio.get_event_loop()
        self._clients = collections.OrderedDict()
        self._server = None

    def add_default_headers(self, request, response):
        headers = response.headers
        headers['Access-Control-Allow-Credentials'] = 'true'
        headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', "*")
        headers['Access-Control-Allow-Headers'] = "Content-Type"
        headers['Access-Control-Allow-Methods'] = request.method

    async def add_event(self, event):
        for client in self._clients.values():
            await client.queue.put(event)

    async def replay_events(self, client):
        queue = client.queue
        for connected_client in self._clients.values():
            if connected_client is client:
                continue
            await queue.put(Event(connected_client.data, event_type="created"))

    async def stream_events(self, request):
        loop = self.loop
        timeout = self.timeout

        ip_address = request.transport.get_extra_info('peername')[0]

        # time in microseconds
        client_id = str(int(loop.time() * 10**6))

        logger.info("OPEN %s %s", ip_address, client_id)

        queue = asyncio.Queue(loop=loop)
        client = Client(client_id, queue)
        self._clients[client_id] = client

        response = web.StreamResponse()
        response.content_type = "text/event-stream"
        self.add_default_headers(request, response)
        response.headers['id'] = client_id
        response.start(request)

        CommentEvent("Howdy {}!".format(client_id)).dump(response)
        RetryEvent(10).dump(response)

        try:
            await self.replay_events(client)
            await self.add_event(Event(client.data, event_type="created"))
            await response.drain()
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout
                    )
                except asyncio.TimeoutError:
                    # Send something so the connection doesn't time out.
                    event = CommentEvent()
                event.dump(response)
                await response.drain()
        finally:
            del self._clients[client_id]
            await self.add_event(Event(dict(id=client_id), event_type="deleted"))
        await response.write_eof()
        logger.info("CLOSE %s %s", ip_address, client_id)
        return response

    async def get_data(self, request):
        client_id = request.match_info['client_id']
        try:
            client = self._clients[client_id]
        except KeyError:
            raise web.HTTPNotFound()
        return web.Response(
            content_type="application/json",
            text="{}\n".format(json_encode(client.data))
        )

    async def set_data(self, request):
        client_id = request.match_info['client_id']
        try:
            client = self._clients[client_id]
        except KeyError:
            raise web.HTTPNotFound()

        try:
            data = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest()

        if not isinstance(data, dict):
            raise web.HTTPBadRequest()

        data['id'] = client_id
        client.data = data
        await self.add_event(Event(data, event_type="updated"))
        return web.Response(
            content_type="application/json",
            text="{}\n".format(json_encode(data))
        )

    async def start(self):
        assert self._server is None
        loop = self.loop
        app = web.Application(loop=loop)

        app.router.add_route("GET", '/events', self.stream_events)
        app.router.add_route("GET", '/data/{client_id:\d+}', self.get_data)
        app.router.add_route("PUT", '/data/{client_id:\d+}', self.set_data)

        self._server = await loop.create_server(
            app.make_handler(access_log=access_logger),
            self.address,
            self.port
        )

    async def stop(self):
        server = self._server
        assert server is not None
        server.close()
        await server.wait_closed()
        server = None
        self._server = server
