#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Written by Michele Comitini <mcm@glisco.it>
License: LGPL v3

Adds support for  OAuth 2.0 authentication to web2py.

OAuth 2.0 Draft:  http://tools.ietf.org/html/draft-ietf-oauth-v2-10
"""

import time
import cgi
import urllib2

from urllib import urlencode
from gluon import current, redirect, HTTP

class OAuthAccount(object):
    """
    Login will be done via   OAuth Framework, instead of web2py's
    login form.

    You need to override the get_user method to match your auth provider needs.
    Example for facebook in your model (eg db.py)::
        # define the auth_table before call to auth.define_tables()
        auth_table = db.define_table(
           auth.settings.table_user_name,
           Field('first_name', length=128, default=""),
           Field('last_name', length=128, default=""),
           Field('username', length=128, default="", unique=True),
           Field('password', 'password', length=256,
           readable=False, label='Password'),
           Field('registration_key', length=128, default= "",
           writable=False, readable=False))

        auth_table.username.requires = IS_NOT_IN_DB(db, auth_table.username)
        auth.define_tables()

        CLIENT_ID=\"<put your fb application id here>\"
        CLIENT_SECRET=\"<put your fb application secret here>\"
        AUTH_URL="http://..."
        TOKEN_URL="http://..."
        # remember to download and install facebook GraphAPI module in your app
        from facebook import GraphAPI, GraphAPIError
        from gluon.contrib.login_methods.oauth20_account import OAuthAccount
        class FaceBookAccount(OAuthAccount):
            '''OAuth impl for FaceBook'''
            AUTH_URL="https://graph.facebook.com/oauth/authorize"
            TOKEN_URL="https://graph.facebook.com/oauth/access_token"

            def __init__(self, g):
               OAuthAccount.__init__(self, g, CLIENT_ID, CLIENT_SECRET,
                                     self.AUTH_URL, self.TOKEN_URL,
                                     scope='user_photos,friends_photos')
               self.graph = None

            def get_user(self):
               '''
                Returns the user using the Graph API.
               '''

               if not self.accessToken():
                  return None
       
               if not self.graph:
                  self.graph = GraphAPI((self.accessToken()))

               user = None
               try:
                   user = self.graph.get_object("me")
               except GraphAPIError, e:
                   self.session.token = None
                   self.graph = None


               if user:
                   return dict(first_name = user['first_name'],
                               last_name = user['last_name'],
                               username = user['id'])



Any optional arg in the constructor will be passed asis to remote
server for requests.  It can be used for the optional"scope" parameters for Facebook.

    """
    def __redirect_uri(self, next=None):
        """
        Build the uri used by the authenticating server to redirect
        the client back to the page originating the auth request.
        Appends the _next action to the generated url so the flows continues.
        """

        r = current.request
        http_host=r.env.http_x_forwarded_for
        if not http_host: http_host=r.env.http_host

        url_scheme = r.env.wsgi_url_scheme
        if next:
            path_info = next
        else:
            path_info = r.env.path_info
        uri = '%s://%s%s' %(url_scheme, http_host, path_info)
        if r.get_vars and not next:
            uri += '?' + urlencode(r.get_vars)
        return uri


    def __build_url_opener(self, uri):
        """
        Build the url opener for managing HTTP Basic Athentication
        """
        # Create an OpenerDirector with support 
        # for Basic HTTP Authentication...

        auth_handler = urllib2.HTTPBasicAuthHandler()
        auth_handler.add_password(None,
                                  uri,
                                  self.client_id,
                                  self.client_secret)
        opener = urllib2.build_opener(auth_handler)
        return opener


    def accessToken(self):
        """
        Return the access token generated by the authenticating server.

        If token is already in the session that one will be used.
        Otherwise the token is fetched from the auth server.

        """
        if current.session.token and current.session.token.has_key('expires'):
            expires = current.session.token['expires']
            # reuse token until expiration
            if expires == 0 or expires > time.time():
                        return current.session.token['access_token']
        if current.session.code:
            data = dict(client_id=self.client_id,
                        client_secret=self.client_secret,
                        redirect_uri=current.session.redirect_uri,
                        response_type='token', code=current.session.code)


            if self.args:
                data.update(self.args)
            open_url = None
            opener = self.__build_url_opener(self.token_url)
            try:
                open_url = opener.open(self.token_url, urlencode(data))
            except urllib2.HTTPError, e:
                raise Exception(e.read())
            finally:
                del current.session.code # throw it away

            if open_url:
                try:
                    tokendata = cgi.parse_qs(open_url.read())
                    current.session.token = \
                        dict([(k,v[-1]) for k,v in tokendata.items()])
                    # set expiration absolute time try to avoid broken
                    # implementations where "expires_in" becomes "expires"
                    if current.session.token.has_key('expires_in'):
                        exps = 'expires_in'
                    else:
                        exps = 'expires'                    
                    current.session.token['expires'] = \
                        int(current.session.token[exps]) + \
                        time.time()
                finally:
                    opener.close()
                return current.session.token['access_token']

        current.session.token = None
        return None

    def __init__(self, g, 
                 client_id, client_secret, auth_url, token_url, **args):
        """
        first argument is unused. Here only for legacy reasons.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_url = auth_url
        self.token_url = token_url
        self.args = args

    def login_url(self, next="/"):
        self.__oauth_login(next)
        return next

    def logout_url(self, next="/"):
        del current.session.token
        return next

    def get_user(self):
        """
        Override this method by sublcassing the class.
        
        """
        raise NotImplementedError, "Must override get_user()"

        # Following code is never executed.  It can be used as example
        # for overriding in subclasses.
        if not self.accessToken():
            return None

        if not self.graph:
            self.graph = GraphAPI((self.accessToken()))

        user = None
        try:
            user = self.graph.get_object("me")
        except GraphAPIError:
            current.session.token = None
            self.graph = None

        if user:
            return dict(first_name = user['first_name'],
                        last_name = user['last_name'],
                        username = user['id'])


    def __oauth_login(self, next):
        """
        This method redirects the user to the authenticating form
        on authentication server if the authentication code
        and the authentication token are not available to the
        application yet.

        Once the authentication code has been received this method is
        called to set the access token into the session by calling
        accessToken()
        """

        if not self.accessToken():
            if not current.request.vars.code:
                current.session.redirect_uri=self.__redirect_uri(next)
                data = dict(redirect_uri=current.session.redirect_uri,
                                  response_type='code',
                                  client_id=self.client_id)
                if self.args:
                    data.update(self.args)
                auth_request_url = self.auth_url + "?" +urlencode(data)
                raise HTTP(307,
                           "You are not authenticated: you are being redirected to the <a href='" + auth_request_url + "'> authentication server</a>",
                           Location=auth_request_url)
            else:
                current.session.code = current.request.vars.code
                self.accessToken()
                return current.session.code
        return None

