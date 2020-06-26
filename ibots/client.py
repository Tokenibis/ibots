import json
import requests
import argparse


def call(server, port, command, kwargs):
    response = requests.post(
        '{}:{}/{}'.format(server, port, command),
        data=kwargs,
    )
    print(json.dumps(response.json(), indent=2))


def get_parser():
    parser = argparse.ArgumentParser(description='''
    This client controls a running version of ibots.server at the
    provided port by forwarding the provided subcommand to the correct
    path.''')

    parser.add_argument(
        '-s',
        '--server',
        help='Domain-level URL of ibots.server',
        default='http://localhost',
    )
    parser.add_argument(
        '-p',
        '--port',
        help='Port number of ibots.server',
        type=int,
        default=8000,
    )
    subparsers = parser.add_subparsers(dest='command')

    parser_status = subparsers.add_parser(
        'status',
        description='''
        Retrieve a JSON object describing the status of specified
        bots. The status contents will vary depending on the class of
        each bot.''',
    )
    parser_status.add_argument(
        '-b',
        '--bots',
        nargs='+',
        default=[],
        help='List of bots to target. If empty, target all applicable bots',
    )

    parser_start = subparsers.add_parser(
        'start',
        description='''
        Start bots that are configured but, for various reasons, may not
        be currently running''',
    )
    parser_start.add_argument(
        '-b',
        '--bots',
        nargs='+',
        default=[],
        help='List of bots to target. If empty, target all applicable bots',
    )

    parser_stop = subparsers.add_parser(
        'stop',
        description='''
        Send a *stop* signal to the given bots. If the bot is
        operational and well-programmed, it should stop within a few
        seconds.''',
    )
    parser_stop.add_argument(
        '-b',
        '--bots',
        nargs='+',
        default=[],
        help='List of bots to target. If empty, target all applicable bots',
    )

    parser_bot = subparsers.add_parser(
        'bot',
        description='''
        Execute a custom resource-defined command on the target
        resource instance.''',
    )
    parser_bot.add_argument(
        'targets',
        nargs='+',
        help='List of bots with which to execute the command',
    )
    parser_bot.add_argument(
        'instruction',
        help='Instruction to execute',
    )

    parser_resource = subparsers.add_parser(
        'resource',
        description='''
        Execute a custom resource-defined command on the target
        resource instance.''',
    )
    parser_resource.add_argument(
        'targets',
        nargs='+',
        help='List of resources with which to execute the command',
    )
    parser_resource.add_argument(
        'instruction',
        help='Instruction to execute',
    )

    parser_bot = subparsers.add_parser(
        'interact',
        description='''
        Request to open up an interactive shell to control the target
        bot. Once processed, the ibots.server program will open up an
        IPython shell with the same context as the bot's ``run``
        method''',
    )
    parser_bot.add_argument(
        'target',
        help='Bot to interact with',
    )
    return parser


if __name__ == '__main__':
    parser = get_parser()
    kwargs = vars(parser.parse_args())

    call(
        kwargs.pop('server'),
        kwargs.pop('port'),
        kwargs.pop('command'),
        kwargs,
    )
