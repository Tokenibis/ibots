import os
import time
import json
import logging
import requests
import argparse
import traceback

from importlib import import_module
from flask import Flask, request
from threading import Thread, Lock, Event
from ibots.base import StopBotException

logger = logging.getLogger('CONTROL')


class Waiter:
    def __init__(self, endpoint, period=10):
        self._endpoint = endpoint
        self._period = period

    def poll(self):
        self._event = Event()
        latest = ''
        while True:
            response = requests.get('https://{}/tracker/wait/'.format(
                self._endpoint))
            if response.text != latest:
                self._event.set()
                self._event = Event()
                latest = response.text
            time.sleep(self._period)

    def wait(self, event_last=None, timeout=None):
        event = event_last if event_last else self._event

        if event.wait(timeout):
            return True, event
        else:
            return False, event


def start(port, config, directory, start_names=[]):
    assert all(y in config['resources'] for x in config['bots']
               for y in config['bots'][x]['resources'])

    if not start_names:
        start_names = set(x for x in config['bots'])
    assert all(x in config['bots'] for x in start_names)

    waiter = Waiter(config['global']['endpoint'])

    # instantiate resources
    resources = {
        x: getattr(
            import_module(config['resources'][x]['class'].rsplit('.', 1)[0]),
            config['resources'][x]['class'].rsplit('.', 1)[1])(
                Lock(),
                **config['resources'][x]['args'],
            )
        for x in config['resources']
    }

    # instantiate all bots
    bots = {
        x: getattr(
            import_module(config['bots'][x]['class'].rsplit('.', 1)[0]),
            config['bots'][x]['class'].rsplit('.', 1)[1])(
                config['global']['endpoint'],
                os.path.join(directory, x),
                x,
                config['bots'][x]['password'],
                {y: resources[y]
                 for y in config['bots'][x]['resources']},
                waiter,
            )
        for x in config['bots']
    }

    # run api polling
    poll_thread = Thread(target=waiter.poll, daemon=True)
    poll_thread.start()

    running = {x: False for x in bots}

    def _run_bot(name, bot):
        try:
            running[name] = True
            logger.info('Running bot {}'.format(name))
            bot.run()
        except StopBotException:
            logger.info('Stopped bot {}'.format(name))
        running[name] = False

    # run bots
    threads = {
        x: Thread(target=_run_bot, args=(x, bots[x]), daemon=True)
        for x in start_names
    }
    for x in threads:
        threads[x].start()

    # start server
    app = Flask(__name__)

    @app.route('/status', methods=['POST'])
    def status():
        target_set = set(
            request.form.to_dict(flat=False)['bots'] if request.
            form['bots'] else config['bots'])

        return {
            x: [
                ('Status', 'Running'),
                ('Directory Size', '5 MiB'),
            ] + bots[x]._status()
            for x in sorted(target_set)
        }

    @app.route('/start', methods=['POST'])
    def start():
        target_set = set(
            request.form.to_dict(flat=False)['bots'] if request.
            form['bots'] else [x for x in config['bots'] if not running[x]])
        assert all(not running[x] for x in target_set)

        threads = {
            x: Thread(target=_run_bot, args=(x, bots[x]), daemon=True)
            for x in target_set
        }

        for x in threads:
            threads[x].start()

        return 'Done'

    @app.route('/stop', methods=['POST'])
    def stop():
        target_set = set(
            request.form.to_dict(flat=False)['bots'] if request.
            form['bots'] else [x for x in config['bots'] if running[x]])
        assert all(running[x] for x in target_set)

        for x in target_set:
            x._stop = True

        while target_set:
            stopped = set()
            for x in target_set:
                if not running[x]:
                    stopped.add(x)
                target_set.difference_update(stopped)

        return 'Done'

    @app.route('/resource', methods=['POST'])
    def resource():
        assert all(x in resources for x in request.form['targets'])
        try:
            return {
                x: resources[x].command(request.form['instruction'])
                for x in request.form['targets']
            }
        except Exception as e:
            logger.exception(e)

    @app.route('/bot', methods=['POST'])
    def bot():
        assert all(running[x] for x in request.form['targets'])
        return {
            x: bots[x].command(request.form['instruction'])
            for x in request.form['targets']
        }

    @app.route('/interact', methods=['POST'])
    def interact():
        bots[request.form['target']]._interact = True
        return 'Done'

    app.run(port=port)


def get_parser():
    parser = argparse.ArgumentParser(description='''
        This server runs the bot deployment platform. The server executes
        bot logic in parallel threads and handles interactions with
        the remote Token Ibis endpoint. It can be controlled by
        accessing ``http://localhost:port`` with ibots.client from a
        different terminal.''')

    parser.add_argument(
        'config',
        help='JSON configuration file for the deployment',
    )
    parser.add_argument(
        '-p',
        '--port',
        help='Port number at which this server can be accesse by the client',
        default=8000,
    )
    parser.add_argument(
        '-d',
        '--directory',
        help='Working directory store persistent state for each bot instance',
        default=os.path.join(os.getcwd(), 'ibots_store'),
    )
    parser.add_argument(
        '-b',
        '--bots',
        nargs='+',
        default=[],
        help='List of bots to start. If empty, start all configured bots',
    )

    return parser


if __name__ == '__main__':
    args = get_parser().parse_args()

    with open(args.config) as fd:
        config = json.load(fd)

    start(args.port, config, args.directory, args.bots)
