
# STANDARD_RIFT_IO_COPYRIGHT

import logging
import requests
import tornado
import tornado.escape

from .mgmt_session import (
   requests_exception_wrapper,
)

logger = logging.getLogger(__name__)


class BrocadeRestSession(object):
    '''Class representing a Brocade Rest Session'''
    DEFAULT_CONNECTION_TIMEOUT = 360
    DEFAULT_PORT = 443
    DEFAULT_USERNAME = 'vyatta'
    DEFAULT_PASSWORD = 'vyatta'
    OPERATION_TIMEOUT_SECS = 30

    REST_HEADERS = {
        'Content-Type: application/json',
        'Accept: application/json',
    }

    def __init__(self, 
            host='127.0.0.1',
            port=DEFAULT_PORT,
            username=DEFAULT_USERNAME,
            password=DEFAULT_PASSWORD):
        '''Initialize a new Restconf Session instance

        Arguments:
            host - host ip
            port - host port
            username - credentials for accessing the host, username
            password - credentials for accessing the host, password

        Returns:
            A newly initialized Restconf session instance
        '''
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.auth = (self.username, self.password)

        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.timeout = BrocadeRestSession.OPERATION_TIMEOUT_SECS
        self.session.headers = self.REST_HEADERS
        self.session.verify = False

    @requests_exception_wrapper
    def request_dhcp_server_info(self):
        """Trigger the http/https request

        Arguments:
            url (str): Url of the request

        Returns:
            request.Response
        """
        url = "http://" + self.host + "/rest/op" + "/show/dhcp/server/leases"
        response = self.session.post(url)
        #print('POST dhcp_info response headers ', response.headers)

        new_uri = response.headers['location']
        url = "http://" + self.host + "/" + new_uri
        response = self.session.get(url)
        #print('GET dhcp_info response text ', response.text)

        return response.text

    @requests_exception_wrapper
    def request_dns_nameserver_info(self):
        """Trigger the http/https request

        Arguments:
            url (str): Url of the request

        Returns:
            request.Response
        """
        url = "http://" + self.host + "/rest/op" + "/show/dns/forwarding/nameservers"
        response = self.session.post(url)
        #print('POST dns_info response headers ', response.headers)

        new_uri = response.headers['location']
        url = "http://" + self.host + "/" + new_uri
        response = self.session.get(url)
        #print('GET dns_info response text ', response.text)

        return response.text

    @requests_exception_wrapper
    def delete_vm_info(self, name):
        """Trigger the http/https request

        Arguments:
            url (str): Url of the request

        Returns:
            request.Response
        """
        url = "http://" + self.host + "/rest/conf"
        response = self.session.post(url)
        logger.debug('POST rest/conf response headers %s', response.headers)

        new_uri = response.headers['location']
        url = "http://" + self.host + "/" + new_uri + "/delete/virtualization/guest/" + name
        response = self.session.put(url)
        logger.debug('PUT delete vm %s response text %s', name, response.text)

        url = "http://" + self.host + "/" + new_uri + "/commit"
        response = self.session.post(url)
        logger.debug('POST commit vm to url %s response text %s', url, response.text)

        url = "http://" + self.host + "/" + new_uri
        response = self.session.delete(url)
        logger.debug('DELETE rest/conf response headers %s', response.headers)

        return response.text

    @requests_exception_wrapper
    def delete_vhost_intf(self, name):
        """Trigger the http/https request

        Arguments:
            url (str): Url of the request

        Returns:
            request.Response
        """
        url = "http://" + self.host + "/rest/conf"
        response = self.session.post(url)
        logger.debug('POST rest/conf response headers %s', response.headers)

        new_uri = response.headers['location']
        url = "http://" + self.host + "/" + new_uri + "/delete/interfaces/vhost/" + name
        response = self.session.put(url)
        logger.debug('PUT delete vhost %s response text %s', name, response.text)

        url = "http://" + self.host + "/" + new_uri + "/commit"
        response = self.session.post(url)
        logger.debug('POST commit vhost %s response text %s', name, response.text)

        url = "http://" + self.host + "/" + new_uri
        response = self.session.delete(url)
        logger.debug('DELETE rest/conf response headers %s', response.headers)

        return response.text

    @requests_exception_wrapper
    def delete_lo_intf(self, name):
        """Trigger the http/https request

        Arguments:
            url (str): Url of the request

        Returns:
            request.Response
        """
        url = "http://" + self.host + "/rest/conf"
        response = self.session.post(url)
        logger.debug('POST rest/conf response headers %s', response.headers)

        new_uri = response.headers['location']
        url = "http://" + self.host + "/" + new_uri + "/delete/interfaces/loopback/" + name
        response = self.session.put(url)
        logger.debug('PUT delete vhost %s response text %s', name, response.text)

        url = "http://" + self.host + "/" + new_uri + "/commit"
        response = self.session.post(url)
        logger.debug('POST commit vhost %s response text %s', name, response.text)

        url = "http://" + self.host + "/" + new_uri
        response = self.session.delete(url)
        logger.debug('DELETE rest/conf response headers %s', response.headers)

        return response.text

    @requests_exception_wrapper
    def delete_vlink(self, name):
        """Trigger the http/https request

        Arguments:
            url (str): Url of the request

        Returns:
            request.Response
        """
        url = "http://" + self.host + "/rest/conf"
        response = self.session.post(url)
        logger.debug('POST rest/conf response headers %s', response.headers)

        new_uri = response.headers['location']
        url = "http://" + self.host + "/" + new_uri + "/delete/service/dhcp-server/shared-network-name/" + name
        response = self.session.put(url)
        logger.debug('PUT delete vlink %s response text %s', name, response.text)

        url = "http://" + self.host + "/" + new_uri + "/commit"
        response = self.session.post(url)
        logger.debug('POST commit vlink %s response text %s', name, response.text)

        url = "http://" + self.host + "/" + new_uri
        response = self.session.delete(url)
        logger.debug('DELETE rest/conf response headers %s', response.headers)

        return response.text

    @requests_exception_wrapper
    def delete_dhcp_listener(self, name):
        """Trigger the http/https request

        Arguments:
            url (str): Url of the request

        Returns:
            request.Response
        """
        url = "http://" + self.host + "/rest/conf"
        response = self.session.post(url)
        logger.debug('POST rest/conf response headers %s', response.headers)

        new_uri = response.headers['location']
        # delete service dhcp-server listento interface 'dp0vhost9'
        url = "http://" + self.host + "/" + new_uri + "/delete/service/dhcp-server/listento/interface/" + name
        response = self.session.put(url)
        logger.debug('PUT delete dhcp listener %s response text %s', name, response.text)

        url = "http://" + self.host + "/" + new_uri + "/commit"
        response = self.session.post(url)
        logger.debug('POST commit dhcp listener %s response text %s', name, response.text)

        url = "http://" + self.host + "/" + new_uri
        response = self.session.delete(url)
        logger.debug('DELETE rest/conf response headers %s', response.headers)

        return response.text


    @requests_exception_wrapper
    def reset_dhcp_lease(self, mac):
        """Trigger the http/https request

        Arguments:
            url (str): Url of the request

        Returns:
            request.Response
        """
        # reset dhcp server lease mac 52:54:00:66:1a:9f 
        esc_mac = tornado.escape.url_escape(mac, plus=False)
        url = "http://" + self.host + "/rest/op" + "/reset/dhcp/server/lease/mac/" + esc_mac
        response = self.session.post(url)
        logger.debug("POST dhcp_info response headers %s", response.headers)

        new_uri = response.headers['location']
        url = "http://" + self.host + "/" + new_uri
        response = self.session.get(url)
        logger.debug("GET dhcp_info response text %s", response.text)

        return response.text


