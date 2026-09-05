# -*- coding: utf-8 -*-
import sys
from urllib.parse import parse_qsl

from resources.lib import navigation


def run():
    base_url = sys.argv[0]
    handle = int(sys.argv[1])
    params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
    navigation.route(base_url, handle, params)


if __name__ == '__main__':
    run()
