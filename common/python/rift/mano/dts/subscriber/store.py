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

@file store.py
@author Varun Prasad (varun.prasad@riftio.com)
@date 09-Jul-2016

"""

import asyncio
import enum

from gi.repository import RwDts as rwdts
from . import core, ns_subscriber, vnf_subscriber


class SubscriberStore(core.SubscriberDtsHandler):
    """A convenience class that hold all the VNF and NS related config and Opdata
    """
    KEY = enum.Enum('KEY', 'NSR NSD VNFD VNFR')

    def __init__(self, log, dts, loop, callback=None):
        super().__init__(log, dts, loop)

        params = (self.log, self.dts, self.loop)

        self._nsd_sub = ns_subscriber.NsdCatalogSubscriber(*params)
        self._vnfd_sub = vnf_subscriber.VnfdCatalogSubscriber(*params)

    @property
    def vnfd(self):
        return list(self._vnfd_sub.reg.get_xact_elements())

    @property
    def nsd(self):
        return list(self._nsd_sub.reg.get_xact_elements())

    def _unwrap(self, values, id_name):
        try:
            return values[0]
        except KeyError:
            self.log.exception("Unable to find the object with the given "
                "ID {}".format(id_name))

    def get_nsd(self, nsd_id):
        values = [nsd for nsd in self.nsd if nsd.id == nsd_id]
        return self._unwrap(values, nsd_id)

    def get_vnfd(self, vnfd_id):
        values = [vnfd for vnfd in self.vnfd if vnfd.id == vnfd_id]
        return self._unwrap(values, vnfd_id)

    @asyncio.coroutine
    def register(self):
        yield from self._vnfd_sub.register()
        yield from self._nsd_sub.register()
