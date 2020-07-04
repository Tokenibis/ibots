import os
import time
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
    """Say something about the fact that it uses

    :ivar logger: (:class:`logging.Logger`) -- ibot-specific logger
    :ivar <resources>: (:class:`ibots.base.AbstractResource`) --
       resources specified in the config will get added as an
       attribute with the same name as the "key" value in the config

    """

    def __init__(self, endpoint, directory, username, password, resources,
                 waiter):

        self.logger = logging.getLogger('BOT_{}'.format(
            self.__class__.__name__.upper()))
        self._directory = directory
        self._waiter = waiter
        self._stop = False
        self._interact = False

        if os.path.exists(self._directory) and os.path.isfile(self._directory):
            self.logger.error('Expected a directory but found a file; exiting')
        os.makedirs(self._directory, exist_ok=True)

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
        """Override this hook to execute any code that runs just before the
        controller safely stops a bot.

        """
        pass

    def api_call(self, operation, variables=None):
        """Execute the gql query and variables on the remote endpoint.

        :param operation: GraphQL query to execute
        :type operation: str

        :param variables: GraphQL variable key/value pairs
        :type variables: dict, optional

        :return: JSON object returned by the remote endpoint call.
        :rtype: JSON object

        """

        return self._client.execute(
            gql(operation),
            variable_values=variables,
        )

    def api_wait(self, timeout=None):
        """Wait until anything useful at all happens at the remote endpoint.
        While waiting, the controller may interrupt to safely stop or
        interact with the bot.

        :param timeout: Number of seconds to timeout if nothing happens
        :type timeout: int, optional

        """
        start = time.time()
        result, event = self._waiter.wait(timeout=1)
        while not result and (not timeout or time.now() - start < timeout):
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
        """Calculate and return the status of the bot. This method should only
        be called internally by the controller.

        :return: List of key-value pairs of status indicators
        :rtype: list of tuples

        """
        # call _client directly *without* going through api_call
        try:
            result = self._client.execute(
                gql('''query Status {{
                person(id: "{id}"{{
                    id
                    name
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
    """Say something about the fact that it uses

    :ivar bid: :term:`BID` of the bot
    :ivar state: Persistent state of the bot

    """

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
            self._directory,
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

    def save_state(self):
        """Write the current state of :attr:`state` to disk if it has changed
        since the last call to :func:`save_state`.

        """

        state_string = json.dumps(self.state)
        if state_string != self._state_string:
            self._state_strin = state_string
            with open(self._basic_store, 'w') as fd:
                fd.write(self._state_string)

    def query_balance(self):
        """The bot's current balance.

        :return: Current balance denominated in cents
        :rtype: int

        """

        return self.api_call(
            self.OPS['Balance'],
            variables={
                'id': self.id,
            },
        )['person']['balance']

    def query_user_list(self, **kwargs):
        """Retrieve a list of recently joined users.

        :param search: Query only users whose username or full name
           contains this substring
        :type search: str, optional

        :param followed_by: Query only users who are followed by this
            user
        :type followed_by: :term:`BID`, optional

        :param followed_of: Query only users who follow this user
        :type followed_of: :term:`BID`, optional

        :param like_for: Query only users who liked this entry
        :type like_for: :term:`BID`, optional

        :param rsvp_for: Query only users who rsvp'd for this event
        :type rsvp_for: :term:`BID`, optional

        :param order_by: Specify query order; see schema at
            ``https://<endpoint>/graphql`` for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the user
            * :attr:`username` (*str*) -- user's on-app username
            * :attr:`short_name` (*str*) -- either the first name alone if
              available OR the last name alone (this is typically the
              best way to refer to a user since nonprofits don't have
              first names)
            * :attr:`full_name` (*str*) -- user's full name
            * :attr:`first_name` (*str*) -- user's first name
            * :attr:`last_name` (*str*) -- user's last name

        """
        return self._query_list('IbisUserList', 'user', kwargs)

    def query_nonprofit_list(self, **kwargs):
        """Retrieve a list of recently joined nonprofits.

        :param search: Query only nonprofits whose username or full name
           contains this substring
        :type search: str, optional

        :param followed_by: Query only nonprofits who are followed by this
            user
        :type followed_by: :term:`BID`, optional

        :param followed_of: Query only nonprofits who follow this user
        :type followed_of: :term:`BID`, optional

        :param like_for: Query only nonprofits who liked this entry
        :type like_for: :term:`BID`, optional

        :param rsvp_for: Query only nonprofits who rsvp'd for this event
        :type rsvp_for: :term:`BID`, optional

        :param order_by: Specify query order; see schema at
            ``https://<endpoint>/graphql`` for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the nonprofit
            * :attr:`username` (*str*) -- nonprofit's on-app username
            * :attr:`short_name` (*str*) -- nonprofit name
            * :attr:`full_name` (*str*) -- nonprofit name
            * :attr:`first_name` (*str*) -- blank (included for consistency)
            * :attr:`last_name` (*str*) -- nonprofit name

        """
        return self._query_list('NonprofitList', 'nonprofit', kwargs)

    def query_person_list(self, **kwargs):
        """Retrieve a list of recently joined people.

        :param search: Query only people whose username or full name
           contains this substring
        :type search: str, optional

        :param followed_by: Query only people who are followed by this
            user
        :type followed_by: :term:`BID`, optional

        :param followed_of: Query only people who follow this user
        :type followed_of: :term:`BID`, optional

        :param like_for: Query only people who liked this entry
        :type like_for: :term:`BID`, optional

        :param rsvp_for: Query only people who rsvp'd for this event
        :type rsvp_for: :term:`BID`, optional

        :param order_by: Specify query order; see schema at
            ``https://<endpoint>/graphql`` for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the person
            * :attr:`username` (*str*) -- person's on-app username
            * :attr:`short_name` (*str*) -- person's first name
            * :attr:`full_name` (*str*) -- person's full name
            * :attr:`first_name` (*str*) -- person's first name
            * :attr:`last_name` (*str*) -- person's last name

        """
        return self._query_list('PersonList', 'person', kwargs)

    def query_donation_list(self, **kwargs):
        """Retrieve a list of recently made donations.

        :param search: Query only donations with a description, usernames, or
            user full names that contains this substring
        :type search: str, optional

        :param by_user: Query only donations made or received by this user
        :type by_user: :term:`BID`, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the donation
            * :attr:`user` (:term:`BID`) -- handler for the donation sender
            * :attr:`target` (:term:`BID`) -- handler for the donation
              recipient
            * :attr:`amount` (*int*) -- donation amount in cents
            * :attr:`description` (*str*) -- donation description
            * :attr:`created` (*str*) -- datetime the donation was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the donation

        """
        return self._query_list('DonationList', 'donation', kwargs)

    def query_transaction_list(self, **kwargs):
        """Retrieve a list of recently made transactions.

        :param search: Query only transactions with a description,
            usernames, or user full names that contains this substring
        :type search: str, optional

        :param by_user: Query only transactions made or received by this user
        :type by_user: :term:`BID`, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the transaction
            * :attr:`user` (:term:`BID`) -- handler for the transaction sender
            * :attr:`target` (:term:`BID`) -- handler for the
              transaction recipient
            * :attr:`amount` (*int*) -- transaction amount in cents
            * :attr:`description` (*str*) -- transaction description
            * :attr:`created` (*str*) -- datetime the transaction was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the transaction

        """
        return self._query_list('TransactionList', 'transaction', kwargs)

    def query_news_list(self, **kwargs):
        """Retrieve a list of recently made news articles.

        :param search: Query only news articles with a nonprofit
            username or full name, title, or content that contains
            this substring,
        :type search: str, optional

        :param by_user: Query only news articles posted by this nonprofit
        :type by_user: :term:`BID`, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the transaction
            * :attr:`user` (:term:`BID`) -- handler for the associated
              nonprofit
            * :attr:`title` (*str*) -- title of the news article
            * :attr:`description` (*str*) -- news article content
            * :attr:`created` (*str*) -- datetime the news article was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the news article

        """
        return self._query_list('NewsList', 'news', kwargs)

    def query_event_list(self, **kwargs):
        """Retrieve a list of recently made events.

        :param search: Query only events with a nonprofit
            username or full name, title, or content that contains
            this substring,
        :type search: str, optional

        :param by_user: Query only events planned by this nonprofit
        :type by_user: :term:`BID`, optional

        :param rsvp_by: Query only events rsvp'd by this user
        :type rsvp_by: :term:`BID`, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the transaction
            * :attr:`user` (:term:`BID`) -- handler for the associated
              nonprofit
            * :attr:`title` (*str*) -- title of the event
            * :attr:`description` (*str*) -- event content
            * :attr:`created` (*str*) -- datetime the event was created
            * :attr:`like_count` (*int*) -- number of users who have
            * :attr:`date` (*str*) -- datetime the event is scheduled for
            * :attr:`duration` (*int*) -- time in minutes the event will take
            * :attr:`address` (*str*) -- physical location of the event
              liked the event

        """
        return self._query_list('EventList', 'event', kwargs)

    def query_post_list(self, **kwargs):
        """Retrieve a list of recently made posts.

        :param search: Query only posts with a person's
            username or full name, title, or content that contains
            this substring,
        :type search: str, optional

        :param by_user: Query only posts posted by this person
        :type by_user: :term:`BID`, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the transaction
            * :attr:`user` (:term:`BID`) -- handler for the associated person
            * :attr:`title` (*str*) -- title of the post
            * :attr:`description` (*str*) -- post content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        return self._query_list('PostList', 'post', kwargs)

    def query_comment_list(self, **kwargs):
        """Retrieve a list of recently made comments. Since parsing comment
        trees can be tedious, :class:`AbstractBasicBot` provides the
        higher-level methods :func:`query_comment_chain` and
        :func:`query_comment_tree` methods.

        :param has_parent: Query only comments that are replying to this entry
        :type has_parent: :term:`BID`, optional

        :param search: Query only posts with a person's
            username or full name, title, or content that contains
            this substring,
        :type search: str, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the comment
            * :attr:`user` (:term:`BID`) -- handler for the commenting user
            * :attr:`parent` (:term:`BID`) -- handler for entry the
              comment is responding to
            * :attr:`description` (*str*) -- comment content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        return self._query_list('CommentList', 'comment', kwargs)

    def query_comment_chain(self, bid):
        """Retrieve the entire chain of comments and root :term:`entry` that
        the provided comment is responding to.

        :param bid: Starting comment
        :type bid: :term:`BID`

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the comment
            * :attr:`user` (:term:`BID`) -- handler for the commenting user
            * :attr:`parent` (:term:`BID`) -- handler for entry the
              comment is responding to
            * :attr:`description` (*str*) -- comment content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        comment = self.query_comment(bid)
        return (self.query_comment_chain(comment['parent'])
                if comment['parent'].type == 'comment' else [
                    getattr(self, 'query_{}'.format(comment['parent'].type))(
                        comment['parent'])
                ]) + [comment]

    def query_comment_tree(self, bid):
        """Retrieve the entire conversation tree of comments stemming from the
        provided comment.

        :param bid: Starting comment
        :type bid: :term:`BID`

        :return: Recursive list of dictionaries with the keys/value pairs:

            * :attr:`comment` (*dict*) -- dictionary containing the
              comment information (see below).
            * :attr:`replies` (*list*) -- list of dictionaries
              containing this same dicionary key/value pair format.

          Each :attr:`comment` dictionary of the structure above
          contains the following key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the comment
            * :attr:`user` (:term:`BID`) -- handler for the commenting user
            * :attr:`parent` (:term:`BID`) -- handler for entry the
              comment is responding to
            * :attr:`description` (*str*) -- comment content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        return [{
            'comment': self.query_comment(x.bid),
            'replies': self.query_comment_tree(x.bid)
        } for x in self.query_comment_list(has_parent=bid)]

    def query_user(self, bid):
        """Retrieve information for a single provided user.

        :param followed_by: User to query
        :type followed_by: :term:`BID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the user
            * :attr:`username` (*str*) -- user's on-app username
            * :attr:`short_name` (*str*) -- either the first name alone if
              available OR the last name alone (this is typically the
              best way to refer to a user since nonprofits don't have
              first names)
            * :attr:`full_name` (*str*) -- user's full name
            * :attr:`first_name` (*str*) -- user's first name
            * :attr:`last_name` (*str*) -- user's last name

        """
        return self._query_single('IbisUser', 'user', bid)

    def query_nonprofit(self, bid):
        """Retrieve information for a single provided nonprofit.

        :param followed_by: Nonprofit to query
        :type followed_by: :term:`BID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the nonprofit
            * :attr:`username` (*str*) -- nonprofit's on-app username
            * :attr:`short_name` (*str*) -- nonprofit name
            * :attr:`full_name` (*str*) -- nonprofit name
            * :attr:`first_name` (*str*) -- blank (included for consistency)
            * :attr:`last_name` (*str*) -- nonprofit name

        """
        return self._query_single('Nonprofit', 'nonprofit', bid)

    def query_person(self, bid):
        """Retrieve information for a single provided person.

        :param followed_by: Person to query
        :type followed_by: :term:`BID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the person
            * :attr:`username` (*str*) -- person's on-app username
            * :attr:`short_name` (*str*) -- person's first name
            * :attr:`full_name` (*str*) -- person's full name
            * :attr:`first_name` (*str*) -- person's first name
            * :attr:`last_name` (*str*) -- person's last name

        """
        return self._query_single('Person', 'person', bid)

    def query_donation(self, bid):
        """Retrieve information for a single provided donation.

        :param followed_by: Donation to query
        :type followed_by: :term:`BID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the donation
            * :attr:`user` (:term:`BID`) -- handler for the donation sender
            * :attr:`target` (:term:`BID`) -- handler for the donation
              recipient
            * :attr:`amount` (*int*) -- donation amount in cents
            * :attr:`description` (*str*) -- donation description
            * :attr:`created` (*str*) -- datetime the donation was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the donation

        """
        return self._query_single('Donation', 'donation', bid)

    def query_transaction(self, bid):
        """Retrieve information for a single provided transaction.

        :param followed_by: Transaction to query
        :type followed_by: :term:`BID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the transaction
            * :attr:`user` (:term:`BID`) -- handler for the transaction sender
            * :attr:`target` (:term:`BID`) -- handler for the
              transaction recipient
            * :attr:`amount` (*int*) -- transaction amount in cents
            * :attr:`description` (*str*) -- transaction description
            * :attr:`created` (*str*) -- datetime the transaction was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the transaction

        """
        return self._query_single('Transaction', 'transaction', bid)

    def query_news(self, bid):
        """Retrieve information for a single provided news article.

        :param followed_by: News article to query
        :type followed_by: :term:`BID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the transaction
            * :attr:`user` (:term:`BID`) -- handler for the associated
              nonprofit
            * :attr:`title` (*str*) -- title of the news article
            * :attr:`description` (*str*) -- news article content
            * :attr:`created` (*str*) -- datetime the news article was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the news article

        """
        return self._query_single('News', 'news', bid)

    def query_event(self, bid):
        """Retrieve information for a single provided event.

        :param followed_by: Event to query
        :type followed_by: :term:`BID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the transaction
            * :attr:`user` (:term:`BID`) -- handler for the associated
              nonprofit
            * :attr:`title` (*str*) -- title of the event
            * :attr:`description` (*str*) -- event content
            * :attr:`created` (*str*) -- datetime the event was created
            * :attr:`like_count` (*int*) -- number of users who have
            * :attr:`date` (*str*) -- datetime the event is scheduled for
            * :attr:`duration` (*int*) -- time in minutes the event will take
            * :attr:`address` (*str*) -- physical location of the event
              liked the event

        """
        return self._query_single('Event', 'event', bid)

    def query_post(self, bid):
        """Retrieve information for a single provided post.

        :param followed_by: Post to query
        :type followed_by: :term:`BID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the transaction
            * :attr:`user` (:term:`BID`) -- handler for the associated person
            * :attr:`title` (*str*) -- title of the post
            * :attr:`description` (*str*) -- post content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        return self._query_single('Post', 'post', bid)

    def query_comment(self, bid):
        """Retrieve information for a single provided comment.

        :param followed_by: Comment to query
        :type followed_by: :term:`BID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`bid` (:term:`BID`) -- handler for the comment
            * :attr:`user` (:term:`BID`) -- handler for the commenting user
            * :attr:`parent` (:term:`BID`) -- handler for entry the
              comment is responding to
            * :attr:`description` (*str*) -- comment content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        return self._query_single('Comment', 'comment', bid)

    def create_post(self, title, description):
        """Create a new post

        :param title: Post title
        :type title: str

        :param description: Post content
        :type description: str

        :return: handler for the post
        :rtype: :term:`BID`

        """
        return self._make_bid(
            utils.first_item(
                self.api_call(
                    self.OPS['PostCreate'],
                    variables={
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
        """Send a donation to the provided nonprofit

        :param target: Recipient of the donation
        :type target: :term:`BID`

        :param amount: Donation amount denominated in cents
        :type amount: int

        :param description: Donation description
        :type description: str

        :return: handler for the donation
        :rtype: :term:`BID`

        """
        return self._make_bid(
            utils.first_item(
                self.api_call(
                    self.OPS['DonationCreate'],
                    variables={
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
        """Send a transaction to the provided person

        :param target: Recipient of the transaction
        :type target: :term:`BID`

        :param amount: Transaction amount denominated in cents
        :type amount: int

        :param description: Transaction description
        :type description: str

        :return: handler for the transaction
        :rtype: :term:`BID`

        """
        return self._make_bid(
            utils.first_item(
                self.api_call(
                    self.OPS['TransactionCreate'],
                    variables={
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
        """Create a new comment replying to the provided entry

        :param parent: Entry to reply to
        :type target: :term:`BID`

        :param description: Comment contents
        :type description: str

        :return: handler for the comment
        :rtype: :term:`BID`

        """
        return self._make_bid(
            utils.first_item(
                self.api_call(
                    self.OPS['CommentCreate'],
                    variables={
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
        """Update the bot's description

        :param description: New biography contents
        :type description: str

        :return: Whether or not the operation was successful
        :rtype: bool

        """
        return 'errors' not in self.api_call(
            self.OPS['BioUpdate'],
            variables={
                'user': self._parse_bid(self.bid)['id'],
                'description': description,
            },
        )

    def create_like(self, target):
        """Like the provided entry. If the bot has already liked the entry,
        then there is no effect.

        :param target: Entry to unlike
        :type target: str

        :return: Whether or not the operation was successful
        :rtype: bool

        """
        return 'errors' not in self.api_call(
            self.OPS['LikeCreate'],
            variables={
                'user': self._parse_bid(self.bid)['id'],
                'target': self._parse_bid(target)['id'],
            },
        )

    def delete_like(self, target):
        """Unlike the provided entry. If the bot has not liked the entry,
        then there is no effect.

        :param target: Entry to like
        :type target: str

        :return: Whether or not the operation was successful
        :rtype: bool

        """
        return 'errors' not in self.api_call(
            self.OPS['LikeDelete'],
            variables={
                'user': self._parse_bid(self.bid)['id'],
                'target': self._parse_bid(target)['id'],
            },
        )

    def create_follow(self, target):
        """Follow the provided user. If the bot is currently following the
        user, then there is no effect.

        :param target: User to follow
        :type target: str

        :return: Whether or not the operation was successful
        :rtype: bool

        """
        return 'errors' not in self.api_call(
            self.OPS['FollowCreate'],
            variables={
                'user': self._parse_bid(self.bid)['id'],
                'target': self._parse_bid(target)['id'],
            },
        )

    def delete_follow(self, target):
        """Unfollow the provided user. If the bot is not currently following
        the user, then there is no effect.

        :param target: User to follow
        :type target: str

        :return: Whether or not the operation was successful
        :rtype: bool

        """
        return 'errors' not in self.api_call(
            self.OPS['FollowDelete'],
            variables={
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
                    variables={
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
                    variables={'id': self._parse_bid(bid)['id']},
                )),
            self.BID_CONF[bid_conf_key],
        )
