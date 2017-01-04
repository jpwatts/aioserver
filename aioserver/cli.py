import asyncio
import logging

import click

from .server import Server


@click.command()
@click.option('--logging', '-l', default="INFO", envvar="SERVER_LOGGING", help="Log level", show_default=True)
@click.option('--debug', '-d', envvar="SERVER_DEBUG", is_flag=True, help="Enable debugging", show_default=True)
@click.option('--address', '-a', default="127.0.0.1", envvar="SERVER_ADDRESS", help="Server address", show_default=True)
@click.option('--port', '-p', default=8000, envvar="SERVER_PORT", help="Server port", show_default=True)
def main(**options):
    """Run an event source server."""
    logging.basicConfig(level=getattr(logging, options['logging'].upper()))
    loop = asyncio.get_event_loop()
    loop.set_debug(options['debug'])
    server = Server(options['address'], options['port'], loop=loop)
    loop.run_until_complete(server.start())
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.stop()
    finally:
        loop.close()
