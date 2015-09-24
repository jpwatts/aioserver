import json
import logging
import random


logger = logging.getLogger(__name__)


def generate_random_color(range_min=0, range_max=255, alpha=0.5):
    """Return a random RGBA color."""
    return "rgba({}, {}, {}, {})".format(
        random.randint(range_min, range_max),  # red
        random.randint(range_min, range_max),  # yellow
        random.randint(range_min, range_max),  # blue
        alpha
    )


def json_encode(data):
    """Return the JSON-encoded text representation of a data object."""
    return json.dumps(data, separators=(',', ':'), sort_keys=True)
