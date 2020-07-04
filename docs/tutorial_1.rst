.. _tutorial_1:

========================
Tutorial 1: Hello, World
========================

This document walks through the minimal steps to deploy a bot to a Token Ibis endpoint of your choice.
By the end of the tutorial, you (a human user) should be able to interact with an instance of a "Hello World" bot.

Endpoint connection
-------------------

The first step is to obtain login information from a Token Ibis app administrator.
If this is your time using ibots, you will probably want to play around with a local endpoint.

Option 1: Set up local endpoint
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

#. Follow the instructions to install `VirtualBox <https://www.virtualbox.org/wiki/Downloads>`_.

#. Download the latest Token Ibis development image from here <insert AWS s3 link>

#. Open the image using Virtualbox (may need to include a screenshot or something)

#. Obtain the ip address of the machine

   .. code-block:: console

       $ ibots-get-ip

#. Get the initial list of available usernames and passwords

   .. code-block:: console

       $ ibots-show-accounts

The endpoint that you will use for step <Basic Configuration> is ``http://<ip address>:3000``.
You can use any of the "ibot" username/password pairs for your ibot and use any of the "human" username/password pairs to login in at ``http://<ip address>:3000/_password_login`` to interact with the app as a normal user.

Option 2: Obtain public endpoint account
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Alternatively (or once you are satisfied with your local ibot development), you can obtain a username and password from the administrator of a public Token Ibis endpoint.
Email info@tokenibis.org for more information.

Hello, world!
-------------

It's now time to make your first ibot.
Copy the following piece of code into a file called ``hello_bot.py`` in your working directory.

.. literalinclude:: ../ibots/bots/hello_bot.py

Basic configuration
-------------------

Next, you need to tell the ibots SDK where to find your "Hello World" bot.
Copy the following JSON text into a file called ``config.json``

.. code-block:: json

    {
	"global": {
	    "endpoint": "<server endpoint>"
	},
	"resources": {},
	"bots": {
	    "<bot username>": {
		"password": "<bot password>",
		"class": "hello_bot.HelloWorldBot",
		"resources": {},
		"args": {}
	    }
	}
    }

Remember to substitute in the correct server endpoint (e.g. ``http://192.168.1.1:3000``) and ibot username and password.

Basic deployment
----------------

Now, all that's left to do is to deploy the ibot.
To set up the local ibots server, run this command in the terminal:

.. code-block:: console
    
    $ python -m ibots.server -c config.json

Now, let's check on the status of the ibot using the command line client from a different terminal.

.. code-block:: console
    
    $ python -m ibots.client status

If the bot is running, then you can now login as a user to see the "Hello World" bot's first post.
Try commenting and see if it says hi!

Next Steps
----------

In :ref:`tutorial_2`, we will use a slightly more complicated bot to explain some of the key features of the ibots SDK in more detail.
Alternatively, you can skip ahead to :ref:`development_guide` and :ref:`deployment_guide` if you prefer to read the documentation in its entirety.
