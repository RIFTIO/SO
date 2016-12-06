
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
import os
import threading
import time

import rift.tasklets
import rift.mano.cloud

from . import glance_proxy_server
from . import glance_client
from . import upload

import gi
gi.require_version('RwImageMgmtYang', '1.0')
gi.require_version('RwLaunchpadYang', '1.0')
gi.require_version('RwDts', '1.0')

from gi.repository import (
    RwcalYang,
    RwDts as rwdts,
    RwImageMgmtYang,
    RwLaunchpadYang,
)


class ImageRequestError(Exception):
    pass


class AccountNotFoundError(ImageRequestError):
    pass


class ImageNotFoundError(ImageRequestError):
    pass


class CloudAccountDtsHandler(object):
    def __init__(self, log, dts, log_hdl):
        self._dts = dts
        self._log = log
        self._log_hdl = log_hdl
        self._cloud_cfg_subscriber = None

    def register(self, on_add_apply, on_delete_apply):
        self._log.debug("creating cloud account config handler")
        self._cloud_cfg_subscriber = rift.mano.cloud.CloudAccountConfigSubscriber(
                self._dts, self._log, self._log_hdl,
                rift.mano.cloud.CloudAccountConfigCallbacks(
                    on_add_apply=on_add_apply,
                    on_delete_apply=on_delete_apply,
                    )
                )
        self._cloud_cfg_subscriber.register()


def openstack_image_to_image_info(openstack_image):
    """Convert the OpenstackImage to a ImageInfo protobuf message

    Arguments:
        openstack_image - A OpenstackImage instance

    Returns:
        A ImageInfo CAL protobuf message
    """

    image_info = RwcalYang.ImageInfoItem()

    copy_fields = ["id", "name", "checksum", "container_format", "disk_format"]
    for field in copy_fields:
        value = getattr(openstack_image, field)
        setattr(image_info, field, value)

    value = getattr(openstack_image, "properties")
    for key in value:
        prop = image_info.properties.add()
        prop.name = key
        prop.property_value = value[key]

    image_info.state = openstack_image.status

    return image_info


class ImageDTSShowHandler(object):
    """ A DTS publisher for the upload-jobs data container """
    def __init__(self, log, loop, dts, job_controller):
        self._log = log
        self._loop = loop
        self._dts = dts
        self._job_controller = job_controller

        self._subscriber = None

    @asyncio.coroutine
    def register(self):
        """ Register as a publisher and wait for reg_ready to complete """
        def get_xpath():
            return "D,/rw-image-mgmt:upload-jobs"

        @asyncio.coroutine
        def on_prepare(xact_info, action, ks_path, msg):
            if action != rwdts.QueryAction.READ:
                xact_info.respond_xpath(rwdts.XactRspCode.NACK)
                return

            jobs_pb_msg = self._job_controller.pb_msg

            xact_info.respond_xpath(
                    rwdts.XactRspCode.ACK,
                    xpath=get_xpath(),
                    msg=jobs_pb_msg,
                    )

        reg_event = asyncio.Event(loop=self._loop)

        @asyncio.coroutine
        def on_ready(regh, status):
            reg_event.set()

        self._subscriber = yield from self._dts.register(
                xpath=get_xpath(),
                handler=rift.tasklets.DTS.RegistrationHandler(
                    on_prepare=on_prepare,
                    on_ready=on_ready,
                    ),
                flags=rwdts.Flag.PUBLISHER,
                )

        yield from reg_event.wait()


class ImageDTSRPCHandler(object):
    """ A DTS publisher for the upload-job RPC's """
    def __init__(self, log, loop, dts, accounts, glance_client, upload_task_creator, job_controller):
        self._log = log
        self._loop = loop
        self._dts = dts
        self._accounts = accounts
        self._glance_client = glance_client
        self._upload_task_creator = upload_task_creator
        self._job_controller = job_controller

        self._subscriber = None

    @asyncio.coroutine
    def _register_create_upload_job(self):
        def get_xpath():
            return "/rw-image-mgmt:create-upload-job"

        @asyncio.coroutine
        def on_prepare(xact_info, action, ks_path, msg):
            create_msg = msg

            account_names = create_msg.cloud_account
            # If cloud accounts were not specified, upload image to all cloud account
            if not account_names:
                account_names = list(self._accounts.keys())

            for account_name in account_names:
                if account_name not in self._accounts:
                    raise AccountNotFoundError("Could not find account %s", account_name)

            if create_msg.has_field("external_url"):
                glance_image = yield from self._upload_task_creator.create_glance_image_from_url_create_rpc(
                        account_names, create_msg.external_url
                        )

                tasks = yield from self._upload_task_creator.create_tasks_from_glance_id(
                    account_names, glance_image.id
                    )

                def delete_image(ft):
                    try:
                        self._glance_client.delete_image_from_id(glance_image.id)
                    except glance_client.OpenstackImageDeleteError:
                        pass

                # Create a job and when the job completes delete the temporary
                # image from the catalog.
                job_id = self._job_controller.create_job(
                        tasks,
                        on_completed=delete_image
                        )

            elif create_msg.has_field("onboarded_image"):
                tasks = yield from self._upload_task_creator.create_tasks_from_onboarded_create_rpc(
                    account_names, create_msg.onboarded_image
                    )
                job_id = self._job_controller.create_job(tasks)

            else:
                raise ImageRequestError("an image selection must be provided")

            rpc_out_msg = RwImageMgmtYang.CreateUploadJobOutput(job_id=job_id)

            xact_info.respond_xpath(
                    rwdts.XactRspCode.ACK,
                    xpath="O," + get_xpath(),
                    msg=rpc_out_msg,
                    )

        reg_event = asyncio.Event(loop=self._loop)

        @asyncio.coroutine
        def on_ready(_, status):
            reg_event.set()

        self._subscriber = yield from self._dts.register(
                xpath="I," + get_xpath(),
                handler=rift.tasklets.DTS.RegistrationHandler(
                    on_prepare=on_prepare,
                    on_ready=on_ready,
                    ),
                flags=rwdts.Flag.PUBLISHER,
                )

        yield from reg_event.wait()

    @asyncio.coroutine
    def _register_cancel_upload_job(self):
        def get_xpath():
            return "/rw-image-mgmt:cancel-upload-job"

        @asyncio.coroutine
        def on_prepare(xact_info, action, ks_path, msg):
            if not msg.has_field("job_id"):
                self._log.error("cancel-upload-job missing job-id field.")
                xact_info.respond_xpath(rwdts.XactRspCode.NACK)
                return

            job_id = msg.job_id

            job = self._job_controller.get_job(job_id)
            job.stop()

            xact_info.respond_xpath(
                    rwdts.XactRspCode.ACK,
                    xpath="O," + get_xpath(),
                    )

        reg_event = asyncio.Event(loop=self._loop)

        @asyncio.coroutine
        def on_ready(_, status):
            reg_event.set()

        self._subscriber = yield from self._dts.register(
                xpath="I," + get_xpath(),
                handler=rift.tasklets.DTS.RegistrationHandler(
                    on_prepare=on_prepare,
                    on_ready=on_ready,
                    ),
                flags=rwdts.Flag.PUBLISHER,
                )

        yield from reg_event.wait()

    @asyncio.coroutine
    def register(self):
        """ Register for RPC's and wait for all registrations to complete """
        yield from self._register_create_upload_job()
        yield from self._register_cancel_upload_job()


class GlanceClientUploadTaskCreator(object):
    """ This class creates upload tasks using configured cloud accounts and
    configured image catalog glance client """

    def __init__(self, log, loop, accounts, glance_client):
        self._log = log
        self._loop = loop
        self._accounts = accounts
        self._glance_client = glance_client

    @asyncio.coroutine
    def create_tasks(self, account_names, image_id=None, image_name=None, image_checksum=None):
        """ Create a list of UploadTasks for a list of cloud accounts
        and a image with a matching image_name and image_checksum in the
        catalog

        Arguments:
            account_names - A list of configured cloud account names
            image_id - A image id
            image_name - A image name
            image_checksum - A image checksum

        Returns:
            A list of AccountImageUploadTask instances

        Raises:
            ImageNotFoundError - Could not find a matching image in the
                image catalog

            AccountNotFoundError - Could not find an account that matched
                the provided account name
        """
        try:
            image = yield from asyncio.wait_for(
                    self._loop.run_in_executor(
                            None,
                            self._glance_client.find_active_image,
                            image_id,
                            image_name,
                            image_checksum,
                            ),
                    timeout=5,
                    loop=self._loop,
                    )

        except glance_client.OpenstackImageError as e:
            msg = "Could not find image in Openstack to upload"
            self._log.exception(msg)
            raise ImageNotFoundError(msg) from e

        image_info = openstack_image_to_image_info(image)
        self._log.debug("created image info: %s", image_info)

        tasks = []
        for account_name in account_names:
            if account_name not in self._accounts:
                raise AccountNotFoundError("Could not find account %s", account_name)

        # For each account name provided, create a pipe (GlanceImagePipeGen)
        # which feeds data into the UploadTask while also monitoring the various
        # transmit stats (progress, bytes written, bytes per second, etc)
        for account_name in account_names:
            account = self._accounts[account_name]
            self._log.debug("creating task for account %s", account.name)
            glance_data_gen = self._glance_client.get_image_data(image_info.id)

            pipe_gen = upload.GlanceImagePipeGen(self._log, self._loop, glance_data_gen)
            progress_pipe = upload.UploadProgressWriteProxy(
                    self._log, self._loop, image.size, pipe_gen.write_hdl
                    )
            progress_pipe.start_rate_monitoring()
            pipe_gen.write_hdl = progress_pipe
            pipe_gen.start()

            task = upload.AccountImageUploadTask(
                    self._log, self._loop, account, image_info, pipe_gen.read_hdl,
                    progress_info=progress_pipe, write_canceller=pipe_gen,
                    )
            tasks.append(task)
            self._log.debug("task created: %s", task)

        return tasks

    @asyncio.coroutine
    def create_glance_image_from_url_create_rpc(self, account_names, create_msg):
        if "image_url" not in create_msg:
            raise ValueError("image_url must be specified")

        if "image_id" in create_msg:
            raise ImageRequestError("Cannot specify both image_url and image_id")

        if "image_name" not in create_msg:
            raise ImageRequestError("image_name must be specified when image_url is provided")

        glance_image = yield from asyncio.wait_for(
                self._loop.run_in_executor(
                    None,
                    self._glance_client.create_image_from_url,
                    create_msg.image_url,
                    create_msg.image_name,
                    create_msg.image_checksum if "image_checksum" in create_msg else None,
                    create_msg.disk_format if "disk_format" in create_msg else None,
                    create_msg.container_format if "container_format" in create_msg else None,
                    ),
                timeout=5,
                loop=self._loop,
                )

        return glance_image

    @asyncio.coroutine
    def create_tasks_from_glance_id(self, account_names, glance_image_id):
        return (yield from self.create_tasks(account_names, glance_image_id))

    @asyncio.coroutine
    def create_tasks_from_onboarded_create_rpc(self, account_names, create_msg):
        return (yield from self.create_tasks(
            account_names,
            create_msg.image_id if "image_id" in create_msg else None,
            create_msg.image_name if "image_name" in create_msg else None,
            create_msg.image_checksum if "image_checksum" in create_msg else None)
            )


class ImageManagerTasklet(rift.tasklets.Tasklet):
    """
    The RwImageMgrTasklet provides a interface for DTS to interact with an
    instance of the Monitor class. This allows the Monitor class to remain
    independent of DTS.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rwlog.set_category("rw-mano-log")

        self.cloud_cfg_subscriber = None
        self.http_proxy = None
        self.proxy_server = None
        self.dts = None
        self.job_controller = None
        self.cloud_accounts = {}
        self.glance_client = None
        self.task_creator = None
        self.rpc_handler = None
        self.show_handler = None

    def start(self):
        super().start()
        self.log.info("Starting Image Manager Tasklet")

        self.log.debug("Registering with dts")
        self.dts = rift.tasklets.DTS(
                self.tasklet_info,
                RwImageMgmtYang.get_schema(),
                self.loop,
                self.on_dts_state_change
                )

        self.log.debug("Created DTS Api GI Object: %s", self.dts)

    def stop(self):
        try:
            self.dts.deinit()
        except Exception as e:
            self.log.exception(e)

    @asyncio.coroutine
    def init(self):
        try:
            self.log.debug("creating cloud account handler")
            self.cloud_cfg_subscriber = CloudAccountDtsHandler(self.log, self.dts, self.log_hdl)
            self.cloud_cfg_subscriber.register(
                    self.on_cloud_account_create,
                    self.on_cloud_account_delete
                    )

            self.log.debug("creating http proxy server")

            self.http_proxy = glance_proxy_server.QuickProxyServer(self.log, self.loop)

            self.proxy_server = glance_proxy_server.GlanceHTTPProxyServer(
                    self.log, self.loop, self.http_proxy
                    )
            self.proxy_server.start()

            self.job_controller = upload.ImageUploadJobController(
                    self.log, self.loop
                    )

            self.glance_client = glance_client.OpenstackGlanceClient.from_token(
                    self.log, "127.0.0.1", "9292", "test"
                    )

            self.task_creator = GlanceClientUploadTaskCreator(
                    self.log, self.loop, self.cloud_accounts, self.glance_client
                    )

            self.rpc_handler = ImageDTSRPCHandler(
                    self.log, self.loop, self.dts, self.cloud_accounts, self.glance_client, self.task_creator,
                    self.job_controller
                    )
            yield from self.rpc_handler.register()

            self.show_handler = ImageDTSShowHandler(
                    self.log, self.loop, self.dts, self.job_controller
                    )
            yield from self.show_handler.register()


        except Exception as e:
            self.log.exception("error during init")

    def on_cloud_account_create(self, account):
        self.log.debug("adding cloud account: %s", account.name)
        self.cloud_accounts[account.name] = account

    def on_cloud_account_delete(self, account_name):
        self.log.debug("deleting cloud account: %s", account_name)
        if account_name not in self.cloud_accounts:
            self.log.warning("cloud account not found: %s", account_name)

        del self.cloud_accounts[account_name]

    @asyncio.coroutine
    def run(self):
        pass

    def on_instance_started(self):
        self.log.debug("Got instance started callback")

    @asyncio.coroutine
    def on_dts_state_change(self, state):
        """Handle DTS state change

        Take action according to current DTS state to transition application
        into the corresponding application state

        Arguments
            state - current dts state

        """
        switch = {
            rwdts.State.INIT: rwdts.State.REGN_COMPLETE,
            rwdts.State.CONFIG: rwdts.State.RUN,
        }

        handlers = {
            rwdts.State.INIT: self.init,
            rwdts.State.RUN: self.run,
        }

        # Transition application to next state
        handler = handlers.get(state, None)
        if handler is not None:
            yield from handler()

        # Transition dts to next state
        next_state = switch.get(state, None)
        if next_state is not None:
            self.dts.handle.set_state(next_state)
