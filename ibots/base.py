import os
import json
import IPython
import logging
import requests
import operator

from functools import reduce
from abc import ABC, abstractmethod
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport

DIR = os.path.dirname(os.path.realpath(__file__))


class TerminateBotException(Exception):
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
        self._pause = False

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

    def api_call(self, operation, variable_values=None):
        # add some tracking for the status
        self._client.execute(gql(operation), variable_values=variable_values)

    def api_wait(self, operation=None, variables=None):
        result, event = self._waiter.wait(timeout=1)
        while not result:
            result, event = self._waiter.wait(event_last=event, timeout=1)
            if self._terminate:
                raise TerminateBotException

    def query_balance(self):
        return self.api_call(
            gql('''query Balance {{
                person (id: {id}) {{
                    id
                    balance
            }}
            '''))['person']['balance']

    def _interact(self):
        IPython.embed()

    def _status(self):
        pass

    @abstractmethod
    def start(self, **kwargs):
        pass

    @abstractmethod
    def run(self):
        pass

    @abstractmethod
    def command(self, instruction):
        pass


class AbstractBasicBot(AbstractBot):
    @classmethod
    def _user_type(node):
        if node['person']:
            return 'bot' if node['person']['isBot'] else 'human'
        return 'nonprofit'

    @classmethod
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
        for x in os.listdir()
    }

    IDS = {
        'user':
        lambda node: [
            {
                'name': 'ibid',
                'type': AbstractBasicBot._user_type(node),
                'location': ['id'], }, ],
        'nonprofit':
        lambda node: [
            {
                'name': 'ibid',
                'type': 'nonprofit',
                'location': ['ibisuserPtr', 'id'], }, ],
        'person':
        lambda node: [
            {
                'name': 'ibid',
                'type': 'person',
                'location': ['ibisuserPtr', 'id'], }, ],
        'donation':
        lambda node: [
            {
                'name': 'ibid',
                'type': 'donation',
                'location': ['id'], },
            {
                'name': 'user',
                'type': AbstractBasicBot._user_type(node),
                'location': ['user', 'id'], },
            {
                'name': 'target_ibid',
                'type': 'nonprofit',
                'location': ['user', 'id'], }, ],
        'transaction':
        lambda node: [
            {
                'name': 'ibid',
                'type': 'transaction',
                'location': ['id'], },
            {
                'name': 'user_ibid',
                'type': AbstractBasicBot._user_type(node),
                'location': ['user', 'id'], },
            {
                'name': 'target_ibid',
                'type': AbstractBasicBot._user_type(node),
                'location': ['user', 'id'], }, ],
        'news':
        lambda node: [
            {
                'name': 'ibid',
                'type': 'news',
                'location': ['id'], },
            {
                'name': 'user_ibid',
                'type': 'nonprofit',
                'location': ['user', 'id'], }, ],
        'event':
        lambda node: [
            {
                'name': 'ibid',
                'type': 'event',
                'location': ['id'], },
            {
                'name': 'user',
                'type': 'nonprofit',
                'location': ['user', 'id'], }, ],
        'post':
        lambda node: [
            {
                'name': 'ibid',
                'type': 'post',
                'location': ['id'], },
            {
                'name': 'user',
                'type': AbstractBasicBot._user_type(node['user']),
                'location': ['user', 'id'], }, ],
        'comment':
        lambda node: [
            {
                'name': 'ibid',
                'type': 'post',
                'location': ['id'], },
            {
                'name': 'user_ibid',
                'type': AbstractBasicBot._user_type(node['user']),
                'location': ['user', 'id'], },
            {
                'name': 'parent_ibid',
                'type': AbstractBasicBot._entry_type(node['parent']),
                'location': ['parent', 'id'], }, ],
    }

    class Ibid:
        def __init__(self, id, type):
            self.id = id
            self.type = type

        def __str__(self):
            return '{}:{}'.format(self.id, self.type)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if os.path.exists(os.path.join(self.directory, 'basic_state.json')):
            with open(os.path.join(self.directory, 'basic_state.json')) as fd:
                self.state = json.load(fd)

    def save_state(self):
        with open(self._store, 'w') as fd:
            json.dump(self._state, fd, indent=2)

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

    def query_comment_chain(self, ibid):
        comment = self.query_comment(ibid)
        return (self.query_comment_chain(comment.parent_ibid)
                if comment.parent_ibid.type == 'comment' else [
                    getattr(self, 'query_{}'.format(comment.parent_ibid.type))(
                        comment.parent_ibid)
                ]) + [comment]

    def query_comment_tree(self, ibid):
        return [{
            'comment': self.query_comment(x.ibid),
            'replies': self.query_comment_tree(x.ibid)
        } for x in self.query_comment_list(has_parent=ibid)]

    def query_user(self, ibid):
        return self._query_single('User', 'user', ibid)

    def query_nonprofit(self, ibid):
        return self._query_single('Nonprofit', 'nonprofit', ibid)

    def query_person(self, ibid):
        return self._query_single('Person', 'person', ibid)

    def query_donation(self, ibid):
        return self._query_single('Donation', 'donation', ibid)

    def query_transaction(self, ibid):
        return self._query_single('Transaction', 'transaction', ibid)

    def query_news(self, ibid):
        return self._query_single('News', 'news', ibid)

    def query_event(self, ibid):
        return self._query_single('Event', 'event', ibid)

    def query_post(self, ibid):
        return self._query_single('Post', 'post', ibid)

    def query_comment(self, ibid):
        return self._query_single('Comment', 'comment', ibid)

    def create_post(self, title, description):
        return self.Ibid(
            self._api_call_named(
                self.OPS['PostCreate'],
                variables={
                    'user': self.id,
                    'title': title,
                    'description': description,
                },
            )['post']['id'],
            'post',
        )

    def create_donation(self, target, amount, description):
        return self.Ibid(
            self._api_call_named(
                self.OPS['DonationCreate'],
                variables={
                    'user': self.id,
                    'target': target.id,
                    'amount': amount,
                    'description': description,
                },
            )['donation']['id'],
            'donation',
        )

    def create_transaction(self, target, amount, description):
        return self.Ibid(
            self._api_call_named(
                self.OPS['TransactionCreate'],
                variables={
                    'user': self.id,
                    'target': target.id,
                    'amount': amount,
                    'description': description,
                },
            )['transaction']['id'],
            'transaction',
        )

    def create_comment(self, parent, description):
        return self.Ibid(
            self._api_call_named(
                self.OPS['CommentCreate'],
                variables={
                    'user': self.id,
                    'parent': parent.id,
                    'description': description,
                },
            )['comment']['id'],
            'comment',
        )

    def update_bio(self, description):
        self._api_call_named(
            self.OPS['BioUpdate'],
            variables={
                'user': self.id,
                'description': description,
            },
        )

    def create_like(self, target):
        self._api_call_named(
            self.OPS['LikeCreate'],
            variables={
                'user': self.id,
                'target': target.id,
            },
        )

    def delete_like(self, target):
        self._api_call_named(
            self.OPS['LikeDelete'],
            variables={
                'user': self.id,
                'target': target.id,
            },
        )

    def create_follow(self, target):
        self._api_call_named(
            self.OPS['FollowCreate'],
            variables={
                'user': self.id,
                'target': target.id,
            },
        )

    def delete_follow(self, target):
        self._api_call_named(
            self.OPS['FollowDelete'],
            variables={
                'user': self.id,
                'target': target.id,
            },
        )

    def _clean_result(self, node, ids):
        return dict([[
            x['name'],
            self.Ibid(
                reduce(operator.getitem, x['location'], node), x['type'])
        ] for x in ids(node)] + [
            x for x in node.items()
            if type(x[1]) != dict and x[0] not in [y['name'] for y in ids]
        ])

    def _query_list(self, ops_key, ids_key, variables):
        return [
            self._clean_result(x['node'], ids=self.IDS[ids_key])
            for x in self.api_call(
                gql(self.OPS[ops_key]),
                variables_values={
                    ''.join(x.title() if i else x
                            for i, x in enumerate(k.split('_'))): v.
                    id if type(v) == AbstractBasicBot.Ibid else v
                    for k, v in variables if v is not None
                },
            )['edges']
        ]

    def _query_single(self, ops_key, ids_key, ibid):
        result = self._api_call_named(
            gql(self.OPS[ops_key]),
            variables_values={'id': ibid.id},
        )
        return [x for x in result[list(result.keys())[0]] if x != 'id']
