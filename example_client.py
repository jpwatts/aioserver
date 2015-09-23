import asyncio
import contextlib
import json
import logging
import random
import urllib.parse

import aiohttp

import click

from aioserver.server import generate_random_color, json_encode


logger = logging.getLogger(__name__)


class ColorUpdater:
    encoding = "UTF-8"

    client_path_template = "/data/{client_id}"
    events_path = "/events"

    def __init__(self, base_url, interval, loop=None):
        self.base_url = base_url
        self.http = None
        self.interval = interval
        self.loop = loop

    def __enter__(self):
        self.http = aiohttp.ClientSession(loop=self.loop)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.http.close()
        self.http = None

    @asyncio.coroutine
    def update_client(self, client_url, data):
        http = self.http
        interval = self.interval
        loop = self.loop
        while True:
            data['color'] = generate_random_color(alpha=0.5)
            logger.debug("UPDATING %s TO %s", client_url, data)
            response = yield from http.request("PUT", client_url, data=json_encode(data))
            response.close()
            logger.info("UPDATED %s TO %s", client_url, data)
            if not interval:
                break
            logger.info("SLEEPING %s FOR %s SECONDS", client_url, interval)
            yield from asyncio.sleep(interval, loop=loop)
            logger.debug("SLEPT %s FOR %s SECONDS", client_url, interval)

    @asyncio.coroutine
    def next_event(self, response):
        encoding = self.encoding
        event_type = None
        data_text = ""
        while True:
            line = yield from response.content.readline()
            logger.debug("LINE %r", line)
            line = line.decode(encoding).strip()

            if line:
                key, value = line.split(None, 1)
                key = key.rstrip(":")

                if key not in ('data', 'event'):
                    continue

                if "event" == key:
                    event_type = value
                    continue

                if "data" == key:
                    data_text += value
                    continue

            if not data_text:
                event_type = None
                continue
            return event_type, json.loads(data_text)

    @asyncio.coroutine
    def start(self):
        client_path_template = self.client_path_template
        clients = {}
        events_url = urllib.parse.urljoin(self.base_url, self.events_path)
        logger.info("GETTING EVENTS %s", events_url)
        response = yield from self.http.request("GET", events_url)
        with contextlib.closing(response):
            while True:
                event_type, data = yield from self.next_event(response)
                client_url = urllib.parse.urljoin(self.base_url, client_path_template.format(client_id=data['id']))
                if "created" == event_type:
                    clients[client_url] = asyncio.ensure_future(self.update_client(client_url, data))
                    logger.info("CREATED TASK %s", client_url)
                    continue
                if "deleted" == event_type:
                    clients[client_url].cancel()
                    del clients[client_url]
                    logger.info("DELETED TASK %s", client_url)
                    continue


@click.command()
@click.argument('base_url', envvar="CLIENT_BASE_URL")
@click.option('--logging', '-l', default="INFO", envvar="CLIENT_LOGGING", help="Log level", show_default=True)
@click.option('--interval', '-i', default=0, type=float, envvar="CLIENT_INTERVAL", help=u"Scheduled interval", show_default=True)
def main(**options):
    logging.basicConfig(level=getattr(logging, options['logging'].upper()))
    loop = asyncio.get_event_loop()
    color_updater = ColorUpdater(options['base_url'], options['interval'], loop=loop)
    with color_updater:
        try:
            loop.run_until_complete(color_updater.start())
        except KeyboardInterrupt:
            loop.stop()
        finally:
            loop.close()


if __name__ == '__main__':
    main()
