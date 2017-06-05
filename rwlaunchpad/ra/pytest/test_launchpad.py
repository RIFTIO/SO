#!/usr/bin/env python3
"""
# 
#   Copyright 2016 RIFT.IO Inc
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#

@file test_launchpad.py
@author Paul Laidler (Paul.Laidler@riftio.com)
@date 07/07/2016
@brief System test of basic launchpad functionality
"""

import pytest

import gi
gi.require_version('RwsdnalYang', '1.0')

from gi.repository import RwsdnalYang
from gi.repository import RwSdnYang

@pytest.mark.setup('sdn')
@pytest.mark.feature('sdn')
@pytest.mark.incremental
class TestSdnSetup:
    def test_create_odl_sdn_account(self, mgmt_session, sdn_account_name, sdn_account_type):
        '''Configure sdn account

        Asserts:
            SDN name and accout type.
        '''
        proxy = mgmt_session.proxy(RwsdnalYang)
        sdn_account = RwsdnalYang.SDNAccount(
                name=sdn_account_name,
                account_type=sdn_account_type)
        xpath = "/sdn-accounts/sdn-account-list[name='%s']" % sdn_account_name
        proxy.replace_config(xpath, sdn_account)
        sdn_account = proxy.get(xpath)

    @pytest.mark.skipif(not pytest.config.getoption("--l2-port-chaining"), reason="Only--l2-port-chaining test needs a sdn account of type 'openstack'")
    def test_create_openstack_sdn_account(self, mgmt_session, openstack_sdn_account_name, cloud_account):
        '''Configure sdn account

        Asserts:
            SDN name and account type.
        '''
        proxy = mgmt_session.proxy(RwSdnYang)
        sdn_account = RwSdnYang.SDNAccountConfig.from_dict({
                        'name':  openstack_sdn_account_name,
                        'account_type': 'openstack',
                        'openstack': {
                            'admin': cloud_account.openstack.admin,
                            'key': cloud_account.openstack.key,
                            'secret': cloud_account.openstack.secret,
                            'auth_url': cloud_account.openstack.auth_url,
                            'tenant': cloud_account.openstack.tenant,
                            'mgmt_network': cloud_account.openstack.mgmt_network}})

        xpath = "/sdn/account[name='{}']".format(openstack_sdn_account_name)
        proxy.replace_config(xpath, sdn_account)
        sdn_account = proxy.get(xpath)

@pytest.mark.depends('sdn')
@pytest.mark.feature('sdn')
@pytest.mark.incremental
class TestSdn:
    def test_show_odl_sdn_account(self, mgmt_session, sdn_account_name, sdn_account_type):
        '''Showing sdn account configuration

        Asserts:
            sdn_account.account_type is what was configured
        '''
        proxy = mgmt_session.proxy(RwsdnalYang)
        xpath = "/sdn-accounts/sdn-account-list[name='%s']" % sdn_account_name
        sdn_account = proxy.get_config(xpath)
        assert sdn_account.account_type == sdn_account_type

    @pytest.mark.skipif(not pytest.config.getoption("--l2-port-chaining"), reason="this is enabled only for --l2-port-chaining test")
    def test_openstack_sdn_account_connection_status(self, mgmt_session, openstack_sdn_account_name):
        '''Verify connection status on openstack sdn account

        Asserts:
            openstack sdn account is successfully connected
        '''
        proxy = mgmt_session.proxy(RwSdnYang)
        proxy.wait_for(
            '/sdn/account[name="{}"]/connection-status/status'.format(openstack_sdn_account_name),
            'success',
            timeout=30,
            fail_on=['failure'])

@pytest.mark.teardown('sdn')
@pytest.mark.feature('sdn')
@pytest.mark.incremental
class TestSdnTeardown:
    def test_delete_odl_sdn_account(self, mgmt_session, sdn_account_name):
        '''Unconfigure sdn account'''
        proxy = mgmt_session.proxy(RwsdnalYang)
        xpath = "/sdn-accounts/sdn-account-list[name='%s']" % sdn_account_name
        proxy.delete_config(xpath)

    @pytest.mark.skipif(not pytest.config.getoption("--l2-port-chaining"), reason="this is needed only for --l2-port-chaining test")
    def test_delete_openstack_sdn_account(self, mgmt_session, openstack_sdn_account_name):
        '''Unconfigure sdn account'''
        proxy = mgmt_session.proxy(RwSdnYang)
        xpath = '/sdn/account[name="{}"]'.format(openstack_sdn_account_name)
        proxy.delete_config(xpath)


@pytest.mark.setup('launchpad')
@pytest.mark.depends('sdn')
@pytest.mark.usefixtures('cloud_account')
@pytest.mark.incremental
class TestLaunchpadSetup:
    def test_create_cloud_accounts(self, mgmt_session, cloud_module, cloud_xpath, cloud_accounts, l2_port_chaining, openstack_sdn_account_name):
        '''Configure cloud accounts

        Asserts:
            Cloud name and cloud type details
        '''
        proxy = mgmt_session.proxy(cloud_module)
        for cloud_account in cloud_accounts:
            if l2_port_chaining:
                cloud_account.sdn_account = openstack_sdn_account_name
            xpath = '{}[name="{}"]'.format(cloud_xpath, cloud_account.name)
            proxy.replace_config(xpath, cloud_account)
            response =  proxy.get(xpath)
            assert response.name == cloud_account.name
            assert response.account_type == cloud_account.account_type

@pytest.mark.depends('launchpad')
@pytest.mark.usefixtures('cloud_account')
@pytest.mark.incremental
class TestLaunchpad:
    def test_account_connection_status(self, mgmt_session, cloud_module, cloud_xpath, cloud_accounts):
        '''Verify connection status on each cloud account

        Asserts:
            Cloud account is successfully connected
        '''
        proxy = mgmt_session.proxy(cloud_module)
        for cloud_account in cloud_accounts:
            proxy.wait_for(
                '{}[name="{}"]/connection-status/status'.format(cloud_xpath, cloud_account.name),
                'success',
                timeout=30,
                fail_on=['failure'])


@pytest.mark.teardown('launchpad')
@pytest.mark.usefixtures('cloud_account')
@pytest.mark.incremental
class TestLaunchpadTeardown:
    def test_delete_cloud_accounts(self, mgmt_session, cloud_module, cloud_xpath, cloud_accounts):
        '''Unconfigure cloud_account'''
        proxy = mgmt_session.proxy(cloud_module)
        for cloud_account in cloud_accounts:
            xpath = "{}[name='{}']".format(cloud_xpath, cloud_account.name)
            proxy.delete_config(xpath)
