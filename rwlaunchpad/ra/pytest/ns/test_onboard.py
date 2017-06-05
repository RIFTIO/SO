#!/usr/bin/env python
"""
# 
#   Copyright 2016-2017 RIFT.io Inc
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

@file test_onboard.py
@author Varun Prasad (varun.prasad@riftio.com)
@brief Onboard descriptors
"""

import json
import logging
import os
import pytest
import shlex
import requests
import shutil
import subprocess
import time
import uuid
import random
import numpy as np

import requests_toolbelt


import rift.auto.mano
import rift.auto.session
import rift.auto.descriptor

import gi
gi.require_version('RwNsrYang', '1.0')
gi.require_version('RwVnfdYang', '1.0')
gi.require_version('RwLaunchpadYang', '1.0')
gi.require_version('RwBaseYang', '1.0')
gi.require_version('RwStagingMgmtYang', '1.0')
gi.require_version('RwPkgMgmtYang', '1.0')
gi.require_version('RwVlrYang', '1.0')

from gi.repository import (
    RwcalYang,
    NsdYang,
    RwNsrYang,
    RwVnfrYang,
    NsrYang,
    VnfrYang,
    VldYang,
    RwVnfdYang,
    RwLaunchpadYang,
    RwBaseYang,
    RwStagingMgmtYang,
    RwPkgMgmtYang,
    RwImageMgmtYang,
    RwTypes,
    RwVlrYang
)

logging.basicConfig(level=logging.DEBUG)


@pytest.fixture(scope='module')
def vnfd_proxy(request, mgmt_session):
    return mgmt_session.proxy(RwVnfdYang)

@pytest.fixture(scope='module')
def rwvnfr_proxy(request, mgmt_session):
    return mgmt_session.proxy(RwVnfrYang)

@pytest.fixture(scope='module')
def vld_proxy(request, mgmt_session):
    return mgmt_session.proxy(VldYang)


@pytest.fixture(scope='module')
def rwvlr_proxy(request, mgmt_session):
    return mgmt_session.proxy(RwVlrYang)


@pytest.fixture(scope='module')
def nsd_proxy(request, mgmt_session):
    return mgmt_session.proxy(NsdYang)


@pytest.fixture(scope='module')
def rwnsr_proxy(request, mgmt_session):
    return mgmt_session.proxy(RwNsrYang)

@pytest.fixture(scope='module')
def base_proxy(request, mgmt_session):
    return mgmt_session.proxy(RwBaseYang)


@pytest.fixture(scope="module")
def endpoint():
    return "upload"


def upload_descriptor(
        logger,
        descriptor_file,
        scheme,
        cert,
        host="127.0.0.1",
        endpoint="upload"):
    curl_cmd = ('curl --cert {cert} --key {key} -F "descriptor=@{file}" -k '
                '{scheme}://{host}:4567/api/{endpoint}'.format(
            cert=cert[0],
            key=cert[1],
            scheme=scheme,
            endpoint=endpoint,
            file=descriptor_file,
            host=host,
            ))

    logger.debug("Uploading descriptor %s using cmd: %s", descriptor_file, curl_cmd)
    stdout = subprocess.check_output(shlex.split(curl_cmd), universal_newlines=True)

    json_out = json.loads(stdout)
    transaction_id = json_out["transaction_id"]

    return transaction_id


class DescriptorOnboardError(Exception):
    pass


def wait_onboard_transaction_finished(
        logger,
        transaction_id,
        scheme,
        cert,
        timeout=600,
        host="127.0.0.1",
        endpoint="upload"):

    logger.info("Waiting for onboard trans_id %s to complete", transaction_id)
    uri = '%s://%s:4567/api/%s/%s/state' % (scheme, host, endpoint, transaction_id)

    elapsed = 0
    start = time.time()
    while elapsed < timeout:
        reply = requests.get(uri, cert=cert, verify=False)
        state = reply.json()
        if state["status"] == "success":
            break
        if state["status"] != "pending":
            raise DescriptorOnboardError(state)

        time.sleep(1)
        elapsed = time.time() - start


    if state["status"] != "success":
        raise DescriptorOnboardError(state)
    logger.info("Descriptor onboard was successful")


def onboard_descriptor(host, file_name, logger, endpoint, scheme, cert):
    """On-board/update the descriptor.

    Args:
        host (str): Launchpad IP
        file_name (str): Full file path.
        logger: Logger instance
        endpoint (str): endpoint to be used for the upload operation.

    """
    logger.info("Onboarding package: %s", file_name)
    trans_id = upload_descriptor(
            logger,
            file_name,
            scheme,
            cert,
            host=host,
            endpoint=endpoint)
    wait_onboard_transaction_finished(
        logger,
        trans_id,
        scheme,
        cert,
        host=host,
        endpoint=endpoint)


def get_ns_cloud_resources(rwvnfr_proxy, rwvlr_proxy):
    """Returns a collection of ports, networks, VMs used by this NS"""
    ns_cloud_resources = {'ports':[], 'vms':[], 'networks':[]}

    # Get ports and VMs associated with each VNF
    vnfrs = rwvnfr_proxy.get('/vnfr-catalog/vnfr', list_obj=True)
    for vnfr in vnfrs.vnfr:
        for cp in vnfr.connection_point:
            ns_cloud_resources['ports'].append(cp.connection_point_id)
        for vdur in vnfr.vdur:
            ns_cloud_resources['vms'].append(vdur.vim_id)

    # Get the network associated with each NS
    vlrs = rwvlr_proxy.get('/vlr-catalog/vlr', list_obj=True)
    for vlr in vlrs.vlr:
        ns_cloud_resources['networks'].append(vlr.network_id)

    return ns_cloud_resources


@pytest.mark.setup('nsr')
@pytest.mark.depends('launchpad')
@pytest.mark.incremental
class TestNsrStart(object):
    """A brief overview of the steps performed.
    1. Generate & on-board new descriptors
    2. Start the NSR 
    """

    def test_upload_descriptors(
            self,
            logger,
            vnfd_proxy,
            nsd_proxy,
            mgmt_session,
            scheme,
            cert,
            descriptors
        ):
        """Generates & On-boards the descriptors.

        1. Request a staging area: RPC returns an endpoint and port
        1. Upload the file to the endpoint, return the endpoint to download 
        2. Reconstruct the URL and trigger an RPC upload for the package.
        """
        endpoint = "upload"

        for file_name in descriptors:

            ip = RwStagingMgmtYang.YangInput_RwStagingMgmt_CreateStagingArea.from_dict({
                    "package_type": "VNFD"})

            if "nsd" in file_name:
                ip.package_type = "NSD"

            data = mgmt_session.proxy(RwStagingMgmtYang).rpc(ip)
            form = requests_toolbelt.MultipartEncoder(fields={
                        'file': (os.path.basename(file_name),
                                 open(file_name, 'rb'),
                                 'application/octet-stream')
                        })

            response = requests.post(
                    "{}://{}:{}/{}".format(
                            scheme,
                            mgmt_session.host,
                            data.port,
                            data.endpoint),
                    data=form.to_string(),
                    cert=cert,  # cert is a tuple
                    verify=False,
                    headers={"Content-Type": "multipart/form-data"})

            resp = json.loads(response.text)
            url = "https://{}:{}{}".format(mgmt_session.host, data.port, resp['path'])

            ip = RwPkgMgmtYang.YangInput_RwPkgMgmt_PackageCreate.from_dict({
                    "package_type": "VNFD",
                    "external_url": url
                })

            if "nsd" in file_name:
                ip.package_type = "NSD"

            # trigger the upload.
            resp = mgmt_session.proxy(RwPkgMgmtYang).rpc(ip)

            wait_onboard_transaction_finished(
                logger,
                resp.transaction_id,
                scheme,
                cert,
                host=mgmt_session.host,
                endpoint=endpoint)

        descriptor_vnfds, descriptor_nsd = descriptors[:-1], descriptors[-1]

        catalog = vnfd_proxy.get_config('/vnfd-catalog')
        actual_vnfds = catalog.vnfd
        assert len(actual_vnfds) == len(descriptor_vnfds), \
                "There should {} vnfds".format(len(descriptor_vnfds))

        catalog = nsd_proxy.get_config('/nsd-catalog')
        actual_nsds = catalog.nsd
        assert len(actual_nsds) == 1, "There should only be a single nsd"

    @pytest.mark.skipif(not pytest.config.getoption('--upload-images-multiple-accounts'),
                        reason="need --upload-images-multiple-accounts option to run")
    def test_images_uploaded_multiple_accounts(self, logger, mgmt_session, random_image_name, cloud_accounts, cal):
        image_mgmt_proxy = mgmt_session.proxy(RwImageMgmtYang)
        upload_jobs = image_mgmt_proxy.get('/upload-jobs')
        logger.info('Embedded image name(apart from ping pong Fedora images): {}'.format(random_image_name))
        for job in upload_jobs.job:
            assert image_mgmt_proxy.wait_for('/upload-jobs/job[id="{}"]/status'.format(job.id), 'COMPLETED', timeout=240)
            assert len(job.upload_tasks) == len(cloud_accounts)
            for upload_task in job.upload_tasks:
                assert upload_task.status == 'COMPLETED'

        assert len(upload_jobs.job) == 3
        
        # Check whether images are present in VIMs
        for account in cloud_accounts:
            rc, res = cal.get_image_list(RwcalYang.CloudAccount.from_dict(
                account.as_dict()))  # account is of type RwCloudYang.CloudAccount, and cal.get_image_list expects RwcalYang.CloudAccount type
            assert rc == RwTypes.RwStatus.SUCCESS
            assert [image for image in res.imageinfo_list if image.name == random_image_name]

    @pytest.mark.skipif(not pytest.config.getoption("--vnf-onboard-delete"), reason="need --vnf-onboard-delete option to run")
    def test_upload_delete_descriptors(self, logger, mgmt_session, vnfd_proxy, descriptors, vnf_onboard_delete):
        """Randomly upload and delete VNFs. With each upload/delete, verify if the VNF
        gets uploaded/deleted successfully.
        """
        xpath = "/vnfd-catalog/vnfd[id='{}']"
        iteration, vnf_count = map(int, vnf_onboard_delete.split(','))
        
        # Get the VNF paths to be used for onboarding
        all_vnfs = [pkg_path for pkg_path in descriptors if '_nsd' not in os.path.basename(pkg_path)]
        if vnf_count > len(all_vnfs):
            vnf_count = len(all_vnfs)
        available_vnfs = random.sample(all_vnfs, vnf_count)

        # Get the add, delete iterations
        add_del_seq = list(np.random.choice(['add', 'del'], iteration))
        random.shuffle(add_del_seq)
        logger.info('Vnf add-delete iteration sequence: {}'.format(add_del_seq))

        uploaded_vnfs = {}

        def get_vnfd_list():
            """Returns list of VNFDs"""
            vnfd_obj = vnfd_proxy.get("/vnfd-catalog/vnfd", list_obj=True)
            return vnfd_obj.vnfd if vnfd_obj else []

        def delete_vnfd():
            """Deletes a VNFD"""
            vnf_path, vnfd_id = random.choice(list(uploaded_vnfs.items()))
            logger.info('Deleting VNF {} having id {}'.format(os.path.basename(vnf_path), vnfd_id))
            vnfd_proxy.delete_config(xpath.format(vnfd_id))
            uploaded_vnfs.pop(vnf_path)
            available_vnfs.append(vnf_path)
            assert not [vnfd for vnfd in get_vnfd_list() if vnfd.id == vnfd_id]
        
        for op_type in add_del_seq:
            if op_type =='del':
                if uploaded_vnfs:
                    delete_vnfd()
                    continue
                op_type = 'add'

            if op_type == 'add':
                if not available_vnfs:
                    delete_vnfd()
                    continue
                vnf_path = random.choice(available_vnfs)
                logger.info('Adding VNF {}'.format(os.path.basename(vnf_path)))
                rift.auto.descriptor.onboard(mgmt_session, vnf_path)
                vnfs = get_vnfd_list()
                assert len(vnfs) == len(uploaded_vnfs) + 1
                vnfd = [vnfd for vnfd in vnfs if vnfd.id not in list(uploaded_vnfs.values())]
                assert len(vnfd) == 1
                vnfd = vnfd[0]
                assert vnfd.name
                assert vnfd.connection_point
                assert vnfd.vdu
                uploaded_vnfs[vnf_path] = vnfd.id
                available_vnfs.remove(vnf_path)
    
            assert len(get_vnfd_list()) == len(uploaded_vnfs)
            logger.info('Onboarded VNFs : {}'.format(uploaded_vnfs))

        assert len(available_vnfs) + len(uploaded_vnfs) == vnf_count
        # cleanup - Delete VNFs(if any)
        for vnfd_id in uploaded_vnfs.values():
            vnfd_proxy.delete_config(xpath.format(vnfd_id))

    @pytest.mark.feature("upload-image")
    def test_upload_images(self, descriptor_images, cloud_host, cloud_user, cloud_tenants):

        openstack = rift.auto.mano.OpenstackManoSetup(
                cloud_host,
                cloud_user,
                [(tenant, "private") for tenant in cloud_tenants])
        
        for image_location in descriptor_images:
            image = RwcalYang.ImageInfoItem.from_dict({
                    'name': os.path.basename(image_location),
                    'location': image_location,
                    'disk_format': 'qcow2',
                    'container_format': 'bare'})
            openstack.create_image(image)


    def test_set_scaling_params(self, nsd_proxy):
        nsds = nsd_proxy.get('/nsd-catalog')
        nsd = nsds.nsd[0]
        for scaling_group in nsd.scaling_group_descriptor:
            scaling_group.max_instance_count = 2

        nsd_proxy.replace_config('/nsd-catalog/nsd[id="{}"]'.format(
            nsd.id), nsd)

    @pytest.mark.skipif(not pytest.config.getoption("--update-vnfd-instantiate"),
                        reason="need --update-vnfd-instantiate option to run")
    def test_update_vnfd(self, vnfd_proxy):
        """Updates few fields of ping pong VNFDs and verify those changes
        """
        xpath = "/vnfd-catalog/vnfd[id='{}']"
        vnfd_catalog = "/vnfd-catalog/vnfd"

        def get_vnfd():
            vnfds = vnfd_proxy.get(vnfd_catalog, list_obj=True)
            dict_ = {}

            # Get ping pong VNFDs
            for vnfd in vnfds.vnfd:
                if 'ping' in vnfd.name:
                    dict_['ping'] = vnfd
                if 'pong' in vnfd.name:
                    dict_['pong'] = vnfd
            return dict_

        vnfds_dict = get_vnfd()
        update_data = {'ping':{'static_ip_address':'31.31.31.60'}, 'pong':{'static_ip_address':'31.31.31.90'}}

        # Modify/add fields in VNFDs
        for name_, vnfd in vnfds_dict.items():
            vnfd.connection_point[0].static_ip_address = update_data[name_]['static_ip_address']

        # Update/save the VNFDs      
        for vnfd in vnfds_dict.values():
            vnfd_proxy.replace_config(xpath.format(vnfd.id), vnfd)

        # Match whether data is updated
        vnfds_dict = get_vnfd()
        assert vnfds_dict
        for name_, vnfd in vnfds_dict.items():
            assert vnfd.connection_point[0].static_ip_address == update_data[name_]['static_ip_address']

    def test_instantiate_nsr(self, logger, nsd_proxy, rwnsr_proxy, base_proxy, cloud_account_name):

        def verify_input_parameters(running_config, config_param):
            """
            Verify the configured parameter set against the running configuration
            """
            for run_input_param in running_config.input_parameter:
                if (run_input_param.xpath == config_param.xpath and
                    run_input_param.value == config_param.value):
                    return True

            assert False, ("Verification of configured input parameters: { xpath:%s, value:%s} "
                          "is unsuccessful.\nRunning configuration: %s" % (config_param.xpath,
                                                                           config_param.value,
                                                                           running_config.input_parameter))

        catalog = nsd_proxy.get_config('/nsd-catalog')
        nsd = catalog.nsd[0]

        input_parameters = []
        descr_xpath = "/nsd:nsd-catalog/nsd:nsd/nsd:vendor"
        descr_value = "New Vendor"
        in_param_id = str(uuid.uuid4())

        input_param_1 = NsrYang.YangData_Nsr_NsInstanceConfig_Nsr_InputParameter(
                                                                xpath=descr_xpath,
                                                                value=descr_value)

        input_parameters.append(input_param_1)

        nsr = rift.auto.descriptor.create_nsr(cloud_account_name, nsd.name, nsd, input_param_list=input_parameters)

        logger.info("Instantiating the Network Service")
        rwnsr_proxy.create_config('/ns-instance-config/nsr', nsr)

        nsr_opdata = rwnsr_proxy.get('/ns-instance-opdata/nsr[ns-instance-config-ref="{}"]'.format(nsr.id))
        assert nsr_opdata is not None

        # Verify the input parameter configuration
        running_config = rwnsr_proxy.get_config("/ns-instance-config/nsr[id='%s']" % nsr.id)
        for input_param in input_parameters:
            verify_input_parameters(running_config, input_param)

    def test_wait_for_nsr_started(self, rwnsr_proxy):
        nsr_opdata = rwnsr_proxy.get('/ns-instance-opdata')
        nsrs = nsr_opdata.nsr

        for nsr in nsrs:
            xpath = "/ns-instance-opdata/nsr[ns-instance-config-ref='{}']/operational-status".format(nsr.ns_instance_config_ref)
            rwnsr_proxy.wait_for(xpath, "running", fail_on=['failed'], timeout=240)


@pytest.mark.teardown('nsr')
@pytest.mark.depends('launchpad')
@pytest.mark.incremental
class TestNsrTeardown(object):

    def test_delete_embedded_images(self, random_image_name, cloud_accounts, cal):
        """Deletes images embedded in VNF from VIM. It only deletes additional images, not 
        the Fedora ping pong images"""
        for account in cloud_accounts:
            rc, rsp = cal.get_image_list(RwcalYang.CloudAccount.from_dict(account.as_dict()))

            for image in rsp.imageinfo_list:
                if random_image_name in image.name:
                    cal.delete_image(RwcalYang.CloudAccount.from_dict(account.as_dict()), image.id)

    def test_terminate_nsr(self, rwvnfr_proxy, rwnsr_proxy, logger, cloud_type, rwvlr_proxy, vim_clients, cloud_account_name):
        """
        Terminate the instance and check if the record is deleted.

        Asserts:
        1. NSR record is deleted from instance-config.

        """
        # Collects the Cloud resources like ports, networks, VMs used by the current NS
        ns_cloud_resources = get_ns_cloud_resources(rwvnfr_proxy, rwvlr_proxy)
        logger.info('Cloud resources used by NS: {}'.format(ns_cloud_resources))

        logger.debug("Terminating NSR")
        wait_after_kill = True
        if cloud_type == "mock":
            wait_after_kill = False

        rift.auto.descriptor.terminate_nsr(rwvnfr_proxy, rwnsr_proxy, logger, wait_after_kill=wait_after_kill)

        # Collect all the ports, networks VMs from openstack and
        # check if previously collected resources (i.e ns_cloud_resources) are still present in this collection
        vim_client = vim_clients[cloud_account_name]
        vim_resources = dict()
        vim_resources['networks'] = vim_client.neutron_network_list()
        vim_resources['vms'] = vim_client.nova_server_list()
        vim_resources['ports'] = vim_client.neutron_port_list()

        logger.info('Validates if the resources are cleared from openstack')
        for resource_type, ns_resource_ids in ns_cloud_resources.items():
            logger.debug('Verifying resources {} of type {}'.format(ns_resource_ids, resource_type))
            for ns_resource_id in ns_resource_ids:
                assert not [vim_resource for vim_resource in vim_resources[resource_type] if
                        vim_resource['id'] == ns_resource_id]

    def test_delete_records(self, nsd_proxy, vnfd_proxy):
        """Delete the NSD & VNFD records

        Asserts:
            The records are deleted.
        """
        nsds = nsd_proxy.get("/nsd-catalog/nsd", list_obj=True)
        for nsd in nsds.nsd:
            xpath = "/nsd-catalog/nsd[id='{}']".format(nsd.id)
            nsd_proxy.delete_config(xpath)

        nsds = nsd_proxy.get("/nsd-catalog/nsd", list_obj=True)
        assert nsds is None or len(nsds.nsd) == 0

        vnfds = vnfd_proxy.get("/vnfd-catalog/vnfd", list_obj=True)
        for vnfd_record in vnfds.vnfd:
            xpath = "/vnfd-catalog/vnfd[id='{}']".format(vnfd_record.id)
            vnfd_proxy.delete_config(xpath)

        vnfds = vnfd_proxy.get("/vnfd-catalog/vnfd", list_obj=True)
        assert vnfds is None or len(vnfds.vnfd) == 0

    
