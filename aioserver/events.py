import io
import logging

from .utils import json_encode


logger = logging.getLogger(__name__)


class BaseEvent:
    """An abstract event source message."""

    encoding = "UTF-8"
    _payload = None

    def encode(self):
        raise NotImplementedError()

    def dump(self, response):
        """Encode the event and write the payload to a file-like object."""
        payload = self._payload
        if payload is None:
            payload = self.encode().encode(self.encoding)
            self._payload = payload
        response.write(payload)


class Event(BaseEvent):
    """A JSON-encoded event source data message."""

    def __init__(self, data, event_id=None, event_type=None):
        self.data = data
        self.event_id = event_id
        self.event_type = event_type

    def encode(self):
        """Return an encoded event source data message."""
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
    """A event source comment."""

    def __init__(self, message=""):
        self.message = message

    def encode(self):
        """Return an encoded event source comment message."""
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
    """An event source retry instruction."""

    _multiplier = 1000  # specify wait in seconds, but send milliseconds

    def __init__(self, wait):
        self.wait = wait

    def encode(self):
        """Return an encoded event source retry message."""
        wait = int(self._multiplier * self.wait)
        return "retry: {}\n\n".format(wait)
