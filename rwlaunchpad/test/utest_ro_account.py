
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
import sys
import types
import unittest
import uuid

import rift.test.dts
import rift.tasklets.rwnsmtasklet.cloud as cloud
import rift.tasklets.rwnsmtasklet.openmano_nsm as openmano_nsm
import rw_peas

import gi
gi.require_version('RwDtsYang', '1.0')
from gi.repository import (
        RwLaunchpadYang as launchpadyang,
        RwDts as rwdts,
        RwVnfdYang,
        RwVnfrYang,
        RwNsrYang,
        RwNsdYang,
        VnfrYang
        )


class DescriptorPublisher(object):
    def __init__(self, log, dts, loop):
        self.log = log
        self.loop = loop
        self.dts = dts

        self._registrations = []

    @asyncio.coroutine
    def publish(self, w_path, path, desc):
        ready_event = asyncio.Event(loop=self.loop)

        @asyncio.coroutine
        def on_ready(regh, status):
            self.log.debug("Create element: %s, obj-type:%s obj:%s",
                           path, type(desc), desc)
            with self.dts.transaction() as xact:
                regh.create_element(path, desc, xact.xact)
            self.log.debug("Created element: %s, obj:%s", path, desc)
            ready_event.set()

        handler = rift.tasklets.DTS.RegistrationHandler(
                on_ready=on_ready
                )

        self.log.debug("Registering path: %s, obj:%s", w_path, desc)
        reg = yield from self.dts.register(
                w_path,
                handler,
                flags=rwdts.Flag.PUBLISHER | rwdts.Flag.NO_PREP_READ
                )
        self._registrations.append(reg)
        self.log.debug("Registered path : %s", w_path)
        yield from ready_event.wait()

        return reg

    def unpublish_all(self):
        self.log.debug("Deregistering all published descriptors")
        for reg in self._registrations:
            reg.deregister()

class RoAccountDtsTestCase(rift.test.dts.AbstractDTSTest):
    @classmethod
    def configure_schema(cls):
       return launchpadyang.get_schema()

    @classmethod
    def configure_timeout(cls):
        return 240

    def configure_test(self, loop, test_id):
        self.log.debug("STARTING - %s", test_id)
        self.tinfo = self.new_tinfo(str(test_id))
        self.dts = rift.tasklets.DTS(self.tinfo, self.schema, self.loop)

        self.tinfo_sub = self.new_tinfo(str(test_id) + "_sub")
        self.dts_sub = rift.tasklets.DTS(self.tinfo_sub, self.schema, self.loop)

        self.publisher = DescriptorPublisher(self.log, self.dts, self.loop)

    def tearDown(self):
        super().tearDown()

    @rift.test.dts.async_test
    def test_orch_account_create(self):
        orch = cloud.ROAccountPluginSelector(self.dts, self.log, self.loop, None)

        yield from orch.register()

        # Test if we have a default plugin in case no RO is specified.
        assert type(orch.ro_plugin) is cloud.RwNsPlugin
        mock_orch_acc = launchpadyang.ResourceOrchestrator.from_dict(
                {'name': 'rift-ro', 'account_type': 'rift_ro', 'rift_ro': {'rift_ro': True}})

        # Test rift-ro plugin CREATE
        w_xpath = "C,/rw-launchpad:resource-orchestrator"
        xpath = w_xpath
        yield from self.publisher.publish(w_xpath, xpath, mock_orch_acc)
        yield from asyncio.sleep(5, loop=self.loop)

        assert type(orch.ro_plugin) is cloud.RwNsPlugin

        # Test Openmano plugin CREATE
        mock_orch_acc = launchpadyang.ResourceOrchestrator.from_dict(
                {'name': 'openmano',
                 'account_type': 'openmano',
                 'openmano': {'tenant_id': "abc",
                              "port": 9999,
                              "host": "10.64.11.77"}})
        yield from self.publisher.publish(w_xpath, xpath, mock_orch_acc)
        yield from asyncio.sleep(5, loop=self.loop)

        assert type(orch.ro_plugin) is openmano_nsm.OpenmanoNsPlugin
        assert orch.ro_plugin._cli_api._port  == mock_orch_acc.openmano.port
        assert orch.ro_plugin._cli_api._host  == mock_orch_acc.openmano.host

        # Test update
        mock_orch_acc.openmano.port = 9789
        mock_orch_acc.openmano.host = "10.64.11.78"
        yield from self.dts.query_update("C,/rw-launchpad:resource-orchestrator",
                rwdts.XactFlag.ADVISE, mock_orch_acc)
        assert orch.ro_plugin._cli_api._port  == mock_orch_acc.openmano.port
        assert orch.ro_plugin._cli_api._host  == mock_orch_acc.openmano.host

        # Test update when a live instance exists
        # Exception should be thrown
        orch.handle_nsr(None, rwdts.QueryAction.CREATE)
        mock_orch_acc.openmano.port = 9788

        with self.assertRaises(Exception):
            yield from self.dts.query_update("C,/rw-launchpad:resource-orchestrator",
                    rwdts.XactFlag.ADVISE, mock_orch_acc)

        # Test delete
        yield from self.dts.query_delete("C,/rw-launchpad:resource-orchestrator",
                flags=rwdts.XactFlag.ADVISE)
        assert orch.ro_plugin == None


def main(argv=sys.argv[1:]):

    # The unittest framework requires a program name, so use the name of this
    # file instead (we do not want to have to pass a fake program name to main
    # when this is called from the interpreter).
    unittest.main(
            argv=[__file__] + argv,
            testRunner=None#xmlrunner.XMLTestRunner(output=os.environ["RIFT_MODULE_TEST"])
            )

if __name__ == '__main__':
    main()