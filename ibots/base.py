import os
import json
import IPython
import logging
import requests

from abc import ABC, abstractmethod
from datetime import timedelta
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport
from ibots import utils

DIR = os.path.dirname(os.path.realpath(__file__))

OPS = {
    utils.snake_case(x.rsplit('.', 1)[0]): open(
        os.path.join(
            DIR,
            'graphql',
            'bot',
            x,
        )).read()
    for x in os.listdir(os.path.join(DIR, 'graphql', 'bot'))
}


class AuthenticateBotException(Exception):
    pass


class StopBotException(Exception):
    pass


class AbstractBot(ABC):
    """Say something about the fact that it uses

    :ivar logger: (:class:`logging.Logger`) -- ibot-specific logger

    """

    def __init__(self, endpoint, username, password, waiter):

        self.logger = logging.getLogger('BOT_{}'.format(
            self.__class__.__name__.upper()))
        self._endpoint = endpoint
        self._waiter = waiter
        self._stop = False
        self._interact = False

        login_response = requests.post(
            'https://{}/ibis/login-pass/'.format(self._endpoint),
            data={
                'username': username,
                'password': password
            })

        self.id = login_response.json()['user_id']
        if not self.id:
            self.logger.error('Failed to log in')
            raise AuthenticateBotException

        self._client = Client(
            transport=RequestsHTTPTransport(
                url='https://{}/graphql/'.format(self._endpoint),
                cookies=login_response.cookies))

    def api_call(self, operation, variables=None):
        """Execute the gql query and variables on the remote endpoint.

        :param operation: GraphQL query to execute
        :type operation: str

        :param variables: GraphQL variable key/value pairs
        :type variables: dict, optional

        :return: JSON object returned by the remote endpoint call.
        :rtype: JSON object

        """

        parsed = gql(operation)

        assert len(parsed.definitions) == 1
        if variables:
            for x in variables:
                if x not in set(
                        utils.snake_case(y.variable.name.value)
                        for y in parsed.definitions[0].variable_definitions):
                    self.logger.error(
                        'Variable "{}" not supported in {}'.format(
                            x, operation))
                    raise StopBotException

        return self._client.execute(
            parsed,
            variable_values={
                utils.mixed_case(x): variables[x]
                for x in variables
            },
        )

    def api_wait(self, timeout=None, exit_any=False):
        """Wait until something happens at the remote endpoint.
        While waiting, the controller may interrupt to safely stop or
        interact with the bot.

        :param timeout: Number of seconds to timeout if nothing happens
        :type timeout: int, optional

        :param mine: Only wait for my notifications
        :type mine: bool, optional

        """
        start = utils.localtime()
        result, event = self._waiter.wait(timeout=1)

        while not result:
            # received signal from server to stop the bot
            if self._stop:
                raise StopBotException
            # received signal from server to enter interactive mode
            if self._interact:
                IPython.embed()
                self._interact = False

            result, event = self._waiter.wait(event_last=event, timeout=1)

            # break because *something* happened and exit_any=True
            if result and exit_any:
                break

            # break because our bot got a notification
            if result and self.api_call(
                    OPS['__notifier'],
                    variables={'id': self.id},
            )['notifier']['unseenCount']:
                self.api_call(
                    OPS['__notifier_update'],
                    variables={
                        'id': self.id,
                        'last_seen': str(utils.localtime()),
                    },
                )
                break

            # break if timeout
            if timeout and utils.localtime() - start < timedelta(
                    seconds=timeout):
                break

            result = False
            event = None

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
            '''.format(id=self.id)))
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


class AbstractBasicBot(AbstractBot):
    """Say something about the fact that it uses

    """

    FIRST = 25

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.refresh_node()

    def load_gql(func):
        def wrapper(*args, **kwargs):
            def empty():
                """Docstring"""
                pass

            assert func.__code__.co_code == empty.__code__.co_code

            # TODO: add assertions for proper function documentation

            if func.__name__.split('_')[-1] == 'create':
                args[0].logger.info('Calling "{}"'.format(func.__name__))
            else:
                args[0].logger.debug('Calling "{}"'.format(func.__name__))
            args[0].logger.debug('Variables: {}'.format(
                json.dumps(kwargs, indent=2)))

            result = AbstractBasicBot._collapse_connections(
                getattr(
                    AbstractBasicBot,
                    '_' + func.__name__.split('_')[-1],
                )(*args, OPS[func.__name__], **kwargs))

            args[0].logger.debug('Result: {}'.format(
                json.dumps(result, indent=2)))

            return result

        return wrapper

    @load_gql
    def organizaton_list(self, **kwargs):
        """Retrieve a list of recently joined organizations.

        :param search: Query only organizations whose username or full name
           contains this substring
        :type search: str, optional

        :param followed_by: Query only organizations who are followed by this
            user
        :type followed_by: :term:`ID`, optional

        :param followed_of: Query only organizations who follow this user
        :type followed_of: :term:`ID`, optional

        :param like_for: Query only organizations who liked this entry
        :type like_for: :term:`ID`, optional

        :param rsvp_for: Query only organizations who rsvp'd for this event
        :type rsvp_for: :term:`ID`, optional

        :param order_by: Specify query order; see schema at
            ``https://<endpoint>/graphql`` for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the organization
            * :attr:`username` (*str*) -- organization's on-app username
            * :attr:`full_name` (*str*) -- organization name
            * :attr:`first_name` (*str*) -- blank (included for consistency)

        """
        pass

    @load_gql
    def person_list(self, **kwargs):
        """Retrieve a list of recently joined people.

        :param search: Query only people whose username or full name
           contains this substring
        :type search: str, optional

        :param followed_by: Query only people who are followed by this
            user
        :type followed_by: :term:`ID`, optional

        :param followed_of: Query only people who follow this user
        :type followed_of: :term:`ID`, optional

        :param like_for: Query only people who liked this entry
        :type like_for: :term:`ID`, optional

        :param rsvp_for: Query only people who rsvp'd for this event
        :type rsvp_for: :term:`ID`, optional

        :param order_by: Specify query order; see schema at
            ``https://<endpoint>/graphql`` for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the person
            * :attr:`username` (*str*) -- person's on-app username
            * :attr:`full_name` (*str*) -- person's full name
            * :attr:`first_name` (*str*) -- person's first name

        """
        pass

    @load_gql
    def bot_list(self, **kwargs):
        """Retrieve a list of recently joined bots.

        :param search: Query only bots whose username or full name
           contains this substring
        :type search: str, optional

        :param followed_by: Query only bots who are followed by this
            user
        :type followed_by: :term:`ID`, optional

        :param followed_of: Query only bots who follow this user
        :type followed_of: :term:`ID`, optional

        :param like_for: Query only bots who liked this entry
        :type like_for: :term:`ID`, optional

        :param rsvp_for: Query only bots who rsvp'd for this event
        :type rsvp_for: :term:`ID`, optional

        :param order_by: Specify query order; see schema at
            ``https://<endpoint>/graphql`` for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the bot
            * :attr:`username` (*str*) -- bot's on-app username
            * :attr:`full_name` (*str*) -- bot's full name
            * :attr:`first_name` (*str*) -- bot's first name

        """
        pass

    @load_gql
    def donation_list(self, **kwargs):
        """Retrieve a list of recently made donations.

        :param search: Query only donations with a description, usernames, or
            user full names that contains this substring
        :type search: str, optional

        :param by_user: Query only donations made or received by this user
        :type by_user: :term:`ID`, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the donation
            * :attr:`user` (:term:`ID`) -- handler for the donation sender
            * :attr:`target` (:term:`ID`) -- handler for the donation
              recipient
            * :attr:`amount` (*int*) -- donation amount in cents
            * :attr:`description` (*str*) -- donation description
            * :attr:`created` (*str*) -- datetime the donation was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the donation

        """
        pass

    @load_gql
    def reward_list(self, **kwargs):
        """Retrieve a list of recently made rewards.

        :param search: Query only rewards with a description,
            usernames, or user full names that contains this substring
        :type search: str, optional

        :param by_user: Query only rewards made or received by this user
        :type by_user: :term:`ID`, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the reward
            * :attr:`user` (:term:`ID`) -- handler for the reward sender
            * :attr:`target` (:term:`ID`) -- handler for the
              reward recipient
            * :attr:`amount` (*int*) -- reward amount in cents
            * :attr:`description` (*str*) -- reward description
            * :attr:`created` (*str*) -- datetime the reward was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the reward

        """
        pass

    @load_gql
    def news_list(self, **kwargs):
        """Retrieve a list of recently made news articles.

        :param search: Query only news articles with a organization
            username or full name, title, or content that contains
            this substring,
        :type search: str, optional

        :param by_user: Query only news articles posted by this organization
        :type by_user: :term:`ID`, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the reward
            * :attr:`user` (:term:`ID`) -- handler for the associated
              organization
            * :attr:`title` (*str*) -- title of the news article
            * :attr:`description` (*str*) -- news article content
            * :attr:`created` (*str*) -- datetime the news article was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the news article

        """
        pass

    @load_gql
    def event_list(self, **kwargs):
        """Retrieve a list of recently made events.

        :param search: Query only events with a organization
            username or full name, title, or content that contains
            this substring,
        :type search: str, optional

        :param by_user: Query only events planned by this organization
        :type by_user: :term:`ID`, optional

        :param rsvp_by: Query only events rsvp'd by this user
        :type rsvp_by: :term:`ID`, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the reward
            * :attr:`user` (:term:`ID`) -- handler for the associated
              organization
            * :attr:`title` (*str*) -- title of the event
            * :attr:`description` (*str*) -- event content
            * :attr:`created` (*str*) -- datetime the event was created
            * :attr:`like_count` (*int*) -- number of users who have
            * :attr:`date` (*str*) -- datetime the event is scheduled for
            * :attr:`duration` (*int*) -- time in minutes the event will take
            * :attr:`address` (*str*) -- physical location of the event
              liked the event

        """
        pass

    @load_gql
    def post_list(self, **kwargs):
        """Retrieve a list of recently made posts.

        :param search: Query only posts with a person's
            username or full name, title, or content that contains
            this substring,
        :type search: str, optional

        :param by_user: Query only posts posted by this person
        :type by_user: :term:`ID`, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the reward
            * :attr:`user` (:term:`ID`) -- handler for the associated person
            * :attr:`title` (*str*) -- title of the post
            * :attr:`description` (*str*) -- post content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        pass

    @load_gql
    def activity_list(self, **kwargs):
        """Retrieve a list of recently made activitys.

        :param search: Query only activitys with a person's
            username or full name, title, or content that contains
            this substring,
        :type search: str, optional

        :param by_user: Query only activitys activityed by this person
        :type by_user: :term:`ID`, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the reward
            * :attr:`user` (:term:`ID`) -- handler for the associated person
            * :attr:`title` (*str*) -- title of the activity
            * :attr:`description` (*str*) -- activity content
            * :attr:`created` (*str*) -- datetime the activity was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the activity

        """
        pass

    @load_gql
    def comment_list(self, **kwargs):
        """Retrieve a list of recently made comments. Since parsing comment
        trees can be tedious, :class:`AbstractBasicBot` provides the
        higher-level methods :func:`comment_chain` and
        :func:`comment_tree` methods.

        :param has_parent: Query only comments that are replying to this entry
        :type has_parent: :term:`ID`, optional

        :param search: Query only posts with a person's
            username or full name, title, or content that contains
            this substring,
        :type search: str, optional

        :param order_by: Specify query order; see schema at
            https://<endpoint>/graphql for all options.
        :type order_by: str, optional

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the comment
            * :attr:`user` (:term:`ID`) -- handler for the commenting user
            * :attr:`parent` (:term:`ID`) -- handler for entry the
              comment is responding to
            * :attr:`description` (*str*) -- comment content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        pass

    @load_gql
    def notification_list(self, **kwargs):
        """Retrieve information for a single provided news article.

        :param for_user: Query only notifications for this user
        :type for_user: :term:`ID`, optional

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the notification
            * :attr:`category` (*str*) -- type of notification
            * :attr:`clicked` (*bool*) -- whether the notification has
              been clicked
            * :attr:`reference` (*str*) -- page redirect of notification
            * :attr:`created` (*str*) -- datetime the notification was created

        """
        pass

    @load_gql
    def organization_node(self, **kwargs):
        """Retrieve information for a single provided organization.

        :param id: Organization to query
        :type id: :term:`ID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the organization
            * :attr:`username` (*str*) -- organization's on-app username
            * :attr:`full_name` (*str*) -- organization name
            * :attr:`first_name` (*str*) -- blank (included for consistency)

        """
        pass

    @load_gql
    def person_node(self, **kwargs):
        """Retrieve information for a single provided person.

        :param id: Person to query
        :type id: :term:`ID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the person
            * :attr:`username` (*str*) -- person's on-app username
            * :attr:`full_name` (*str*) -- person's full name
            * :attr:`first_name` (*str*) -- person's first name

        """
        pass

    @load_gql
    def bot_node(self, **kwargs):
        """Retrieve information for a single provided person.

        :param id: Person to query
        :type id: :term:`ID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the person
            * :attr:`username` (*str*) -- person's on-app username
            * :attr:`full_name` (*str*) -- person's full name
            * :attr:`first_name` (*str*) -- person's first name

        """
        pass

    @load_gql
    def donation_node(self, **kwargs):
        """Retrieve information for a single provided donation.

        :param id: Donation to query
        :type id: :term:`ID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the donation
            * :attr:`user` (:term:`ID`) -- handler for the donation sender
            * :attr:`target` (:term:`ID`) -- handler for the donation
              recipient
            * :attr:`amount` (*int*) -- donation amount in cents
            * :attr:`description` (*str*) -- donation description
            * :attr:`created` (*str*) -- datetime the donation was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the donation

        """
        pass

    @load_gql
    def reward_node(self, **kwargs):
        """Retrieve information for a single provided reward.

        :param id: Reward to query
        :type id: :term:`ID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the reward
            * :attr:`user` (:term:`ID`) -- handler for the reward sender
            * :attr:`target` (:term:`ID`) -- handler for the
              reward recipient
            * :attr:`amount` (*int*) -- reward amount in cents
            * :attr:`description` (*str*) -- reward description
            * :attr:`created` (*str*) -- datetime the reward was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the reward

        """
        pass

    @load_gql
    def news_node(self, **kwargs):
        """Retrieve information for a single provided news article.

        :param id: News article to query
        :type id: :term:`ID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the reward
            * :attr:`user` (:term:`ID`) -- handler for the associated
              organization
            * :attr:`title` (*str*) -- title of the news article
            * :attr:`description` (*str*) -- news article content
            * :attr:`created` (*str*) -- datetime the news article was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the news article

        """
        pass

    @load_gql
    def event_node(self, **kwargs):
        """Retrieve information for a single provided event.

        :param id: Event to query
        :type id: :term:`ID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the reward
            * :attr:`user` (:term:`ID`) -- handler for the associated
              organization
            * :attr:`title` (*str*) -- title of the event
            * :attr:`description` (*str*) -- event content
            * :attr:`created` (*str*) -- datetime the event was created
            * :attr:`like_count` (*int*) -- number of users who have
            * :attr:`date` (*str*) -- datetime the event is scheduled for
            * :attr:`duration` (*int*) -- time in minutes the event will take
            * :attr:`address` (*str*) -- physical location of the event
              liked the event

        """
        pass

    @load_gql
    def post_node(self, **kwargs):
        """Retrieve information for a single provided post.

        :param id: Post to query
        :type id: :term:`ID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the reward
            * :attr:`user` (:term:`ID`) -- handler for the associated person
            * :attr:`title` (*str*) -- title of the post
            * :attr:`description` (*str*) -- post content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        pass

    @load_gql
    def activity_node(self, **kwargs):
        """Retrieve information for a single provided activity.

        :param id: Activity to query
        :type id: :term:`ID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the reward
            * :attr:`user` (:term:`ID`) -- handler for the associated person
            * :attr:`title` (*str*) -- title of the activity
            * :attr:`description` (*str*) -- activity content
            * :attr:`created` (*str*) -- datetime the activity was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the activity

        """
        pass

    @load_gql
    def comment_node(self, **kwargs):
        """Retrieve information for a single provided comment.

        :param id: Comment to query
        :type id: :term:`ID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the comment
            * :attr:`user` (:term:`ID`) -- handler for the commenting user
            * :attr:`parent` (:term:`ID`) -- handler for entry the
              comment is responding to
            * :attr:`description` (*str*) -- comment content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        pass

    @load_gql
    def notification_node(self, **kwargs):
        """Retrieve information for a single provided news article.

        :param id: Notification node to query
        :type id: :term:`ID`

        :return: Dictionary with the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the reward
            * :attr:`category` (*str*) -- type of notification
            * :attr:`clicked` (*bool*) -- whether the notification has
              been clicked
            * :attr:`reference` (*str*) -- page redirect of notification
            * :attr:`created` (*str*) -- datetime the notification was created

        """
        pass

    @load_gql
    def activity_create(self, **kwargs):
        """Create a new activity

        :param title: Activity title
        :type title: str

        :param description: Activity content
        :type description: str

        :return: handler for the activity
        :rtype: :term:`ID`

        """
        pass

    @load_gql
    def reward_create(self, **kwargs):
        """Send a reward to the provided person

        :param target: Recipient of the reward
        :type target: :term:`ID`

        :param amount: Reward amount denominated in cents
        :type amount: int

        :param description: Reward description
        :type description: str

        :return: handler for the reward
        :rtype: :term:`ID`

        """
        pass

    @load_gql
    def comment_create(self, **kwargs):
        """Create a new comment replying to the provided entry

        :param parent: Entry to reply to
        :type target: :term:`ID`

        :param description: Comment contents
        :type description: str

        :return: handler for the comment
        :rtype: :term:`ID`

        """
        pass

    @load_gql
    def bot_update(self, **kwargs):
        """Update the bot's description

        :param description: New biography contents
        :type description: str

        :return: Whether or not the operation was successful
        :rtype: bool

        """
        pass

    @load_gql
    def activity_update(self, **kwargs):
        """Update a new activity

        :param title: Activity title
        :type title: str

        :param description: Activity content
        :type description: str

        :param active: Whether or not the activity is currently active
        :type active: str

        :param reward_min: Minimum reward
        :type active: str

        :param reward_range: Maximum reward minus minimum reward
        :type active: str

        :param scratch: Activity scratch data that won't get displayed
        :type scratch: str

        :return: handler for the activity
        :rtype: :term:`ID`

        """
        pass

    @load_gql
    def like_create(self, **kwargs):
        """Like the provided entry. If the bot has already liked the entry,
        then there is no effect.

        :param target: Entry to unlike
        :type target: str

        :return: Whether or not the operation was successful
        :rtype: bool

        """
        pass

    @load_gql
    def like_delete(self, **kwargs):
        """Unlike the provided entry. If the bot has not liked the entry,
        then there is no effect.

        :param target: Entry to like
        :type target: str

        :return: Whether or not the operation was successful
        :rtype: bool

        """
        pass

    @load_gql
    def follow_create(self, **kwargs):
        """Follow the provided user. If the bot is currently following the
        user, then there is no effect.

        :param target: User to follow
        :type target: str

        :return: Whether or not the operation was successful
        :rtype: bool

        """
        pass

    @load_gql
    def follow_delete(self, **kwargs):
        """Unfollow the provided user. If the bot is not currently following
        the user, then there is no effect.

        :param target: User to follow
        :type target: str

        :return: Whether or not the operation was successful
        :rtype: bool

        """
        pass

    def refresh_node(self):
        self.node = self.bot_node(id=self.id)

    def comment_chain(self, id):
        """Retrieve the entire chain of comments and root :term:`entry` that
        the provided comment is responding to.

        :param id: Starting comment
        :type id: :term:`ID`

        :return: List of dictionaries each with the following
            key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the comment
            * :attr:`user` (:term:`ID`) -- handler for the commenting user
            * :attr:`parent` (:term:`ID`) -- handler for entry the
              comment is responding to
            * :attr:`description` (*str*) -- comment content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        comment = self.comment(id)
        return (self.comment_chain(comment['parent'])
                if comment['parent'].type == 'comment' else [
                    getattr(self, '{}'.format(comment['parent'].type))(
                        comment['parent'])
                ]) + [comment]

    def comment_tree(self, root):
        """Retrieve the entire conversation tree of comments stemming from the
        provided entry.

        :param id: Starting comment
        :type id: :term:`ID`

        :return: Recursive list of dictionaries with the keys/value pairs:

            * :attr:`comment` (*dict*) -- dictionary containing the
              comment information (see below).
            * :attr:`replies` (*list*) -- list of dictionaries
              containing this same dicionary key/value pair format.

          Each :attr:`comment` dictionary of the structure above
          contains the following key/value pairs:

            * :attr:`id` (:term:`ID`) -- handler for the comment
            * :attr:`user` (:term:`ID`) -- handler for the commenting user
            * :attr:`parent` (:term:`ID`) -- handler for entry the
              comment is responding to
            * :attr:`description` (*str*) -- comment content
            * :attr:`created` (*str*) -- datetime the post was created
            * :attr:`like_count` (*int*) -- number of users who have
              liked the post

        """
        return [{
            y: z
            for y, z in list(x.items()) +
            [['replies_', self.comment_tree(root=x['id'])]]
        } for x in self.comment_list(parent=root)]

    def get_app_link(self, id):
        """Get an app link to the user or app based on the id"""
        return requests.get('https://{}/notifications/app_link/{}'.format(
            self._endpoint, id)).content.decode()

    def _node(self, op, **kwargs):
        return self.api_call(op, kwargs)

    def _list(self, op, **kwargs):
        if 'first' not in kwargs:
            kwargs['first'] = self.FIRST

        return self.api_call(op, kwargs)

    def _create(self, op, **kwargs):
        assert 'user' not in kwargs
        kwargs['user'] = self.id
        return utils.first_item(self.api_call(op, kwargs))

    def _update(self, op, **kwargs):
        assert 'id' in kwargs
        assert 'user' not in kwargs
        return utils.first_item(self.api_call(op, kwargs))

    def _delete(self, op, **kwargs):
        assert 'user' not in kwargs
        kwargs['user'] = self.id
        return utils.first_item(self.api_call(op, kwargs))

    @staticmethod
    def _collapse_connections(result):
        """Accept a GraphQL JSON object result and collapse all edge/nodes
        connections into Python lists

        :param obj: GraphQL result
        :type obj: dict

        :return: Copy of result
        :rtype: dict

        """
        assert len(result) == 1

        def _recurse(obj):
            if type(obj) == list:
                return [_recurse(x) for x in obj]
            elif type(obj) == dict:
                if 'edges' in obj:
                    return _recurse(obj['edges'])
                if 'node' in obj:
                    return _recurse(obj['node'])
                else:
                    return {utils.snake_case(x): _recurse(obj[x]) for x in obj}
            else:
                return obj

        return utils.first_item(_recurse(result))
