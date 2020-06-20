import os
import json
import IPython
import logging
import requests
import operator
import ibots.utils as utils

from functools import reduce
from abc import ABC, abstractmethod
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport

DIR = os.path.dirname(os.path.realpath(__file__))


class StopBotException(Exception):
    pass


class AbstractResource(ABC):
    @abstractmethod
    def command(self, instruction):
        pass


class AbstractBot(ABC):
    def __init__(self, endpoint, directory, username, password, resources,
                 waiter):
        self.logger = logging.getLogger('BOT_{}'.format(
            self.__class__.__name__.upper()))
        self.directory = directory
        self._waiter = waiter
        self._stop = False
        self._interact = False

        if os.path.exists(self.directory) and os.path.isfile(self.directory):
            self.logger.error('Expected a directory but found a file; exiting')
        os.makedirs(self.directory, exist_ok=True)

        for key, value in resources.items():
            setattr(self, key, value)

        login_response = requests.post(
            'https://{}//ibis/login-pass/'.format(endpoint),
            data={
                'username': username,
                'password': password
            })

        self.id = login_response.json()['user_id']
        if not self.id:
            self.logger.error('Failed to log in')
            return

        self._client = Client(
            transport=RequestsHTTPTransport(
                url='https://{}/graphql/'.format(endpoint),
                cookies=login_response.cookies))

    def stop_hook(self):
        pass

    def api_call(self, operation, variable_values=None):
        return self._client.execute(
            gql(operation),
            variable_values=variable_values,
        )

    def api_wait(self, operation=None, variables=None):
        result, event = self._waiter.wait(timeout=1)
        while not result:
            if self._stop:
                self.logger.info('Initiating tear-down')
                self.stop_hook()
                self.logger.info('Done')
                raise StopBotException
            if self._interact:
                IPython.embed()
                self._interact = False
            result, event = self._waiter.wait(event_last=event, timeout=1)

    def _status(self):
        # call _client directly WITHOUT going through api_call
        try:
            result = self._client.execute(
                gql('''query Status {{
                person(id: "{id}"{{
                    id
                    name
                    username
                    balance
                }}
            }}
            '''.format(self.id)))

            return [
                ('API Connection', 'connected'),
                ('Logged in as', '{} ({})'.format(
                    result['person']['username'],
                    result['person']['name'],
                )),
                ('Balance',
                 utils.amount_to_string(result['person']['balance'])),
            ]
        except Exception:
            return [
                ('API Connection', 'disconnected'),
            ]

    @abstractmethod
    def run(self):
        pass

    @abstractmethod
    def command(self, instruction):
        pass


class AbstractBasicBot(AbstractBot):
    @staticmethod
    def _user_type(node):
        if node['person']:
            return 'bot' if node['person']['isBot'] else 'human'
        return 'nonprofit'

    @staticmethod
    def _entry_type(node):
        return [
            x for x in [
                'donation',
                'transaction',
                'news',
                'event',
                'post',
                'comment',
            ] if node[x]
        ][0]

    COUNT = 25

    OPS = {
        x.rsplit('.', 1)[0]: open(os.path.join(
            DIR,
            'graphql',
            'bots',
            x,
        )).read()
        for x in os.listdir(os.path.join(DIR, 'graphql', 'bots'))
    }

    BID_CONF = {
        'user':
        lambda node: [
            {
                'name': 'bid',
                'type': AbstractBasicBot._user_type(node),
                'location': ['id'], }, ],
        'nonprofit':
        lambda node: [
            {
                'name': 'bid',
                'type': 'nonprofit',
                'location': ['ibisuserPtr', 'id'], }, ],
        'person':
        lambda node: [
            {
                'name': 'bid',
                'type': 'bot' if node['isBot'] else 'human',
                'location': ['ibisuserPtr', 'id'], }, ],
        'donation':
        lambda node: [
            {
                'name': 'bid',
                'type': 'donation',
                'location': ['id'], },
            {
                'name': 'user',
                'type': AbstractBasicBot._user_type(node),
                'location': ['user', 'id'], },
            {
                'name': 'target',
                'type': 'nonprofit',
                'location': ['user', 'id'], }, ],
        'transaction':
        lambda node: [
            {
                'name': 'bid',
                'type': 'transaction',
                'location': ['id'], },
            {
                'name': 'user',
                'type': AbstractBasicBot._user_type(node),
                'location': ['user', 'id'], },
            {
                'name': 'target',
                'type': AbstractBasicBot._user_type(node),
                'location': ['user', 'id'], }, ],
        'news':
        lambda node: [
            {
                'name': 'bid',
                'type': 'news',
                'location': ['id'], },
            {
                'name': 'user',
                'type': 'nonprofit',
                'location': ['user', 'id'], }, ],
        'event':
        lambda node: [
            {
                'name': 'bid',
                'type': 'event',
                'location': ['id'], },
            {
                'name': 'user',
                'type': 'nonprofit',
                'location': ['user', 'id'], }, ],
        'post':
        lambda node: [
            {
                'name': 'bid',
                'type': 'post',
                'location': ['id'], },
            {
                'name': 'user',
                'type': AbstractBasicBot._user_type(node['user']),
                'location': ['user', 'id'], }, ],
        'comment':
        lambda node: [
            {
                'name': 'bid',
                'type': 'post',
                'location': ['id'], },
            {
                'name': 'user',
                'type': AbstractBasicBot._user_type(node['user']),
                'location': ['user', 'id'], },
            {
                'name': 'parent',
                'type': AbstractBasicBot._entry_type(node['parent']),
                'location': ['parent', 'id'], }, ],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bid = self._make_bid(self.id, 'bot')
        self._basic_store = os.path.join(
            self.directory,
            'basic_state_{}.json'.format(
                utils.snake_case(self.__class__.__name__)),
        )
        if os.path.exists(self._basic_store):
            with open(self._basic_store) as fd:
                self.state = json.load(fd)
        else:
            self.state = {}
            with open(self._basic_store, 'w') as fd:
                json.dump(self.state, fd, indent=2)
        self._state_string = json.dumps(self.state, indent=2)

    def _status(self):
        return super()._status() + [('Basic Storage Size',
                                     os.path.getsize(self._basic_store))]

    @staticmethod
    def _make_bid(id, type):
        return '__bid__:{}:{}'.format(id, type)

    @staticmethod
    def _is_bid(bid):
        return type(bid) == str and len(
            bid.split(':')) == 3 and bid.split(':')[0] == '__bid__'

    @staticmethod
    def _parse_bid(bid):
        assert AbstractBasicBot._is_bid(bid)
        return {
            'id': bid.split(':')[1],
            'type': bid.split(':')[2],
        }

    def stop_hook(self):
        self.save_state()

    def save_state(self):
        state_string = json.dumps(self.state)
        if state_string != self._state_string:
            self._state_strin = state_string
            with open(self._basic_store, 'w') as fd:
                fd.write(self._state_string)

    def query_balance(self, **kwargs):
        return self.api_call(
            self.OPS['Balance'],
            variable_values={
                'id': self.id,
            },
        )['person']['id']

    def query_user_list(self, **kwargs):
        return self._query_list('IbisUserList', 'user', kwargs)

    def query_nonprofit_list(self, **kwargs):
        return self._query_list('NonprofitList', 'nonprofit', kwargs)

    def query_person_list(self, **kwargs):
        return self._query_list('PersonList', 'person', kwargs)

    def query_donation_list(self, **kwargs):
        return self._query_list('DonationList', 'donation', kwargs)

    def query_transaction_list(self, **kwargs):
        return self._query_list('TransactionList', 'transaction', kwargs)

    def query_news_list(self, **kwargs):
        return self._query_list('NewsList', 'news', kwargs)

    def query_event_list(self, **kwargs):
        return self._query_list('EventList', 'event', kwargs)

    def query_post_list(self, **kwargs):
        return self._query_list('PostList', 'post', kwargs)

    def query_comment_list(self, **kwargs):
        return self._query_list('CommentList', 'comment', kwargs)

    def query_comment_chain(self, bid):
        comment = self.query_comment(bid)
        return (self.query_comment_chain(comment['parent'])
                if comment['parent'].type == 'comment' else [
                    getattr(self, 'query_{}'.format(comment['parent'].type))(
                        comment['parent'])
                ]) + [comment]

    def query_comment_tree(self, bid):
        return [{
            'comment': self.query_comment(x.bid),
            'replies': self.query_comment_tree(x.bid)
        } for x in self.query_comment_list(has_parent=bid)]

    def query_user(self, bid):
        return self._query_single('IbisUser', 'user', bid)

    def query_nonprofit(self, bid):
        return self._query_single('Nonprofit', 'nonprofit', bid)

    def query_person(self, bid):
        return self._query_single('Person', 'person', bid)

    def query_donation(self, bid):
        return self._query_single('Donation', 'donation', bid)

    def query_transaction(self, bid):
        return self._query_single('Transaction', 'transaction', bid)

    def query_news(self, bid):
        return self._query_single('News', 'news', bid)

    def query_event(self, bid):
        return self._query_single('Event', 'event', bid)

    def query_post(self, bid):
        return self._query_single('Post', 'post', bid)

    def query_comment(self, bid):
        return self._query_single('Comment', 'comment', bid)

    def create_post(self, title, description):
        return self._make_bid(
            utils.first_item(
                self.api_call(
                    self.OPS['PostCreate'],
                    variable_values={
                        'user': self._parse_bid(self.bid)['id'],
                        'title': title,
                        'description': description,
                    },
                ),
                depth=3,
            ),
            'post',
        )

    def create_donation(self, target, amount, description):
        return self._make_bid(
            utils.first_item(
                self.api_call(
                    self.OPS['DonationCreate'],
                    variable_values={
                        'user': self._parse_bid(self.bid)['id'],
                        'target': self._parse_bid(target)['id'],
                        'amount': amount,
                        'description': description,
                    },
                ),
                depth=3,
            ),
            'donation',
        )

    def create_transaction(self, target, amount, description):
        return self._make_bid(
            utils.first_item(
                self.api_call(
                    self.OPS['TransactionCreate'],
                    variable_values={
                        'user': self._parse_bid(self.bid)['id'],
                        'target': self._parse_bid(target)['id'],
                        'amount': amount,
                        'description': description,
                    },
                ),
                depth=3,
            ),
            'transaction',
        )

    def create_comment(self, parent, description):
        return self._make_bid(
            utils.first_item(
                self.api_call(
                    self.OPS['CommentCreate'],
                    variable_values={
                        'user': self._parse_bid(self.bid)['id'],
                        'parent': self._parse_bid(parent)['id'],
                        'description': description,
                    },
                ),
                depth=3,
            ),
            'comment',
        )

    def update_bio(self, description):
        self.api_call(
            self.OPS['BioUpdate'],
            variable_values={
                'user': self._parse_bid(self.bid)['id'],
                'description': description,
            },
        )

    def create_like(self, target):
        self.api_call(
            self.OPS['LikeCreate'],
            variable_values={
                'user': self._parse_bid(self.bid)['id'],
                'target': self._parse_bid(target)['id'],
            },
        )

    def delete_like(self, target):
        self.api_call(
            self.OPS['LikeDelete'],
            variable_values={
                'user': self._parse_bid(self.bid)['id'],
                'target': self._parse_bid(target)['id'],
            },
        )

    def create_follow(self, target):
        self.api_call(
            self.OPS['FollowCreate'],
            variable_values={
                'user': self._parse_bid(self.bid)['id'],
                'target': self._parse_bid(target)['id'],
            },
        )

    def delete_follow(self, target):
        self.api_call(
            self.OPS['FollowDelete'],
            variable_values={
                'user': self.id,
                'target': target.id,
                'user': self._parse_bid(self.bid)['id'],
                'target': self._parse_bid(target)['id'],
            },
        )

    def _clean_result(self, node, bid_conf):
        return dict([[
            x['name'],
            self._make_bid(
                reduce(operator.getitem, x['location'], node), x['type'])
        ] for x in bid_conf(node)] + [[
            utils.snake_case(k),
            v,
        ] for k, v in node.items() if type(v) != dict and k not in ['ids'] +
                                      [y['name'] for y in bid_conf(node)]])

    def _query_list(self, ops_key, bid_conf_key, variables):
        return [
            self._clean_result(x['node'], self.BID_CONF[bid_conf_key])
            for x in utils.first_item(
                self.api_call(
                    self.OPS[ops_key],
                    variable_values={
                        utils.mixed_case(k): self._parse_bid(v)['id'] if self.
                        _is_bid(v) else v
                        for k, v in variables.items() if v is not None
                    },
                ))['edges']
        ]

    def _query_single(self, ops_key, bid_conf_key, bid):
        return self._clean_result(
            utils.first_item(
                self.api_call(
                    self.OPS[ops_key],
                    variable_values={'id': self._parse_bid(bid)['id']},
                )),
            self.BID_CONF[bid_conf_key],
        )
