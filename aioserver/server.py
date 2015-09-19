import asyncio
import collections
import io
import json
import logging

from aiohttp import web
from aiohttp.log import access_logger


logger = logging.getLogger(__name__)


def json_encode(data):
    return json.dumps(data, separators=(',', ':'), sort_keys=True)


class BaseEvent:
    encoding = "UTF-8"
    _payload = None

    def encode(self):
        raise NotImplementedError()

    def dump(self, response):
        payload = self._payload
        if payload is None:
            payload = self.encode().encode(self.encoding)
            self._payload = payload
        response.write(payload)


class Event(BaseEvent):
    def __init__(self, data, event_id=None, event_type=None):
        self.data = data
        self.event_id = event_id
        self.event_type = event_type

    def encode(self):
        text_buffer = io.StringIO()

        event_id = self.event_id
        if event_id is not None:
            text_buffer.write("id: {}\n".format(event_id))

        event_type = self.event_type
        if event_type is not None:
            text_buffer.write("event: {}\n".format(event_type))

        event_text = json_encode(self.data)
        for line in event_text.splitlines():
            text_buffer.write("data: {}\n".format(line))

        text_buffer.write("\n")
        return text_buffer.getvalue()


class CommentEvent(BaseEvent):
    def __init__(self, message=""):
        self.message = message

    def encode(self):
        text_buffer = io.StringIO()

        message = self.message
        if message:
            for line in message.splitlines():
                text_buffer.write(": {}\n".format(line))
        else:
            text_buffer.write(":\n")

        text_buffer.write("\n")
        return text_buffer.getvalue()


class RetryEvent(BaseEvent):
    _multiplier = 1000  # specify wait in seconds, but send milliseconds

    def __init__(self, wait):
        self.wait = wait

    def encode(self):
        wait = int(self._multiplier * self.wait)
        return "retry: {}\n\n".format(wait)


class Client:
    def __init__(self, client_id, queue):
        self.client_id = client_id
        self.queue = queue
        self.data = dict(id=client_id)


class Server:
    timeout = 30

    def __init__(self, address, port, loop=None):
        self.address = address
        self.port = port
        self._loop = loop
        self._clients = collections.OrderedDict()
        self._server = None

    @property
    def loop(self):
        loop = self._loop
        if loop is None:
            loop = asyncio.get_event_loop()
            self._loop = loop
        return loop

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

        # time in microseconds
        client_id = str(int(loop.time() * 10**6))
        queue = asyncio.Queue(loop=loop)
        client = Client(client_id, queue)
        self._clients[client_id] = client

        response = web.StreamResponse()
        response.content_type = "text/event-stream"
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
