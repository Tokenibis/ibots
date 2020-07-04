import random

from ibots.base import AbstractBasicBot


class TwoPlayerBlackjack(AbstractBasicBot):
    def run(self):
        if 'games' not in self.state:
            self.state['games'] = {}

        while True:
            for x in self.query_transaction_list(target=self.bid):
                if x.bid not in self.state['games']:
                    deck = [[x, y] for x in list(range(1, 15))
                            for y in ['S', 'C', 'D', 'H']]
                    random.shuffle(deck)
                    self.state['games'][x.bid] = {
                        'deck': deck,
                        'player_score': 0,
                        'dealer_score': 0,
                        'initial_move': x.bid,
                        'last_move': x.bid,
                        'in_progress': True,
                    }
            self.save_state()

            for x in self.query_comment_list(has_parent=):


            # walk down the comment tree
            # if last move was players, then calculate score and update state

            self.api_wait()

    def command(self, instruction):
        name, value = instruction.split(':')

        if name == 'invite':
            self.invite(value)
        else:
            raise ValueError('Unrecognized command')

    def invite(self, username):
        """Invite the specified user to play rock, paper, scissors"""

        target = [
            x for x in self.query_person_list(search=username)
            if x.username == username
        ][0]

        self.create_transaction(
            target=target,
            amount=1,
            description='Hey {}, want to play blackjack?'.format(
                target.short_name),
        )
