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


logger = logging.getLogger(__name__)


@asyncio.coroutine
def schedule(interval, loop=None):
    """Wait for an interval to pass before proceeding.
    This function is a coroutine.
    """
    logger.debug("Waiting %s seconds", interval.total_seconds())
    yield from asyncio.sleep(interval.total_seconds(), loop=loop)

@asyncio.coroutine
def update_client(http, client_id, interval, loop=None):
    logger.info("ADDED CLIENT %s", client_id)
    i = 1
    while True:
        yield from schedule(interval, loop=loop)
        logger.debug("UPDATING %s", client_id)
        data = dict(text="{}.{}".format(client_id, i), color=generate_random_color())
        response = yield from http.request("PUT", SET_DATA_URL.format(client_id=client_id), data=json_encode(data))
        response.close()
        logger.info("UPDATED %s", client_id)
        if 200 != response.status:
            break
        i += 1
    logger.info("REMOVED CLIENT %s", client_id)


@asyncio.coroutine
def start(interval, loop=None):
    http = aiohttp.ClientSession(loop=loop)
    response = yield from http.request("GET", STREAM_EVENTS_URL)

    client_id = response.headers['id']
    logger.info('client_id %s', client_id);

    clients = set()

    while True:
        line = yield from response.content.readline()
        if client_id in clients:
            continue
        clients.add(client_id)
        asyncio.ensure_future(update_client(http, client_id, interval, loop=loop), loop=loop)


@click.command()
@click.option('--logging', '-l', default="INFO", envvar="CLIENT_LOGGING", help="Log level", show_default=True)
@click.option('--interval', '-i', default=0, envvar="CLIENT_INTERVAL", help=u"Scheduled interval in seconds", show_default=True)
def main(**options):
    logging.basicConfig(level=getattr(logging, options['logging'].upper()))
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start(datetime.timedelta(seconds=options['interval']), loop=loop))
    except KeyboardInterrupt:
        loop.stop()
    finally:
        loop.close()


if __name__ == '__main__':
    main()
