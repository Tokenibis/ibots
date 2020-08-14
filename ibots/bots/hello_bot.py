from ibots.base import AbstractBasicBot


class HelloWorldBot(AbstractBasicBot):
    def run(self):
        self.activity_create(
            title='Hello, world!',
            description='Nice to meet everyone.',
            active=True,
        )

        while True:
            self.api_wait()
