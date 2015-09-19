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
def schedule(interval, previous_deadline=None, loop=None):
    """Wait for an interval to pass before proceeding.
    There are two special cases where we don't wait:
      1. If there's no previous deadline (the first time we're called)
      2. If we're backed up (duration exceeds interval)
    This function is a coroutine.
    """
    now = datetime.datetime.now().replace(microsecond=0)

    # This is the first time we've been called.
    if previous_deadline is None:
        return now

    if interval is None:
        return

    duration = now - previous_deadline

    # Check if we're backed up.
    if duration > interval:
        logger.warning("DURATION %s EXCEEDED INTERVAL %s", duration, interval)
        return now

    # Compute the required delay.
    interval_seconds = int(interval.total_seconds())
    next_deadline = datetime.datetime.fromtimestamp(
        int(time.mktime(now.timetuple()))
        // interval_seconds
        * interval_seconds
        + interval_seconds
    )
    delay = next_deadline - now

    if not delay:
        return now

    logger.info("WAITING %s UNTIL %s", delay, next_deadline)
    yield from asyncio.sleep(delay.total_seconds(), loop=loop)
    logger.debug("WAITED %s UNTIL %s", delay, next_deadline)

    return next_deadline


@asyncio.coroutine
def update_client(http, client_id, interval, loop=None):
    logger.info("ADDED CLIENT %s", client_id)
    deadline = None
    i = 1
    while True:
        deadline = yield from schedule(interval, deadline, loop=loop)
        logger.debug("UPDATING %s @ %s", client_id, deadline)
        data = dict(text="{}.{}".format(client_id, i), color=generate_random_color())
        response = yield from http.request("PUT", SET_DATA_URL.format(client_id=client_id), data=json_encode(data))
        response.close()
        logger.info("UPDATED %s @ %s", client_id, deadline)
        if 200 != response.status:
            break
        i += 1
    logger.info("REMOVED CLIENT %s", client_id)


@asyncio.coroutine
def start(interval, loop=None):
    http = aiohttp.ClientSession(loop=loop)
    response = yield from http.request("GET", STREAM_EVENTS_URL)

    clients = set()

    while True:
        line = yield from response.content.readline()
        line = line.decode('UTF-8').strip()
        if not line.startswith('data: '):
            continue
        data = json.loads(line[6:])
        client_id = data['id']
        if client_id in clients:
            continue
        clients.add(client_id)
        asyncio.ensure_future(update_client(http, data['id'], interval, loop=loop), loop=loop)


@click.command()
@click.option('--logging', '-l', default="INFO", envvar="CLIENT_LOGGING", help="Log level", show_default=True)
@click.option('--interval', '-i', default=0, envvar="CLIENT_INTERVAL", help=u"Scheduled interval", show_default=True)
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
