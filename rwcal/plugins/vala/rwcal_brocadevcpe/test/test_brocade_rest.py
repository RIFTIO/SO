#!/usr/bin/python

import requests
import logging
import tornado
import tornado.escape

host = "10.66.4.26"
username = "vyatta"
password = "vyatta"

logger = logging.getLogger('BrocadeRestTest')

REST_HEADERS = {
          'Content-Type: application/json',
          'Accept: application/json',
}

auth = (username, password)
  
session = requests.Session()
session.auth = auth
session.timeout = 30
session.headers = REST_HEADERS
session.verify = False

logging.basicConfig(level=logging.DEBUG)

def delete_vm_info(session, name):
          """Trigger the http/https request
  
          Arguments:
              url (str): Url of the request
  
          Returns:
              request.Response
          """
          url = "http://" + host + "/rest/conf"
          response = session.post(url)
          print('POST rest/conf response headers ', response.headers)
  
          new_uri = response.headers['location']
          url = "http://" + host + "/" + new_uri + "/delete/virtualization/guest/" + name
          response = session.put(url)
          print('PUT delete vm response text ', response.text)
  
          url = "http://" + host + "/" + new_uri + "/commit"
          print('POST to url ', url)
          response = session.post(url)
          print('POST commit vm response text ', response.text)
  
          url = "http://" + host + "/" + new_uri
          response = session.delete(url)
          print('DELETE rest/conf response headers ', response.headers)
  
          return response.text


def delete_vlink(session, name):
        """Trigger the http/https request

        Arguments:
            url (str): Url of the request

        Returns:
            request.Response
        """
        url = "http://" + host + "/rest/conf"
        response = session.post(url)
        logger.debug('POST rest/conf response headers %s', response.headers)

        new_uri = response.headers['location']
        url = "http://" + host + "/" + new_uri + "/delete/service/dhcp-server/shared-network-name/" + name
        response = session.put(url)
        logger.debug('PUT delete vlink %s response text %s', name, response.text)

        url = "http://" + host + "/" + new_uri + "/commit"
        response = session.post(url)
        logger.debug('POST commit vlink %s response text %s', name, response.text)

        url = "http://" + host + "/" + new_uri
        response = session.delete(url)
        logger.debug('DELETE rest/conf response headers %s', response.headers)

        return response.text


name = "Test1__vnfd-1__1__abd6831e-f811-4580-9aad-1de9c6424180"
#delete_vm_info(session, name)
name = "rift.cal.virtual_link"
#delete_vlink(session, name)

def reset_dhcp_lease(mac):
        """Trigger the http/https request

        Arguments:
            url (str): Url of the request

        Returns:
            request.Response
        """
        # reset dhcp server lease mac 52:54:00:66:1a:9f 
        esc_mac = tornado.escape.url_escape(mac, plus=False)
        url = "http://" + host + "/rest/op" + "/reset/dhcp/server/lease/mac/" + esc_mac
        response = session.post(url)
        print('POST dhcp_info response headers ', response.headers)

        new_uri = response.headers['location']
        url = "http://" + host + "/" + new_uri
        response = session.get(url)
        print('GET dhcp_info response text ', response.text)

        return response.text

mac = "52:54:00:64:d1:0c"
reset_dhcp_lease(mac)
