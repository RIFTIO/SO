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
gi.require_version('RwsdnYang', '1.0')

from gi.repository import RwsdnYang

@pytest.mark.setup('sdn')
@pytest.mark.feature('sdn')
@pytest.mark.incremental
class TestSdnSetup:
    def test_create_odl_sdn_account(self, mgmt_session, sdn_account_name, sdn_account_type):
        '''Configure sdn account

        Asserts:
            SDN name and accout type.
        '''
        proxy = mgmt_session.proxy(RwsdnYang)
        sdn_account = RwsdnYang.SDNAccount(
                name=sdn_account_name,
                account_type=sdn_account_type)
        xpath = "/sdn-accounts/sdn-account-list[name='%s']" % sdn_account_name
        proxy.create_config(xpath, sdn_account)
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
        proxy = mgmt_session.proxy(RwsdnYang)
        xpath = "/sdn-accounts/sdn-account-list[name='%s']" % sdn_account_name
        sdn_account = proxy.get_config(xpath)
        assert sdn_account.account_type == sdn_account_type

@pytest.mark.teardown('sdn')
@pytest.mark.feature('sdn')
@pytest.mark.incremental
class TestSdnTeardown:
    def test_delete_odl_sdn_account(self, mgmt_session, sdn_account_name):
        '''Unconfigure sdn account'''
        proxy = mgmt_session.proxy(RwsdnYang)
        xpath = "/sdn-accounts/sdn-account-list[name='%s']" % sdn_account_name
        proxy.delete_config(xpath)


@pytest.mark.setup('launchpad')
@pytest.mark.usefixtures('cloud_account')
@pytest.mark.incremental
class TestLaunchpadSetup:
    def test_create_cloud_accounts(self, mgmt_session, cloud_module, cloud_xpath, cloud_accounts):
        '''Configure cloud accounts

        Asserts:
            Cloud name and cloud type details
        '''
        proxy = mgmt_session.proxy(cloud_module)
        for cloud_account in cloud_accounts:
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
