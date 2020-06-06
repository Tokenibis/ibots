from ibots.base import AbstractBasicBot


class HelloBot(AbstractBasicBot):
    def start(self):
        # If first time starting, the initialize the list
        if 'people_greeted' not in self.state:
            self.state['people_greeted'] = []

    def run(self):
        # If first time running, in then make "hello world" post
        if 'post_ibid' not in self.state:
            self.state['post_ibid'] = self.create_post(
                title='Hello, world!',
                description='Nice to meet everyone.',
            )
            self.save_state()

        # Keep an eye out on the post and greet anybody who replies
        while True:
            self.api_wait()
            for comment in self.query_comment_list(
                    parent=self.state['post_ibid']):
                if self.ibid not in [
                        x['ibid']
                        for x in self.query_comments_to(comment['ibid'])
                ]:
                    self.comment(
                        comment['ibid'],
                        'Hi, {}'.format(
                            self.query_user(
                                comment['user_ibid'])['short_name']),
                    )
                self.state['people_greeted'].append(comment['user_ibid'])
                self.save_state()

    def command(self, instruction):
        # log incoming instructions, but don't act on them
        self.logger.info(' {}'.format(instruction))
