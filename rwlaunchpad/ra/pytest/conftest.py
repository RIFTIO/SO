
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

import pytest
import os
import subprocess
import sys

import rift.auto.log
import rift.auto.session
import rift.vcs.vcs
import rift.rwcal.openstack
import rw_peas
import rwlogger
import logging

import gi
gi.require_version('RwCloudYang', '1.0')

from gi.repository import RwCloudYang, RwTypes

@pytest.fixture(scope='session')
def cloud_name_prefix():
    '''fixture which returns the prefix used in cloud account names'''
    return 'cloud'

@pytest.fixture(scope='session')
def cloud_account_name(cloud_name_prefix):
    '''fixture which returns the name used to identify the cloud account'''
    return '{prefix}-0'.format(prefix=cloud_name_prefix)

@pytest.fixture(scope='session')
def sdn_account_name():
    '''fixture which returns the name used to identify the sdn account'''
    return 'sdn-0'

@pytest.fixture(scope='session')
def openstack_sdn_account_name():
    '''fixture which returns the name used to identify the sdn account'''
    return 'openstack-sdn-0'

@pytest.fixture(scope='session')
def sdn_account_type():
    '''fixture which returns the account type used by the sdn account'''
    return 'odl'

@pytest.fixture(scope='session')
def cloud_module():
    '''Fixture containing the module which defines cloud account
    Returns:
        module to be used when configuring a cloud account
    '''
    return RwCloudYang

@pytest.fixture(scope='session')
def cloud_xpath():
    '''Fixture containing the xpath that should be used to configure a cloud account
    Returns:
        xpath to be used when configure a cloud account
    '''
    return '/cloud/account'

@pytest.fixture(scope='session')
def cloud_accounts(request, cloud_module, cloud_name_prefix, cloud_host, cloud_user, cloud_tenants, cloud_type):
    '''fixture which returns a list of CloudAccounts. One per tenant provided

    Arguments:
        cloud_module        - fixture: module defining cloud account
        cloud_name_prefix   - fixture: name prefix used for cloud account
        cloud_host          - fixture: cloud host address
        cloud_user          - fixture: cloud account user key
        cloud_tenants       - fixture: list of tenants to create cloud accounts on
        cloud_type          - fixture: cloud account type

    Returns:
        A list of CloudAccounts
    '''

    def account_name_generator(prefix):
        '''Generator of unique account names for a given prefix
        Arguments:
            prefix - prefix of account name
        '''
        idx=0
        while True:
            yield "{prefix}-{idx}".format(prefix=prefix, idx=idx)
            idx+=1
    name_gen = account_name_generator(cloud_name_prefix)

    accounts = []
    for cloud_tenant in cloud_tenants:
        if cloud_type == 'lxc':
            accounts.append(
                    cloud_module.CloudAccount.from_dict({
                        "name": next(name_gen),
                        "account_type": "cloudsim_proxy"})
            )
        elif cloud_type == 'openstack':
            hosts = [cloud_host]
            if request.config.option.upload_images_multiple_accounts:
                hosts.append('10.66.4.32')
            for host in hosts:
                password = 'mypasswd'
                auth_url = 'http://{host}:5000/v3/'.format(host=host)
                mgmt_network = os.getenv('MGMT_NETWORK', 'private')
                accounts.append(
                        cloud_module.CloudAccount.from_dict({
                            'name':  next(name_gen),
                            'account_type': 'openstack',
                            'openstack': {
                                'admin': True,
                                'key': cloud_user,
                                'secret': password,
                                'auth_url': auth_url,
                                'tenant': cloud_tenant,
                                'mgmt_network': mgmt_network}})
                )
        elif cloud_type == 'mock':
            accounts.append(
                    cloud_module.CloudAccount.from_dict({
                        "name": next(name_gen),
                        "account_type": "mock"})
            )

    return accounts


@pytest.fixture(scope='session', autouse=True)
def cloud_account(cloud_accounts):
    '''fixture which returns an instance of CloudAccount

    Arguments:
        cloud_accounts - fixture: list of generated cloud accounts

    Returns:
        An instance of CloudAccount
    '''
    return cloud_accounts[0]

@pytest.fixture(scope='class')
def vim_clients(cloud_accounts):
    """Fixture which returns sessions to VIMs"""
    vim_sessions = {}
    for cloud_account in cloud_accounts:
        if cloud_account.account_type == 'openstack':
            vim_sessions[cloud_account.name] = rift.rwcal.openstack.OpenstackDriver(**{'username': cloud_account.openstack.key,
                                                                        'password': cloud_account.openstack.secret,
                                                                        'auth_url': cloud_account.openstack.auth_url,
                                                                        'project': cloud_account.openstack.tenant,
                                                                        'mgmt_network': cloud_account.openstack.mgmt_network,
                                                                        'cert_validate': False,
                                                                        'user_domain': 'Default',
                                                                        'project_domain': 'Default',
                                                                        'region': 'RegionOne'})
        # Add initialization for other VIM types
    return vim_sessions


@pytest.fixture(scope='session')
def cal(cloud_account):
    """Fixture which returns cal interface"""
    if cloud_account.account_type == 'openstack':
        plugin = rw_peas.PeasPlugin('rwcal_openstack', 'RwCal-1.0')
    elif cloud_account.account_type == 'openvim':
        plugin = rw_peas.PeasPlugin('rwcal_openmano_vimconnector', 'RwCal-1.0')
    elif cloud_account.account_type == 'aws':
        plugin = rw_peas.PeasPlugin('rwcal_aws', 'RwCal-1.0')
    elif cloud_account.account_type == 'vsphere':
        plugin = rw_peas.PeasPlugin('rwcal-python', 'RwCal-1.0')

    engine, info, extension = plugin()
    cal = plugin.get_interface("Cloud")
    rwloggerctx = rwlogger.RwLog.Ctx.new("Cal-Log")
    rc = cal.init(rwloggerctx)
    assert rc == RwTypes.RwStatus.SUCCESS

    return cal
