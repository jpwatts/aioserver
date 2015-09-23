#!/usr/bin/env python3.5

import asyncio
import datetime
import json
import logging
import time

import aiohttp

import click

from aioserver.server import generate_random_color, json_encode


STREAM_EVENTS_URL = "http://159.203.72.183:8000/events"
SET_DATA_URL = "http://159.203.72.183:8000/data/{client_id}"

# STREAM_EVENTS_URL = "http://127.0.0.1:8000/events"
# SET_DATA_URL = "http://127.0.0.1:8000/data/{client_id}"


logger = logging.getLogger(__name__)


class ScheduledUpdate:

    def __init__(self, loop=None):
        self._loop = loop
        self.connections = 0

    @property
    def loop(self):
        loop = self._loop
        if loop is None:
            loop = asyncio.get_event_loop()
            self._loop = loop
        return loop

    @asyncio.coroutine
    def schedule(self, interval):
        """Wait for an interval to pass before proceeding.
        This function is a coroutine.
        """
        loop = self.loop
        logger.debug("Waiting %s seconds", interval.total_seconds())
        yield from asyncio.sleep(interval.total_seconds(), loop=loop)

    @asyncio.coroutine
    def update_client(self, http, client_id, interval):
        loop = self.loop
        logger.info("ADDED CLIENT %s", client_id)
        i = 1

        while True:
            yield from self.schedule(interval)
            logger.debug("UPDATING %s", client_id)
            data = dict(text=" Eloy {}".format(self.connections), color=generate_random_color())
            response = yield from http.request("PUT", SET_DATA_URL.format(client_id=client_id), data=json_encode(data))
            response.close()
            logger.info("UPDATED %s", client_id)
            if 200 != response.status:
                break
            i += 1
        logger.info("REMOVED CLIENT %s", client_id)

    @asyncio.coroutine
    def start(self, interval):
        loop = self.loop
        http = aiohttp.ClientSession(loop=loop)
        response = yield from http.request("GET", STREAM_EVENTS_URL)

        client_id = response.headers['id']
        logger.info('MY CONNECTION ID %s', client_id);

        clients = set()

        while True:
            line = yield from response.content.readline()
            line = line.decode('UTF-8').strip()

            if line.startswith('event: created'):
                self.connections += 1
            elif line.startswith('event: deleted'):
                self.connections -= 1

            if client_id in clients:
                continue
            clients.add(client_id)
            asyncio.ensure_future(self.update_client(http, client_id, interval), loop=loop)


@click.command()
@click.option('--logging', '-l', default="INFO", envvar="CLIENT_LOGGING", help="Log level", show_default=True)
@click.option('--interval', '-i', default=1, envvar="CLIENT_INTERVAL", help=u"Scheduled interval in seconds", show_default=True)
def main(**options):
    logging.basicConfig(level=getattr(logging, options['logging'].upper()))
    loop = asyncio.get_event_loop()
    scheduled_update = ScheduledUpdate(loop=loop)

    try:
        loop.run_until_complete(scheduled_update.start(datetime.timedelta(seconds=options['interval'])))
    except KeyboardInterrupt:
        loop.stop()
    finally:
        loop.close()


if __name__ == '__main__':
    main()
