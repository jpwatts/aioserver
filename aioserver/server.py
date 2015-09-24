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
    server_name = os.environ.get('USER', "aioserver")

    def __init__(self, server, ip_address, client_id):
        self.server = server
        self.ip_address = ip_address
        self.client_id = client_id
        self._update({})
        self.queue = None

    def _update(self, data):
        client_id = self.client_id
        cleaned_data = dict(
            id=client_id,
            color=data.get('color') or generate_random_color(),
            server=self.server_name,
            text=data.get('text', client_id)
        )
        self.data = cleaned_data

    async def update(self, data):
        self._update(data)
        await self.server.add_event(Event(self.data, event_type="updated"))

    async def __aenter__(self):
        client_id = self.client_id
        logger.info("OPEN %s %s", self.ip_address, client_id)

        server = self.server
        queue = asyncio.Queue(loop=server.loop)

        for client in server.clients.values():
            await queue.put(Event(client.data, event_type="created"))

        self.queue = queue
        server.clients[client_id] = self
        await server.add_event(Event(self.data, event_type="created"))

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        server = self.server
        client_id = self.client_id

        del server.clients[client_id]
        self.queue = None

        await self.server.add_event(Event(dict(id=client_id), event_type="deleted"))
        logger.info("CLOSE %s %s", self.ip_address, client_id)


class Server:
    timeout = 30

    def __init__(self, address, port, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()
        self.address = address
        self.port = port
        self.loop = loop
        self.clients = collections.OrderedDict()
        self._server = None

    async def add_event(self, event):
        for client in self.clients.values():
            await client.queue.put(event)

    async def stream_events(self, request):
        loop = self.loop
        timeout = self.timeout

        ip_address = request.transport.get_extra_info('peername')[0]

        # time in microseconds
        client_id = str(int(loop.time() * 10**6))

        response = web.StreamResponse()
        response.content_type = "text/event-stream"
        response.headers.update({
            'Access-Control-Allow-Credentials': "true",
            'Access-Control-Allow-Headers': "Content-Type",
            'Access-Control-Allow-Methods': "GET",
            'Access-Control-Allow-Origin': request.headers.get('Origin', "*"),
            'Client-ID': client_id
        })
        response.start(request)

        CommentEvent("Howdy {}!".format(client_id)).dump(response)
        RetryEvent(10).dump(response)

        async with Client(self, ip_address, client_id) as client:
            await response.drain()
            queue = client.queue
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

        await response.write_eof()
        return response

    async def get_data(self, request):
        client_id = request.match_info['client_id']
        try:
            client = self.clients[client_id]
        except KeyError:
            raise web.HTTPNotFound()
        return web.Response(
            content_type="application/json",
            text="{}\n".format(json_encode(client.data))
        )

    async def set_data(self, request):
        client_id = request.match_info['client_id']
        try:
            client = self.clients[client_id]
        except KeyError:
            raise web.HTTPNotFound()

        try:
            data = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest()

        if not isinstance(data, dict):
            raise web.HTTPBadRequest()

        await client.update(data)
        return web.Response(
            content_type="application/json",
            text="{}\n".format(json_encode(client.data))
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
