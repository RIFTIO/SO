
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

import asyncio
from gi.repository import (
    RwDts as rwdts,
    RwcalYang as rwcal,
    RwTypes,
    ProtobufC,
    )

import rift.mano.cloud
import rift.mano.dts as mano_dts
import rift.tasklets

from . import openmano_nsm
from . import rwnsmplugin


class RwNsPlugin(rwnsmplugin.NsmPluginBase):
    """
        RW Implentation of the NsmPluginBase
    """
    def __init__(self, dts, log, loop, publisher, ro_account):
        self._dts = dts
        self._log = log
        self._loop = loop

    def create_nsr(self, nsr_msg, nsd,key_pairs=None):
        """
        Create Network service record
        """
        pass

    @asyncio.coroutine
    def deploy(self, nsr):
        pass

    @asyncio.coroutine
    def instantiate_ns(self, nsr, config_xact):
        """
        Instantiate NSR with the passed nsr id
        """
        yield from nsr.instantiate(config_xact)

    @asyncio.coroutine
    def instantiate_vnf(self, nsr, vnfr):
        """
        Instantiate NSR with the passed nsr id
        """
        yield from vnfr.instantiate(nsr)

    @asyncio.coroutine
    def instantiate_vl(self, nsr, vlr):
        """
        Instantiate NSR with the passed nsr id
        """
        yield from vlr.instantiate()

    @asyncio.coroutine
    def terminate_ns(self, nsr):
        """
        Terminate the network service
        """
        pass

    @asyncio.coroutine
    def terminate_vnf(self, vnfr):
        """
        Terminate the network service
        """
        yield from vnfr.terminate()

    @asyncio.coroutine
    def terminate_vl(self, vlr):
        """
        Terminate the virtual link
        """
        yield from vlr.terminate()


class NsmPlugins(object):
    """ NSM Plugins """
    def __init__(self):
        self._plugin_classes = {
                "openmano": openmano_nsm.OpenmanoNsPlugin,
                }

    @property
    def plugins(self):
        """ Plugin info """
        return self._plugin_classes

    def __getitem__(self, name):
        """ Get item """
        print("%s", self._plugin_classes)
        return self._plugin_classes[name]

    def register(self, plugin_name, plugin_class, *args):
        """ Register a plugin to this Nsm"""
        self._plugin_classes[plugin_name] = plugin_class

    def deregister(self, plugin_name, plugin_class, *args):
        """ Deregister a plugin to this Nsm"""
        if plugin_name in self._plugin_classes:
            del self._plugin_classes[plugin_name]

    def class_by_plugin_name(self, name):
        """ Get class by plugin name """
        return self._plugin_classes[name]


class CloudAccountConfigSubscriber:
    def __init__(self, log, dts, log_hdl):
        self._dts = dts
        self._log = log
        self._log_hdl = log_hdl

        self._cloud_sub = rift.mano.cloud.CloudAccountConfigSubscriber(
                self._dts,
                self._log,
                self._log_hdl,
                rift.mano.cloud.CloudAccountConfigCallbacks())

    def get_cloud_account_sdn_name(self, account_name):
        if account_name in self._cloud_sub.accounts:
            self._log.debug("Cloud accnt msg is %s",self._cloud_sub.accounts[account_name].account_msg)
            if self._cloud_sub.accounts[account_name].account_msg.has_field("sdn_account"):
                sdn_account = self._cloud_sub.accounts[account_name].account_msg.sdn_account 
                self._log.info("SDN associated with Cloud name %s is %s", account_name, sdn_account)
                return sdn_account
            else:
                self._log.debug("No SDN Account associated with Cloud name %s", account_name)
                return None

    @asyncio.coroutine
    def register(self):
       self._cloud_sub.register()


class ROAccountPluginSelector(object):
    """
    Select the RO based on the config.

    If no RO account is specified, then default to rift-ro.

    Note:
    Currently only one RO can be used (one-time global config.)
    """
    DEFAULT_PLUGIN = RwNsPlugin

    def __init__(self, dts, log, loop, records_publisher):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._records_publisher = records_publisher

        self._nsm_plugins = NsmPlugins()

        self._ro_sub = mano_dts.ROAccountConfigSubscriber(
                self._log,
                self._dts,
                self._loop,
                callback=self.on_ro_account_change
                )
        self._nsr_sub = mano_dts.NsrCatalogSubscriber(
                self._log,
                self._dts,
                self._loop,
                self.handle_nsr)

        # The default plugin will be RwNsPlugin
        self._ro_plugin = self._create_plugin(self.DEFAULT_PLUGIN, None)
        self.live_instances = 0

    @property
    def ro_plugin(self):
        return self._ro_plugin

    def handle_nsr(self, nsr, action):
        if action == rwdts.QueryAction.CREATE:
            self.live_instances += 1
        elif action == rwdts.QueryAction.DELETE:
            self.live_instances -= 1

    def on_ro_account_change(self, ro_account, action):
        if action in [rwdts.QueryAction.CREATE, rwdts.QueryAction.UPDATE]:
            self._on_ro_account_change(ro_account)
        elif action == rwdts.QueryAction.DELETE:
            self._on_ro_account_deleted(ro_account)

    def _on_ro_account_change(self, ro_account):
        self._log.debug("Got nsm plugin RO account: %s", ro_account)
        try:
            nsm_cls = self._nsm_plugins.class_by_plugin_name(
                    ro_account.account_type
                    )
        except KeyError as e:
            self._log.debug(
                "RO account nsm plugin not found: %s.  Using standard rift nsm.",
                ro_account.name
                )
            nsm_cls = self.DEFAULT_PLUGIN

        ro_plugin = self._create_plugin(nsm_cls, ro_account)
        if self.live_instances == 0:
            self._ro_plugin = ro_plugin
        else:
            raise ValueError("Unable to change the plugin when live NS instances exists!")

    def _on_ro_account_deleted(self, ro_account):
        self._ro_plugin = None

    def _create_plugin(self, nsm_cls, ro_account):

        self._log.debug("Instantiating new RO account using class: %s", nsm_cls)
        nsm_instance = nsm_cls(self._dts, self._log, self._loop,
                               self._records_publisher, ro_account)

        return nsm_instance

    @asyncio.coroutine
    def register(self):
        yield from self._ro_sub.register()
        yield from self._nsr_sub.register()
