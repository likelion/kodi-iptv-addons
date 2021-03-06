# coding=utf-8
#
#      Copyright (C) 2018 Dmitry Vinogradov
#      https://github.com/kodi-iptv-addons
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Library General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Library General Public License for more details.
#
# You should have received a copy of the GNU Library General Public
# License along with this library; if not, write to the
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA  02110-1301, USA.
#
import abc
import json
import os
import threading
import traceback
import urllib2
from Queue import Queue
from collections import OrderedDict
from threading import Event
from urllib import urlencode, addinfourl
from urllib2 import Request

import xbmc
from iptvlib import build_user_agent, log
from iptvlib.models import Group, Program, Channel


class ApiException(Exception):
    def __init__(self, message, code, origin_error=None):
        self.message = message
        self.code = code
        self.origin_error = origin_error

    def __repr__(self):
        return "ApiException: (%s) %s" % (self.code, self.message)


class HttpRequest(urllib2.Request):
    ident = None  # type: str
    method = None # type: str

    def __init__(self, ident=None, method=None, **kwargs):
        self.ident = ident
        self.method = method
        urllib2.Request.__init__(self, **kwargs)

    def get_method(self):
        return self.method or urllib2.Request.get_method(self)

class Api:
    __metaclass__ = abc.ABCMeta

    AUTH_STATUS_NONE = 0
    AUTH_STATUS_OK = 1
    AUTH_MAX_ATTEMPTS = 3

    E_UNKNOW_ERROR = 1000
    E_HTTP_REQUEST_FAILED = 1001
    E_JSON_DECODE = 1002
    E_AUTH_ERROR = 1003
    E_API_ERROR = 1004

    auth_status = AUTH_STATUS_NONE  # type: int
    username = None  # type: str
    password = None  # type: str
    working_path = None  # type: str
    cookie_file = None  # type: str
    settings_file = None  # type: str
    _attempt = 0  # type: int
    _groups = None  # type: OrderedDict[str, Group]
    _channels = None  # type: OrderedDict[str, Channel]
    _ident = None  # type: str

    def __init__(self, username=None, password=None, working_path="./"):
        self.auth_status = self.AUTH_STATUS_NONE
        self.username = self._ident = username
        self.password = password
        self.working_path = working_path
        if not os.path.exists(self.working_path):
            os.makedirs(self.working_path)
        self.cookie_file = os.path.join(self.working_path, "%s.cookie.txt" % self.__class__.__name__)
        self.settings_file = os.path.join(self.working_path, "%s.settings.txt" % self.__class__.__name__)
        self._groups = OrderedDict()
        self._channels = OrderedDict()

    @property
    def client_id(self):
        return "%s:%s" % (self.__class__.__name__, self._ident)

    @property
    def user_agent(self):
        # type: () -> str
        """
        User agent of HTTP client.
        :rtype: str
        """
        return build_user_agent()

    @property
    def groups(self):
        if len(self._groups) == 0:
            self._groups = self.get_groups()
            self._channels = OrderedDict()
            for group in self._groups.values():
                self._channels.update(group.channels)
        return self._groups

    @property
    def channels(self):
        if len(self._channels) == 0:
            len(self.groups)
        return self._channels

    @abc.abstractproperty
    def base_api_url(self):
        # type: () -> str
        """
        Base URL of API.
        :rtype: str
        """
        return ""

    @abc.abstractproperty
    def base_icon_url(self):
        # type: () -> str
        """
        Base URL of channel icons.
        :rtype: str
        """
        return ""

    @abc.abstractproperty
    def host(self):
        # type: () -> str
        """
        Api hostname.
        :rtype: str
        """
        return ""

    @abc.abstractproperty
    def diff_live_archive(self):
        # type: () -> int
        """
        Difference between live stream and archive stream in seconds.
        :rtype: int
        """
        return -1

    @abc.abstractproperty
    def archive_ttl(self):
        # type: () -> int
        """
        Time to live (ttl) of archive streams in seconds.
        :rtype: int
        """
        return -1

    @abc.abstractmethod
    def login(self):
        # type: () -> dict
        """Login to the IPTV service"""
        pass

    @abc.abstractmethod
    def is_login_request(self, uri, payload=None, method=None, headers=None):
        # type: (str, dict, str, dict) -> bool
        """
        Checks whether given URI is used for login
        :rtype: str
        """
        pass

    @abc.abstractmethod
    def get_groups(self):
        # type: () ->  OrderedDict[str, Group]
        """
        Returns the groups from the service
        :rtype: dict[str, Group]
        """
        pass

    @abc.abstractmethod
    def get_stream_url(self, cid, ut_start=None):
        # type: (str, int) -> str
        """
        Returns the stream URL for given channel id and timestamp
        :rtype: str
        """
        pass

    @abc.abstractmethod
    def get_epg(self, cid):
        # type: (str) -> dict[int, Program]
        """
        Returns the EPG for given channel id
        :rtype: dict[int, Program]
        """
        pass

    @abc.abstractmethod
    def get_cookie(self):
        # type: () -> str
        """
        Returns cookie
        :rtype: str
        """
        pass

    def read_cookie_file(self):
        # type: () -> str
        """
        Returns cookie stored in the cookie file
        :rtype: str
        """
        cookie = ""
        if os.path.isfile(self.cookie_file):
            with open(self.cookie_file, 'r') as fh:
                cookie = fh.read()
                fh.close()
        return cookie

    def write_cookie_file(self, data):
        # type: (str) -> None
        """
        Stores cookie to the cookie file
        :rtype: None
        """
        with open(self.cookie_file, 'w') as fh:
            fh.write(data)
            fh.close()

    def read_settings_file(self):
        # type: () -> dict
        """
        Returns settings stored in the settings file
        :rtype: dict
        """
        settings = None
        if os.path.isfile(self.settings_file):
            with open(self.settings_file, 'r') as fh:
                json_string = fh.read()
                fh.close()
                settings = json.loads(json_string)
        return settings

    def write_settings_file(self, data):
        # type: (dict) -> None
        """
        Stores settings to the settings file
        :rtype: None
        """
        with open(self.settings_file, 'w') as fh:
            fh.write(json.dumps(data))
            fh.close()

    def prepare_request(self, uri, payload=None, method="GET", headers=None, ident=None):
        # type: (str, dict, str, dict, str) -> HttpRequest
        url = self.base_api_url % uri if uri.startswith('http') is False else uri
        headers = headers or {}
        headers["User-Agent"] = self.user_agent
        headers["Connection"] = "Close"

        cookie = self.get_cookie()
        if cookie != "" and not self.is_login_request(uri, payload):
            headers["Cookie"] = cookie

        data = None
        if payload:
            if method == "POST":
                if "Content-Type" in headers and headers["Content-Type"] == "application/json":
                    data = json.dumps(payload)
                else:
                    data = urlencode(payload)
            elif method == "GET":
                url += "%s%s" % ("&" if "?" in url else "?", urlencode(payload))
        ident = ident or url
        return HttpRequest(ident=ident, method=method, url=url, headers=headers, data=data)

    def send_request(self, request):
        # type: (Request) -> dict|str
        json_data = ""
        try:
            response = urllib2.urlopen(request)  # type: addinfourl
            content_type = response.headers.getheader("content-type")  # type: str
            content = response.read()
            if not content_type.startswith("application/json"):
                return content
            response = json.loads(content)
        except urllib2.URLError, ex:
            log("Exception %s: message=%s" % (type(ex), ex.message))
            log(traceback.format_exc(), xbmc.LOGDEBUG)
            response = {
                "__error": {
                    "message": str(ex),
                    "code": self.E_HTTP_REQUEST_FAILED,
                    "details": {
                        "url": request.get_full_url(),
                        "data": request.get_data(),
                        "headers": request.headers
                    },
                }
            }
            pass
        except ValueError, ex:
            log("Exception %s: message=%s" % (type(ex), ex.message))
            log(traceback.format_exc(), xbmc.LOGDEBUG)
            response = {
                "__error": {
                    "message": "Unable decode server response: %s" % str(ex),
                    "code": self.E_JSON_DECODE,
                    "details": {
                        "response": json_data
                    }
                }
            }
            pass
        except Exception, ex:
            log("Exception %s: message=%s" % (type(ex), ex.message))
            log(traceback.format_exc(), xbmc.LOGDEBUG)
            response = {
                "__error": {
                    "message": "%s: %s" % (type(ex), str(ex)),
                    "code": self.E_UNKNOW_ERROR
                }
            }
            pass
        return response

    def make_request(self, uri, payload=None, method="GET", headers=None):
        # type: (str, dict, str, dict) -> dict
        """
        Makes HTTP request to the IPTV API
        :param uri: URL of the IPTV API
        :param payload: Payload data
        :param method: HTTP method
        :param headers: Additional HTTP headers
        :return:
        """
        if self.auth_status != self.AUTH_STATUS_OK and not self.is_login_request(uri, payload, method, headers):
            self.login()
            return self.make_request(uri, payload, method, headers)

        request = self.prepare_request(uri, payload, method, headers)
        response = self.send_request(request)

        if "__error" in response:
            if self.is_login_request(uri, payload):
                self.auth_status = self.AUTH_STATUS_NONE
                try:
                    os.remove(self.cookie_file)
                except OSError:
                    pass

        return response

    def do_send_request(self, queue, results, stop_event, wait=None):
        # type: (Queue, dict[str, dict], Event, float) -> None
        while not stop_event.is_set():
            request = queue.get()  # type: HttpRequest
            results[request.ident] = self.send_request(request)
            queue.task_done()
            stop_event.wait(wait)

    def send_parallel_requests(self, requests, wait=None, num_threads=None):
        # type: (list[HttpRequest], float, int) -> dict[str, dict]
        num_threads = len(requests) if num_threads is None else num_threads
        queue = Queue(num_threads * 2)
        results = dict()

        stop_event = threading.Event()
        for i in range(num_threads):
            thread = threading.Thread(target=self.do_send_request, args=(queue, results, stop_event, wait,))
            thread.setDaemon(True)
            thread.start()

        for req in requests:
            queue.put(req)
        queue.join()

        while queue.unfinished_tasks > 0:
            continue

        stop_event.set()

        return results

    @staticmethod
    def is_error_response(response):
        # type: (dict) -> (bool, dict or None)
        if "__error" in response:
            return True, response["__error"]
        return False, None
