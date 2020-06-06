import time

from threading import Thread
from ibots.base import AbstractBasicBot


class TestBot(AbstractBasicBot):
    def start(self):
        print('Starting')

    def run(self):
        print('Running')
        # crawl through all API stuff
        # spin off thread to test waiting
        # spin off thread to test out commands

    def command(self, instruction):
        print('Executing {}'.format(instruction))
