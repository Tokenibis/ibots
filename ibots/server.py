import sys
import time
import json
import logging
import requests
import argparse

from importlib import import_module
from flask import Flask, request
from threading import Thread, Event
from ibots import base

logger = logging.getLogger('CONTROL')

PERIOD = 5
RETRY_NETWORK = 20


class Waiter:
    def __init__(self, endpoint, period=PERIOD):
        self._endpoint = endpoint
        self._period = period

    def poll(self):
        self._event = Event()
        latest = ''
        while True:
            logger.debug('Polling')
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


def start(port, level, std, endpoint, config, start_names=[]):
    if std:
        logging.basicConfig(
            stream=sys.stdout,
            level=logging._nameToLevel[level],
            format='%(asctime)s:%(name)s:%(levelname)s:%(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
    else:
        logging.basicConfig(
            filename='ibots.log',
            level=logging._nameToLevel[level],
            format='%(asctime)s:%(name)s:%(levelname)s:%(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )

    if not start_names:
        start_names = set(x for x in config)
    assert all(x in config for x in start_names)

    waiter = Waiter(endpoint)

    classes = {
        x: getattr(
            import_module(config[x]['class'].rsplit('.', 1)[0]),
            config[x]['class'].rsplit('.', 1)[1])
        for x in config for x in config
    }

    # run api polling
    poll_thread = Thread(target=waiter.poll, daemon=True)
    poll_thread.start()

    running = {x: False for x in config}
    bots = {x: None for x in config}

    def _run_bot(name, cls, init_args, run_args):
        running[name] = True
        while True:
            try:
                bot = cls(**init_args)
                bots[name] = bot
                logger.info('Running bot {}'.format(name))
                bot.run(**run_args)
            except base.BotStopException:
                logger.info('Stopped bot {}'.format(name))
                break
            except base.BotBalanceException:
                logger.error('{} is broke; exiting'.format(name))
                break
            except base.BotNetworkException:
                logger.warn('{} lost connection; retry in {}s'.format(
                    name,
                    RETRY_NETWORK,
                ))
                time.sleep(RETRY_NETWORK)
                continue
            except Exception:
                logger.exception('{} threw exception'.format(name))
                break

        running[name] = False

    # run bots
    threads = {
        x: Thread(
            target=_run_bot,
            args=(
                x,
                classes[x],
                {
                    'endpoint': endpoint,
                    'username': x,
                    'password': config[x]['password'],
                    'waiter': waiter,
                },
                config[x]['args'],
            ),
            daemon=True,
        )
        for x in start_names
    }
    for x in threads:
        threads[x].start()

    # start server
    app = Flask(__name__)

    for x in threads:
        threads[x].join()
    logger.info('All bots terminated')
    exit()

    @app.route('/', methods=['GET', 'POST'])
    def dash():
        return '''
<!DOCTYPE html>
<html>
<body>

<h1>The input checked attribute</h1>

<form action="/action_page.php" method="get">
  <input type="checkbox" name="vehicle1" value="Bike">
  <label for="vehicle1"> I have a bike</label><br>
  <input type="checkbox" name="vehicle2" value="Car">
  <label for="vehicle2"> I have a car</label><br>
  <input type="checkbox" name="vehicle3" value="Boat" checked>
  <label for="vehicle3"> I have a boat</label><br><br>
  <input type="submit" value="Submit">
</form>

</body>
</html>
        '''

    # @app.route('/status', methods=['POST'])
    # def status():
    #     target_set = set(
    #         request.form.to_dict(flat=False)['bots'] if request.
    #         form['bots'] else config['bots'])

    #     return {
    #         x: [
    #             ('Status', 'Running'),
    #         ] + bots[x]._status()
    #         for x in sorted(target_set)
    #     }

    # @app.route('/start', methods=['POST'])
    # def start():
    #     target_set = set(
    #         request.form.to_dict(flat=False)['bots'] if request.
    #         form['bots'] else [x for x in config['bots'] if not running[x]])
    #     assert all(not running[x] for x in target_set)

    #     threads = {
    #         x: Thread(target=_run_bot, args=(x, bots[x]), daemon=True)
    #         for x in target_set
    #     }

    #     for x in threads:
    #         threads[x].start()

    #     return 'Done'

    # @app.route('/stop', methods=['POST'])
    # def stop():
    #     target_set = set(
    #         request.form.to_dict(flat=False)['bots'] if request.
    #         form['bots'] else [x for x in config['bots'] if running[x]])
    #     assert all(running[x] for x in target_set)

    #     for x in target_set:
    #         x._stop = True

    #     while target_set:
    #         stopped = set()
    #         for x in target_set:
    #             if not running[x]:
    #                 stopped.add(x)
    #             target_set.difference_update(stopped)

    #     return 'Done'

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
        'endpoint',
        help='Connection endpoint',
    )
    parser.add_argument(
        '-p',
        '--port',
        help='Port number at which this server can be accesse by the client',
        default=8000,
    )
    parser.add_argument(
        '-s',
        '--std',
        help='Log to stdout',
        action='store_true',
    )
    parser.add_argument(
        '-l',
        '--level',
        help='Set log level ({})'.format('|'.join(logging._nameToLevel)),
        default='INFO',
    )
    parser.add_argument(
        '-b',
        '--bots',
        nargs='+',
        default=[],
        help='List of bots to start. If empty, start all configured bots',
    )

    return parser


def main():
    args = get_parser().parse_args()

    with open(args.config) as fd:
        config = json.load(fd)

    start(
        args.port,
        args.level,
        args.std,
        args.endpoint,
        config,
        args.bots,
    )
