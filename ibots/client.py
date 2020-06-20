import json
import requests
import argparse


def call(server, port, command, kwargs):
    response = requests.post(
        '{}:{}/{}'.format(server, port, command),
        data=kwargs,
    )
    print(json.dumps(response.json(), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-s',
        '--server',
        help='Server',
        default='http://localhost',
    )
    parser.add_argument(
        '-p',
        '--port',
        help='Port number',
        type=int,
        default=8000,
    )
    subparsers = parser.add_subparsers(dest='command')

    parser_status = subparsers.add_parser('status')
    parser_status.add_argument(
        '-b',
        '--bots',
        nargs='+',
        default=[],
        help='List of bots',
    )

    parser_start = subparsers.add_parser('start')
    parser_start.add_argument(
        '-b',
        '--bots',
        nargs='+',
        default=[],
        help='List of bots',
    )

    parser_stop = subparsers.add_parser('stop')
    parser_stop.add_argument(
        '-b',
        '--bots',
        nargs='+',
        default=[],
        help='List of bots',
    )

    parser_resource = subparsers.add_parser('resource')
    parser_resource.add_argument(
        'targets',
        nargs='+',
        help='List of resources',
    )
    parser_resource.add_argument(
        'instruction',
        help='Instructions for execution',
    )

    parser_bot = subparsers.add_parser('bot')
    parser_bot.add_argument(
        'targets',
        nargs='+',
        help='List of bots',
    )
    parser_resource.add_argument(
        'instruction',
        help='Instructions for execution',
    )

    parser_bot = subparsers.add_parser('interact')
    parser_bot.add_argument(
        'target',
        help='Bot to interact with',
    )

    kwargs = vars(parser.parse_args())

    call(
        kwargs.pop('server'),
        kwargs.pop('port'),
        kwargs.pop('command'),
        kwargs,
    )
