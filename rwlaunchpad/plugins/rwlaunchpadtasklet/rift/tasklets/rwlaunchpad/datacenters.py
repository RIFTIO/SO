
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
    RwDts,
    RwLaunchpadYang,
)

import rift.mano.dts as mano_dts
import rift.openmano.openmano_client as openmano_client
import rift.tasklets


class DataCenterPublisher(mano_dts.DtsHandler):
    """
    This class is reponsible for exposing the data centers associated with an
    openmano cloud account.
    """

    XPATH = "D,/rw-launchpad:datacenters"

    def __init__(self, log, dts, loop):
        """Creates an instance of a DataCenterPublisher

        Arguments:
            tasklet - the tasklet that this publisher is registered for

        """
        super().__init__(log, dts, loop)

        self._ro_sub = mano_dts.ROAccountConfigSubscriber(
                        self.log,
                        self.dts,
                        self.loop,
                        callback=self.on_ro_account_change
                        )
        self.ro_accounts = {}

    def on_ro_account_change(self, ro_account, action):
        if action in  [ RwDts.QueryAction.CREATE, RwDts.QueryAction.UPDATE ]:
            self.ro_accounts[ro_account.name] = ro_account
        elif action == RwDts.QueryAction.DELETE and ro_account.name in self.ro_accounts:
            del self.ro_accounts[ro_account.name]

    @asyncio.coroutine
    def register(self):
        """Registers the publisher with DTS"""
        yield from self._ro_sub.register()

        @asyncio.coroutine
        def on_prepare(xact_info, action, ks_path, msg):
            try:
                # Create a datacenters instance to hold all of the cloud
                # account data.
                datacenters = RwLaunchpadYang.DataCenters()

                # Iterate over the known openmano accounts and populate cloud
                # account instances with the corresponding data center info
                for _, account in self.ro_accounts.items():
                    if account.account_type != "openmano":
                        continue

                    try:
                        ro_account = RwLaunchpadYang.ROAccount()
                        ro_account.name = account.name

                        # Create a client for this cloud account to query for
                        # the associated data centers
                        client = openmano_client.OpenmanoCliAPI(
                                self.log,
                                account.openmano.host,
                                account.openmano.port,
                                account.openmano.tenant_id,
                                )

                        # Populate the cloud account with the data center info
                        for uuid, name in client.datacenter_list():
                            ro_account.datacenters.append(
                                    RwLaunchpadYang.DataCenter(
                                        uuid=uuid,
                                        name=name,
                                        )
                                    )

                        datacenters.ro_accounts.append(ro_account)

                    except Exception as e:
                        self.log.exception(e)

                xact_info.respond_xpath(
                        RwDts.XactRspCode.MORE,
                        'D,/rw-launchpad:datacenters',
                        datacenters,
                        )

                xact_info.respond_xpath(RwDts.XactRspCode.ACK)

            except Exception as e:
                self.log.exception(e)
                raise

        handler = rift.tasklets.DTS.RegistrationHandler(on_prepare=on_prepare)

        with self.dts.group_create() as group:
            self.reg = group.register(
                    xpath=DataCenterPublisher.XPATH,
                    handler=handler,
                    flags=RwDts.Flag.PUBLISHER,
                    )
