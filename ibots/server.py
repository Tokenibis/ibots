import os
import time
import json
import logging
import requests
import argparse

from importlib import import_module
from flask import Flask, request
from threading import Thread, Lock, Event
from base import TerminateBotException

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


def start(port, config, directory, bots=[]):
    waiter = Waiter(config['global']['endpoint'])

    assert all(x in config['bots'] for x in bots)
    if not bots:
        bot_names = set(x for x in config['bots'])

    assert all(
        y in config['resources'] for x in bots for y in config[x]['resources'])
    resource_names = set(y for x in bots for y in config[x]['resources'])

    # instantiate resources
    resources = {
        x: getattr(
            import_module(config['resources'][x]['class'].rsplit('.', 1)[0]),
            config['resources'][x]['class'].rsplit('.', 1)[1])(
                Lock(),
                **config['resources'][x]['args'],
            )
        for x in resource_names
    }

    # instantiate bots
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
        for x in bot_names
    }

    # start bots
    for x in bots:
        bots[x].start(**config['bots'][x]['args'])

    # run api polling
    poll_thread = Thread(target=waiter.poll, daemon=True)
    poll_thread.start()

    def _run_bot(bot):
        try:
            bot.run()
        except TerminateBotException:
            logger.info('Successfully stopped {}'.format(bot.username))

    # run bots
    threads = {
        x: Thread(target=_run_bot, args=(bots[x], ), daemon=True)
        for x in bots
    }
    for x in threads:
        threads[x].start()

    # start server
    app = Flask(__name__)

    @app.route('/status', methods=['POST'])
    def status():
        # loop through and delete all working directories of specified bots
        # but only if they are stopped
        # status should include:
        # - started/stopped
        # - last activity
        # - size of working directory
        # - last 10 api calls (time, type, name, variables)
        # - balance
        print(dict(request.form))

    @app.route('/start', methods=['POST'])
    def start():
        print(dict(request.form))

    @app.route('/stop', methods=['POST'])
    def stop():
        print(dict(request.form))

    @app.route('/wipe', methods=['POST'])
    def wipe():
        # loop through and delete all working directories of specified bots
        # but only if they are stopped
        print(dict(request.form))

    @app.route('/resource', methods=['POST'])
    def resource():
        for x in request.form.targets:
            resources[x].command(request.form.instruction)

    @app.route('/bot', methods=['POST'])
    def bot():
        for x in request.form.targets:
            bots[x].command(request.form.instruction)

    @app.route('/interact', methods=['POST'])
    def interact():
        interact_thread = Thread(bots[x]._interact)
        interact_thread.start()

    app.run(port=port)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'config',
        help='Configuration file',
    )
    parser.add_argument(
        '-p',
        '--port',
        help='Port number',
        default=8000,
    )
    parser.add_argument(
        '-b',
        '--bots',
        nargs='+',
        default=[],
        help='List of bots',
    )
    parser.add_argument(
        '-d',
        '--directory',
        help='Working directory',
        default=os.path.join(os.get_cwd(), 'ibots_store'),
    )

    args = parser.parse_args()

    with open(args.config) as fd:
        config = json.load(fd)

    start(args.port, config, args.directory, args.bots)
