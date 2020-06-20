from ibots.base import AbstractBasicBot


class HelloBot(AbstractBasicBot):
    def run(self):
        # check to see if I've already posted before
        posts = self.query_post_list(by_user=self.bid)

        # only post if I haven't already
        if posts:
            self.state['post_bid'] = posts[0]['bid']
        else:
            self.state['post_bid'] = self.create_post(
                title='Hello, world!',
                description='Nice to meet everyone.',
            )
            self.save_state()

        # keep an eye on my last post and reply to anybody who replies
        while True:
            for comment in self.query_comment_list(
                    has_parent=self.state['post_bid']):
                if self.bid not in [
                        x['user'] for x in self.query_comment_list(
                            has_parent=comment['bid'])
                ]:
                    self.create_comment(
                        comment['bid'],
                        'Hi, {}'.format(
                            self.query_user(comment['user'])['short_name']),
                    )
            self.api_wait()

    def command(self, instruction):
        # log incoming instructions, but don't act on them
        self.logger.info(' {}'.format(instruction))
