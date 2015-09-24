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
    """A connected client"""

    server_name = os.environ.get('USER', "aioserver")

    def __init__(self, server, request):
        self.server = server
        self.request = request
        self.client_id = str(int(server.loop.time() * 10**6))              # time in microseconds
        self.ip_address = request.transport.get_extra_info('peername')[0]  # remote IP from socket
        self._update({})                                                   # initialize default data
        self.queue = None

    def _update(self, data):
        """Update data, ensuring required attributes aren't changed."""
        client_id = self.client_id
        clean_data = dict(
            id=client_id,
            color=data.get('color') or generate_random_color(),
            ip_address=self.ip_address,
            server=self.server_name,
            text=data.get('text', client_id),
            width=data.get('width')
        )
        self.data = clean_data

    async def update(self, data):
        """Update data and notify connected clients."""
        self._update(data)
        await self.server.add_event(Event(self.data, event_type="updated"))

    async def __aenter__(self):
        """Notify connected clients of a newly opened connection."""
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
        """Notify connected clients of a closed connection."""
        server = self.server
        client_id = self.client_id

        del server.clients[client_id]
        self.queue = None

        await self.server.add_event(Event(dict(id=client_id), event_type="deleted"))
        logger.info("CLOSE %s %s", self.ip_address, client_id)


class Server:
    """An event source server"""

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
        """Add an event to the queue of each connected client."""
        for client in self.clients.values():
            await client.queue.put(event)

    async def stream_events(self, request):
        """Respond to a request to stream events."""
        response = web.StreamResponse()
        response.content_type = "text/event-stream"
        response.headers.update({
            'Access-Control-Allow-Credentials': "true",
            'Access-Control-Allow-Headers': "Content-Type",
            'Access-Control-Allow-Methods': "GET",
            'Access-Control-Allow-Origin': request.headers.get('Origin', "*")
        })

        async with Client(self, request) as client:
            client_id = client.client_id
            queue = client.queue
            timeout = self.timeout

            response.headers['id'] = client_id
            response.start(request)

            CommentEvent("Howdy {}!".format(client_id)).dump(response)
            RetryEvent(10).dump(response)

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

        await response.write_eof()
        return response

    async def get_data(self, request):
        """Respond to a request for a connected client's data."""
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
        """Respond to a request to update a connected client's data."""
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
        """Start the server."""
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
        """Stop the server."""
        server = self._server
        assert server is not None
        server.close()
        await server.wait_closed()
        server = None
        self._server = server
