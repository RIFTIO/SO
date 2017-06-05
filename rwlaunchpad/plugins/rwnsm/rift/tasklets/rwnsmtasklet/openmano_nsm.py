
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
import sys
import time
import yaml

import gi
gi.require_version('RwDts', '1.0')
gi.require_version('RwVnfrYang', '1.0')
from gi.repository import (
    RwDts as rwdts,
    RwVnfrYang,
)

import rift.openmano.rift2openmano as rift2openmano
import rift.openmano.openmano_client as openmano_client
from . import rwnsmplugin
from enum import Enum


import rift.tasklets

if sys.version_info < (3, 4, 4):
    asyncio.ensure_future = asyncio.async


DUMP_OPENMANO_DIR = os.path.join(
    os.environ["RIFT_ARTIFACTS"],
    "openmano_descriptors"
)


def dump_openmano_descriptor(name, descriptor_str):
    filename = "{}_{}.yaml".format(
        time.strftime("%Y%m%d-%H%M%S"),
        name
    )

    filepath = os.path.join(
        DUMP_OPENMANO_DIR,
        filename
    )

    try:
        if not os.path.exists(DUMP_OPENMANO_DIR):
            os.makedirs(DUMP_OPENMANO_DIR)

        with open(filepath, 'w') as hdl:
            hdl.write(descriptor_str)

    except OSError as e:
        print("Failed to dump openmano descriptor: %s" % str(e))

    return filepath

class VnfrConsoleOperdataDtsHandler(object):
    """ registers 'D,/vnfr:vnfr-console/vnfr:vnfr[id]/vdur[id]' and handles CRUD from DTS"""
    @property
    def vnfr_vdu_console_xpath(self):
        """ path for resource-mgr"""
        return ("D,/rw-vnfr:vnfr-console/rw-vnfr:vnfr[rw-vnfr:id='{}']/rw-vnfr:vdur[vnfr:id='{}']".format(self._vnfr_id,self._vdur_id))

    def __init__(self, dts, log, loop, nsr, vnfr_id, vdur_id, vdu_id):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._regh = None
        self._nsr = nsr

        self._vnfr_id = vnfr_id
        self._vdur_id = vdur_id
        self._vdu_id = vdu_id

    @asyncio.coroutine
    def register(self):
        """ Register for VNFR VDU Operational Data read from dts """

        @asyncio.coroutine
        def on_prepare(xact_info, action, ks_path, msg):
            """ prepare callback from dts """
            xpath = ks_path.to_xpath(RwVnfrYang.get_schema())
            self._log.debug(
                "Got VNFR VDU Opdata xact_info: %s, action: %s): %s:%s",
                xact_info, action, xpath, msg
            )

            if action == rwdts.QueryAction.READ:
                schema = RwVnfrYang.YangData_RwVnfr_VnfrConsole_Vnfr_Vdur.schema()
                path_entry = schema.keyspec_to_entry(ks_path)

                try:
                    console_url = yield from self._loop.run_in_executor(
                        None,
                        self._nsr._http_api.get_instance_vm_console_url,
                        self._nsr._nsr_uuid,
                        self._vdur_id
                    )

                    self._log.debug("Got console response: %s for NSR ID %s vdur ID %s",
                                    console_url,
                                    self._nsr._nsr_uuid,
                                    self._vdur_id
                                    )
                    vdur_console = RwVnfrYang.YangData_RwVnfr_VnfrConsole_Vnfr_Vdur()
                    vdur_console.id = self._vdur_id
                    if console_url:
                        vdur_console.console_url = console_url
                    else:
                        vdur_console.console_url = 'none'
                    self._log.debug("Recevied console URL for vdu {} is {}".format(self._vdu_id,vdur_console))
                except openmano_client.InstanceStatusError as e:
                    self._log.error("Could not get NS instance console URL: %s",
                                    str(e))
                    vdur_console = RwVnfrYang.YangData_RwVnfr_VnfrConsole_Vnfr_Vdur()
                    vdur_console.id = self._vdur_id
                    vdur_console.console_url = 'none'

                xact_info.respond_xpath(rsp_code=rwdts.XactRspCode.ACK,
                                        xpath=self.vnfr_vdu_console_xpath,
                                        msg=vdur_console)
            else:
                #raise VnfRecordError("Not supported operation %s" % action)
                self._log.error("Not supported operation %s" % action)
                xact_info.respond_xpath(rsp_code=rwdts.XactRspCode.ACK)
                return

        self._log.debug("Registering for VNFR VDU using xpath: %s",
                        self.vnfr_vdu_console_xpath)
        hdl = rift.tasklets.DTS.RegistrationHandler(on_prepare=on_prepare,)
        with self._dts.group_create() as group:
            self._regh = group.register(xpath=self.vnfr_vdu_console_xpath,
                                        handler=hdl,
                                        flags=rwdts.Flag.PUBLISHER,
                                        )



class OpenmanoVnfr(object):
    def __init__(self, log, loop, cli_api, vnfr, nsd, ssh_key=None):
        self._log = log
        self._loop = loop
        self._cli_api = cli_api
        self._vnfr = vnfr
        self._vnfd_id = vnfr.vnfd.id

        self._vnf_id = None

        self._created = False

        self.nsd = nsd
        self._ssh_key = ssh_key

    @property
    def vnfd(self):
        return rift2openmano.RiftVNFD(self._vnfr.vnfd)

    @property
    def vnfr(self):
        return self._vnfr

    @property
    def rift_vnfd_id(self):
        return self._vnfd_id

    @property
    def openmano_vnfd_id(self):
        return self._vnf_id

    @property
    def openmano_vnfd(self):
        self._log.debug("Converting vnfd %s from rift to openmano", self.vnfd.id)
        openmano_vnfd = rift2openmano.rift2openmano_vnfd(self.vnfd, self.nsd)
        return openmano_vnfd

    @property
    def openmano_vnfd_yaml(self):
        return yaml.safe_dump(self.openmano_vnfd, default_flow_style=False)

    @asyncio.coroutine
    def create(self):
        self._log.debug("Creating openmano vnfd")
        openmano_vnfd = self.openmano_vnfd
        name = openmano_vnfd["vnf"]["name"]

        # If the name already exists, get the openmano vnfd id
        name_uuid_map = yield from self._loop.run_in_executor(
            None,
            self._cli_api.vnf_list,
        )

        if name in name_uuid_map:
            vnf_id = name_uuid_map[name]
            self._log.debug("Vnf already created.  Got existing openmano vnfd id: %s", vnf_id)
            self._vnf_id = vnf_id
            return

        self._vnf_id, _ = yield from self._loop.run_in_executor(
            None,
            self._cli_api.vnf_create,
            self.openmano_vnfd_yaml,
        )

        fpath = dump_openmano_descriptor(
            "{}_vnf".format(name),
            self.openmano_vnfd_yaml
        )

        self._log.debug("Dumped Openmano VNF descriptor to: %s", fpath)

        self._created = True

    def delete(self):
        if not self._created:
            return

        self._log.debug("Deleting openmano vnfd")
        if self._vnf_id is None:
            self._log.warning("Openmano vnf id not set.  Cannot delete.")
            return

        self._cli_api.vnf_delete(self._vnf_id)


class OpenmanoNSRecordState(Enum):
    """ Network Service Record State """
    # Make sure the values match with NetworkServiceRecordState
    INIT = 101
    INSTANTIATION_PENDING = 102
    RUNNING = 106
    SCALING_OUT = 107
    SCALING_IN = 108
    TERMINATE = 109
    TERMINATE_RCVD = 110
    TERMINATED = 114
    FAILED = 115
    VL_INSTANTIATE = 116
    VL_TERMINATE = 117


class OpenmanoNsr(object):
    TIMEOUT_SECS = 300
    INSTANCE_TERMINATE_TIMEOUT = 60

    def __init__(self, dts, log, loop, publisher, cli_api, http_api, nsd_msg,
                 nsr_config_msg, key_pairs, ssh_key, rift_vnfd_id=None ):
        self._log = log
        self._dts = dts
        self._loop = loop
        self._publisher = publisher
        self._cli_api = cli_api
        self._http_api = http_api

        self._nsd_msg = nsd_msg
        self._nsr_config_msg = nsr_config_msg
        self._vlrs = []
        self._vnfrs = []
        self._nsrs = {}
        self._vdur_console_handler = {}
        self._key_pairs = key_pairs
        self._ssh_key = ssh_key

        self._nsd_uuid = None
        self._nsr_uuid = None
        self._nsd_msg = nsd_msg

        self._nsr_msg = None

        self._created = False

        self._monitor_task = None
        self._rift_vnfd_id = rift_vnfd_id
        self._state = OpenmanoNSRecordState.INIT

    @property
    def nsd(self):
        return rift2openmano.RiftNSD(self._nsd_msg)

    @property
    def rift_vnfd_id(self):
        return self._rift_vnfd_id

    @property
    def nsd_msg(self):
        return self._nsd_msg

    @property
    def nsr_config_msg(self):
        return self._nsr_config_msg


    @property
    def vnfds(self):
        return {v.rift_vnfd_id: v.vnfd for v in self._vnfrs}

    @property
    def vnfr_ids(self):
        return {v.rift_vnfd_id: v.openmano_vnfd_id for v in self._vnfrs}

    @property
    def vnfrs(self):
        return self._vnfrs

    @property
    def key_pairs(self):
        return self._key_pairs

    @property
    def nsr_msg(self):
        return self._nsr_msg

    @property
    def vlrs(self):
        return self._vlrs

    @property
    def openmano_nsd_yaml(self):
        self._log.debug("Converting nsd %s from rift to openmano", self.nsd.id)
        openmano_nsd = rift2openmano.rift2openmano_nsd(self.nsd, self.vnfds,self.vnfr_ids)
        return yaml.safe_dump(openmano_nsd, default_flow_style=False)

    @property
    def openmano_scaling_yaml(self):
        self._log.debug("Creating Openmano Scaling Descriptor %s")
        try:
            openmano_vnfd_nsd = rift2openmano.rift2openmano_vnfd_nsd(self.nsd, self.vnfds, self.vnfr_ids, self._rift_vnfd_id)
            return yaml.safe_dump(openmano_vnfd_nsd, default_flow_style=False)
        except Exception as e:
            self._log.exception("Scaling Descriptor Exception: %s", str(e))

    def get_ssh_key_pairs(self):
        cloud_config = {}
        key_pairs = list()
        for authorized_key in self._nsr_config_msg.ssh_authorized_key:
            self._log.debug("Key pair ref present is %s",authorized_key.key_pair_ref)
            if authorized_key.key_pair_ref in  self._key_pairs:
                key_pairs.append(self._key_pairs[authorized_key.key_pair_ref].key)

        for authorized_key in self._nsd_msg.key_pair:
            self._log.debug("Key pair  NSD  is %s",authorized_key)
            key_pairs.append(authorized_key.key)

        if self._ssh_key['public_key']:
            self._log.debug("Pub key  NSD  is %s", self._ssh_key['public_key'])
            key_pairs.append(self._ssh_key['public_key'])

        if key_pairs:
            cloud_config["key-pairs"] = key_pairs

        users = list()
        for user_entry in self._nsr_config_msg.user:
            self._log.debug("User present is  %s",user_entry)
            user = {}
            user["name"] = user_entry.name
            user["key-pairs"] = list()
            for ssh_key in user_entry.ssh_authorized_key:
                if ssh_key.key_pair_ref in  self._key_pairs:
                    user["key-pairs"].append(self._key_pairs[ssh_key.key_pair_ref].key)
            users.append(user)

        for user_entry in self._nsd_msg.user:
            self._log.debug("User present in NSD is  %s",user_entry)
            user = {}
            user["name"] = user_entry.name
            user["key-pairs"] = list()
            for ssh_key in user_entry.key_pair:
                user["key-pairs"].append(ssh_key.key)
            users.append(user)

        if users:
            cloud_config["users"] = users

        self._log.debug("Cloud config formed is %s",cloud_config)
        return cloud_config


    @property
    def openmano_instance_create_yaml(self):
        self._log.debug("Creating instance-scenario-create input file for nsd %s with name %s", self.nsd.id, self._nsr_config_msg.name)
        openmano_instance_create = {}
        openmano_instance_create["name"] = self._nsr_config_msg.name
        openmano_instance_create["description"] = self._nsr_config_msg.description
        openmano_instance_create["scenario"] = self._nsd_uuid

        cloud_config = self.get_ssh_key_pairs()
        if cloud_config:
            openmano_instance_create["cloud-config"] = cloud_config
        if self._nsr_config_msg.has_field("om_datacenter"):
            openmano_instance_create["datacenter"] = self._nsr_config_msg.om_datacenter
        openmano_instance_create["vnfs"] = {}
        for vnfr in self._vnfrs:
            if "om_datacenter" in vnfr.vnfr.vnfr_msg:
                vnfr_name = vnfr.vnfr.vnfd.name + "__" + str(vnfr.vnfr.vnfr_msg.member_vnf_index_ref)
                openmano_instance_create["vnfs"][vnfr_name] = {"datacenter": vnfr.vnfr.vnfr_msg.om_datacenter}
        openmano_instance_create["networks"] = {}
        for vld_msg in self._nsd_msg.vld:
            openmano_instance_create["networks"][vld_msg.name] = {}
            openmano_instance_create["networks"][vld_msg.name]["sites"] = list()
            for vlr in self._vlrs:
                if vlr.vld_msg.name == vld_msg.name:
                    self._log.debug("Received VLR name %s, VLR DC: %s for VLD: %s",vlr.vld_msg.name,
                                    vlr.om_datacenter_name,vld_msg.name)
                    #network["vim-network-name"] = vld_msg.name
                    network = {}
                    ip_profile = {}
                    if vld_msg.vim_network_name:
                        network["netmap-use"] = vld_msg.vim_network_name
                    elif vlr._ip_profile and vlr._ip_profile.has_field("ip_profile_params"):
                        ip_profile_params = vlr._ip_profile.ip_profile_params
                        if ip_profile_params.ip_version == "ipv6":
                            ip_profile['ip-version'] = "IPv6"
                        else:
                            ip_profile['ip-version'] = "IPv4"
                        if ip_profile_params.has_field('subnet_address'):
                            ip_profile['subnet-address'] = ip_profile_params.subnet_address
                        if ip_profile_params.has_field('gateway_address'):
                            ip_profile['gateway-address'] = ip_profile_params.gateway_address
                        if ip_profile_params.has_field('dns_server') and len(ip_profile_params.dns_server) > 0:
                            ip_profile['dns-address'] =  ip_profile_params.dns_server[0].address
                        if ip_profile_params.has_field('dhcp_params'):
                            ip_profile['dhcp'] = {}
                            ip_profile['dhcp']['enabled'] = ip_profile_params.dhcp_params.enabled
                            ip_profile['dhcp']['start-address'] = ip_profile_params.dhcp_params.start_address
                            ip_profile['dhcp']['count'] = ip_profile_params.dhcp_params.count
                    else:
                        network["netmap-create"] = vlr.name
                    if vlr.om_datacenter_name:
                        network["datacenter"] = vlr.om_datacenter_name
                    elif vld_msg.has_field("om_datacenter"):
                        network["datacenter"] = vld_msg.om_datacenter
                    elif "datacenter" in openmano_instance_create:
                        network["datacenter"] = openmano_instance_create["datacenter"]
                    if network:
                        openmano_instance_create["networks"][vld_msg.name]["sites"].append(network)
                    if ip_profile:
                        openmano_instance_create["networks"][vld_msg.name]['ip-profile'] = ip_profile

        return yaml.safe_dump(openmano_instance_create, default_flow_style=False,width=1000)

    @property
    def scaling_instance_create_yaml(self, scaleout=False):
        self._log.debug("Creating instance-scenario-create input file for nsd %s with name %s", self.nsd.id, self._nsr_config_msg.name+"scal1")
        scaling_instance_create = {}
        for group_list in self._nsd_msg.scaling_group_descriptor:
            scaling_instance_create["name"] = self._nsr_config_msg.name + "__"+group_list.name
            if scaleout:
                scaling_instance_create["scenario"] = self._nsd_uuid + "__" +group_list.name
            else:
                scaling_instance_create["scenario"] = self._nsd_uuid
        scaling_instance_create["description"] = self._nsr_config_msg.description


        if self._nsr_config_msg.has_field("om_datacenter"):
            scaling_instance_create["datacenter"] = self._nsr_config_msg.om_datacenter
        scaling_instance_create["vnfs"] = {}
        for vnfr in self._vnfrs:
            if "om_datacenter" in vnfr.vnfr.vnfr_msg:
                vnfr_name = vnfr.vnfr.vnfd.name + "__" + str(vnfr.vnfr.vnfr_msg.member_vnf_index_ref)
                scaling_instance_create["vnfs"][vnfr_name] = {"datacenter": vnfr.vnfr.vnfr_msg.om_datacenter}
        scaling_instance_create["networks"] = {}
        for vld_msg in self._nsd_msg.vld:
            scaling_instance_create["networks"][vld_msg.name] = {}
            scaling_instance_create["networks"][vld_msg.name]["sites"] = list()
            for vlr in self._vlrs:
                if vlr.vld_msg.name == vld_msg.name:
                    self._log.debug("Received VLR name %s, VLR DC: %s for VLD: %s",vlr.vld_msg.name,
                                    vlr.om_datacenter_name,vld_msg.name)
                    #network["vim-network-name"] = vld_msg.name
                    network = {}
                    ip_profile = {}
                    if vld_msg.vim_network_name:
                        network["netmap-use"] = vld_msg.vim_network_name
                    #else:
                    #    network["netmap-create"] = vlr.name
                    if vlr.om_datacenter_name:
                        network["datacenter"] = vlr.om_datacenter_name
                    elif vld_msg.has_field("om_datacenter"):
                        network["datacenter"] = vld_msg.om_datacenter
                    elif "datacenter" in scaling_instance_create:
                        network["datacenter"] = scaling_instance_create["datacenter"]
                    if network:
                        scaling_instance_create["networks"][vld_msg.name]["sites"].append(network)

        return yaml.safe_dump(scaling_instance_create, default_flow_style=False, width=1000)

    @asyncio.coroutine
    def add_vlr(self, vlr):
        self._vlrs.append(vlr)
        yield from self._publisher.publish_vlr(None, vlr.vlr_msg)
        yield from asyncio.sleep(1, loop=self._loop)

    @asyncio.coroutine
    def remove_vlr(self, vlr):
        if vlr in self._vlrs:
            self._vlrs.remove(vlr)
            yield from self._publisher.unpublish_vlr(None, vlr.vlr_msg)
        yield from asyncio.sleep(1, loop=self._loop)

    @asyncio.coroutine
    def delete_vlr(self, vlr):
        if vlr in self._vlrs:
            self._vlrs.remove(vlr)
            if not  vlr.vld_msg.vim_network_name:
                yield from self._loop.run_in_executor(
                    None,
                    self._cli_api.ns_vim_network_delete,
                    vlr.name,
                    vlr.om_datacenter_name)
            yield from self._publisher.unpublish_vlr(None, vlr.vlr_msg)
        yield from asyncio.sleep(1, loop=self._loop)

    @asyncio.coroutine
    def add_vnfr(self, vnfr):
        vnfr = OpenmanoVnfr(self._log, self._loop, self._cli_api, vnfr,
                            nsd=self.nsd, ssh_key=self._ssh_key)
        yield from vnfr.create()
        self._vnfrs.append(vnfr)

    @asyncio.coroutine
    def add_nsr(self, nsr, vnfr):
        self._nsrs[vnfr.id] = nsr

    def delete(self):
        if not self._created:
            self._log.debug("NSD wasn't created.  Skipping delete.")
            return

        self._log.debug("Deleting openmano nsr")
        self._cli_api.ns_delete(self._nsd_uuid)

        self._log.debug("Deleting openmano vnfrs")
        deleted_vnf_id_list = []
        for vnfr in self._vnfrs:
            if vnfr.vnfr.vnfd.id not in deleted_vnf_id_list:
                vnfr.delete()
                deleted_vnf_id_list.append(vnfr.vnfr.vnfd.id)


    @asyncio.coroutine
    def create(self):
        self._log.debug("Creating openmano scenario")
        name_uuid_map = yield from self._loop.run_in_executor(
            None,
            self._cli_api.ns_list,
        )

        if self._nsd_msg.name in name_uuid_map:
            self._log.debug("Found existing openmano scenario")
            self._nsd_uuid = name_uuid_map[self._nsd_msg.name]
            return


        # Use the nsd uuid as the scenario name to rebind to existing
        # scenario on reload or to support muliple instances of the name
        # nsd
        self._nsd_uuid, _ = yield from self._loop.run_in_executor(
            None,
            self._cli_api.ns_create,
            self.openmano_nsd_yaml,
            self._nsd_msg.name
        )
        fpath = dump_openmano_descriptor(
            "{}_nsd".format(self._nsd_msg.name),
            self.openmano_nsd_yaml,
        )

        self._log.debug("Dumped Openmano NS descriptor to: %s", fpath)

        self._created = True

    @asyncio.coroutine
    def scaling_scenario_create(self):
        self._log.debug("Creating scaling openmano scenario")
        self._nsd_uuid, _ = yield from self._loop.run_in_executor(
            None,
            self._cli_api.ns_create,
            self.openmano_scaling_yaml,

        )
        fpath = dump_openmano_descriptor(
            "{}_sgd".format(self._nsd_msg.name),
            self.scaling_instance_create_yaml,
        )

    @asyncio.coroutine
    def instance_monitor_task(self):
        self._log.debug("Starting Instance monitoring task")

        start_time = time.time()
        active_vnfs = []

        while True:
            yield from asyncio.sleep(1, loop=self._loop)

            try:
                instance_resp_json = yield from self._loop.run_in_executor(
                    None,
                    self._http_api.get_instance,
                    self._nsr_uuid,
                )

                self._log.debug("Got instance response: %s for NSR ID %s",
                                instance_resp_json,
                                self._nsr_uuid)

            except openmano_client.InstanceStatusError as e:
                self._log.error("Could not get NS instance status: %s", str(e))
                continue

            def all_vms_active(vnf):
                for vm in vnf["vms"]:
                    vm_status = vm["status"]
                    vm_uuid = vm["uuid"]
                    if vm_status != "ACTIVE":
                        self._log.debug("VM is not yet active: %s (status: %s)", vm_uuid, vm_status)
                        return False

                return True

            def any_vm_active_nomgmtip(vnf):
                for vm in vnf["vms"]:
                    vm_status = vm["status"]
                    vm_uuid = vm["uuid"]
                    if vm_status != "ACTIVE":
                        self._log.debug("VM is not yet active: %s (status: %s)", vm_uuid, vm_status)
                        return False

                return True

            def any_vms_error(vnf):
                for vm in vnf["vms"]:
                    vm_status = vm["status"]
                    vm_vim_info = vm["vim_info"]
                    vm_uuid = vm["uuid"]
                    if vm_status == "ERROR":
                        self._log.error("VM Error: %s (vim_info: %s)", vm_uuid, vm_vim_info)
                        return True

                return False

            def get_vnf_ip_address(vnf):
                if "ip_address" in vnf:
                    return vnf["ip_address"].strip()
                return None

            def get_vnf_mac_address(vnf):
                if "mac_address" in vnf:
                    return vnf["mac_address"].strip()
                return None

            def get_ext_cp_info(vnf):
                cp_info_list = []
                for vm in vnf["vms"]:
                    if "interfaces" not in vm:
                        continue

                    for intf in vm["interfaces"]:
                        if "external_name" not in intf:
                            continue

                        if not intf["external_name"]:
                            continue

                        ip_address = intf["ip_address"]
                        if ip_address is None:
                            ip_address = "0.0.0.0"

                        mac_address = intf["mac_address"]
                        if mac_address is None:
                            mac_address="00:00:00:00:00:00"

                        cp_info_list.append((intf["external_name"], ip_address, mac_address))

                return cp_info_list

            def get_vnf_status(vnfr):
                # When we create an openmano descriptor we use <name>__<idx>
                # to come up with openmano constituent VNF name.  Use this
                # knowledge to map the vnfr back.
                openmano_vnfr_suffix = "__{}".format(
                    vnfr.vnfr.vnfr_msg.member_vnf_index_ref
                )

                for vnf in instance_resp_json["vnfs"]:
                    if vnf["vnf_name"].endswith(openmano_vnfr_suffix):
                        return vnf

                self._log.warning("Could not find vnf status with name that ends with: %s",
                                  openmano_vnfr_suffix)
                return None

            for vnfr in self._vnfrs:
                if vnfr in active_vnfs:
                    # Skipping, so we don't re-publish the same VNF message.
                    continue

                vnfr_msg = vnfr.vnfr.vnfr_msg.deep_copy()
                vnfr_msg.operational_status = "init"

                try:
                    vnf_status = get_vnf_status(vnfr)
                    self._log.debug("Found VNF status: %s", vnf_status)
                    if vnf_status is None:
                        self._log.error("Could not find VNF status from openmano")
                        self._state = OpenmanoNSRecordState.FAILED
                        vnfr_msg.operational_status = "failed"
                        yield from self._publisher.publish_vnfr(None, vnfr_msg)
                        return

                    # If there was a VNF that has a errored VM, then just fail the VNF and stop monitoring.
                    if any_vms_error(vnf_status):
                        self._log.debug("VM was found to be in error state.  Marking as failed.")
                        self._state = OpenmanoNSRecordState.FAILED
                        vnfr_msg.operational_status = "failed"
                        yield from self._publisher.publish_vnfr(None, vnfr_msg)
                        return

                    if (time.time() - start_time) > OpenmanoNsr.TIMEOUT_SECS:
                        self._log.error("NSR timed out before reaching running state")
                        self._state = OpenmanoNSRecordState.FAILED
                        vnfr_msg.operational_status = "failed"
                        yield from self._publisher.publish_vnfr(None, vnfr_msg)
                        return

                    if all_vms_active(vnf_status):
                        vnf_ip_address = get_vnf_ip_address(vnf_status)
                        vnf_mac_address = get_vnf_mac_address(vnf_status)

                        if vnf_ip_address is None:
                            self._log.warning("No IP address obtained "
                                              "for VNF: {}, will retry.".format(
                                vnf_status['vnf_name']))
                            continue

                        self._log.debug("All VMs in VNF are active.  Marking as running.")
                        vnfr_msg.operational_status = "running"

                        self._log.debug("Got VNF ip address: %s, mac-address: %s",
                                        vnf_ip_address, vnf_mac_address)
                        vnfr_msg.mgmt_interface.ip_address = vnf_ip_address
                        vnfr_msg.mgmt_interface.ssh_key.public_key = \
                                                    vnfr._ssh_key['public_key']
                        vnfr_msg.mgmt_interface.ssh_key.private_key_file = \
                                                    vnfr._ssh_key['private_key']
                        vnfr_msg.vnf_configuration.config_access.mgmt_ip_address = vnf_ip_address


                        for vm in vnf_status["vms"]:
                            if vm["uuid"] not in self._vdur_console_handler:
                                vdur_console_handler = VnfrConsoleOperdataDtsHandler(self._dts, self._log, self._loop,
                                                                                     self, vnfr_msg.id,vm["uuid"],vm["name"])
                                yield from vdur_console_handler.register()
                                self._vdur_console_handler[vm["uuid"]] = vdur_console_handler

                            vdur_msg = vnfr_msg.vdur.add()
                            vdur_msg.vim_id = vm["vim_vm_id"]
                            vdur_msg.id = vm["uuid"]

                        # Add connection point information for the config manager
                        cp_info_list = get_ext_cp_info(vnf_status)
                        for (cp_name, cp_ip, cp_mac_addr) in cp_info_list:
                            cp = vnfr_msg.connection_point.add()
                            cp.name = cp_name
                            cp.short_name = cp_name
                            cp.ip_address = cp_ip
                            cp.mac_address = cp_mac_addr

                        yield from self._publisher.publish_vnfr(None, vnfr_msg)
                        active_vnfs.append(vnfr)

                except Exception as e:
                    vnfr_msg.operational_status = "failed"
                    self._state = OpenmanoNSRecordState.FAILED
                    yield from self._publisher.publish_vnfr(None, vnfr_msg)
                    self._log.exception("Caught exception publishing vnfr info: %s", str(e))
                    return

            if len(active_vnfs) == len(self._vnfrs):
                self._state = OpenmanoNSRecordState.RUNNING
                self._log.info("All VNF's are active.  Exiting NSR monitoring task")
                return

    @asyncio.coroutine
    def deploy(self,nsr_msg):
        if self._nsd_uuid is None:
            raise ValueError("Cannot deploy an uncreated nsd")

        self._log.debug("Deploying openmano instance scenario")

        name_uuid_map = yield from self._loop.run_in_executor(
            None,
            self._cli_api.ns_instance_list,
        )

        if self._nsr_config_msg.name in name_uuid_map:
            self._log.debug("Found existing instance with nsr name: %s", self._nsr_config_msg.name)
            self._nsr_uuid = name_uuid_map[self._nsr_config_msg.name]
        else:
            self._nsr_msg = nsr_msg
            fpath = dump_openmano_descriptor(
                "{}_instance_sce_create".format(self._nsr_config_msg.name),
                self.openmano_instance_create_yaml,
            )
            self._log.debug("Dumped Openmano instance Scenario Cretae to: %s", fpath)

            self._nsr_uuid = yield from self._loop.run_in_executor(
                None,
                self._cli_api.ns_instance_scenario_create,
                self.openmano_instance_create_yaml)

        self._state = OpenmanoNSRecordState.INSTANTIATION_PENDING

        self._monitor_task = asyncio.ensure_future(
            self.instance_monitor_task(), loop=self._loop
        )

    @asyncio.coroutine
    def deploy_scaling(self, nsr_msg, rift_vnfd_id):
        self._log.debug("Deploying Scaling instance scenario")
        self._nsr_msg = nsr_msg
        self._rift_vnfd_id = rift_vnfd_id
        fpath = dump_openmano_descriptor(
            "{}_scale_instance".format(self._nsr_config_msg.name),
            self.scaling_instance_create_yaml
            )
        self._nsr_uuid = yield from self._loop.run_in_executor(
                None,
                self._cli_api.ns_instance_scenario_create,
                self.scaling_instance_create_yaml)

        self._state = OpenmanoNSRecordState.INSTANTIATION_PENDING

        self._monitor_task = asyncio.ensure_future(
            self.instance_monitor_task(), loop=self._loop
        )

        self._state = OpenmanoNSRecordState.INIT


    def terminate(self):
        if self._nsr_uuid is None:
            start_time = time.time()
            while ((time.time() - start_time) < OpenmanoNsr.INSTANCE_TERMINATE_TIMEOUT) and (self._nsr_uuid is None):
                time.sleep(5)
                self._log.warning("Waiting for nsr to get instatiated")
            if self._nsr_uuid is None:
                self._log.warning("Cannot terminate an un-instantiated nsr")
                return

        if self._monitor_task is not None:
            self._monitor_task.cancel()
            self._monitor_task = None

        self._log.debug("Terminating openmano nsr")
        self._cli_api.ns_terminate(self._nsr_uuid)

    @asyncio.coroutine
    def create_vlr(self,vlr):
        self._log.debug("Creating openmano vim network VLR name %s, VLR DC: %s",vlr.vld_msg.name,
                        vlr.om_datacenter_name)
        net_create = {}
        net = {}
        net['name'] = vlr.name
        net['shared'] = True
        net['type'] = 'bridge'
        self._log.debug("Received ip profile is %s",vlr._ip_profile)
        if vlr._ip_profile and vlr._ip_profile.has_field("ip_profile_params"):
            ip_profile_params = vlr._ip_profile.ip_profile_params
            ip_profile = {}
            if ip_profile_params.ip_version == "ipv6":
                ip_profile['ip_version'] = "IPv6"
            else:
                ip_profile['ip_version'] = "IPv4"
            if ip_profile_params.has_field('subnet_address'):
                ip_profile['subnet_address'] = ip_profile_params.subnet_address
            if ip_profile_params.has_field('gateway_address'):
                ip_profile['gateway_address'] = ip_profile_params.gateway_address
            if ip_profile_params.has_field('dns_server') and len(ip_profile_params.dns_server) > 0:
                ip_profile['dns_address'] =  ip_profile_params.dns_server[0].address
            if ip_profile_params.has_field('dhcp_params'):
                ip_profile['dhcp_enabled'] = ip_profile_params.dhcp_params.enabled
                ip_profile['dhcp_start_address'] = ip_profile_params.dhcp_params.start_address
                ip_profile['dhcp_count'] = ip_profile_params.dhcp_params.count
            net['ip_profile'] = ip_profile
        net_create["network"]= net

        net_create_msg = yaml.safe_dump(net_create,default_flow_style=False)
        fpath = dump_openmano_descriptor(
            "{}_vim_net_create_{}".format(self._nsr_config_msg.name,vlr.name),
            net_create_msg)
        self._log.debug("Dumped Openmano VIM Net create to: %s", fpath)

        vim_network_uuid = yield from self._loop.run_in_executor(
            None,
            self._cli_api.ns_vim_network_create,
            net_create_msg,
            vlr.om_datacenter_name)
        self._vlrs.append(vlr)



class OpenmanoNsPlugin(rwnsmplugin.NsmPluginBase):
    """
        RW Implentation of the NsmPluginBase
    """
    def __init__(self, dts, log, loop, publisher, ro_account):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._publisher = publisher

        self._cli_api = None
        self._http_api = None
        self._openmano_nsrs = {}
        self._vnfr_uptime_tasks = {}

        self._set_ro_account(ro_account)

    def _set_ro_account(self, ro_account):
        self._log.debug("Setting openmano plugin cloud account: %s", ro_account)
        self._cli_api = openmano_client.OpenmanoCliAPI(
            self.log,
            ro_account.openmano.host,
            ro_account.openmano.port,
            ro_account.openmano.tenant_id,
        )

        self._http_api = openmano_client.OpenmanoHttpAPI(
            self.log,
            ro_account.openmano.host,
            ro_account.openmano.port,
            ro_account.openmano.tenant_id,
        )

    def set_state(self, nsr_id, state):
        # Currently we update only during terminate to
        # decide how to handle VL terminate
        if state.value == OpenmanoNSRecordState.TERMINATE.value:
            self._openmano_nsrs[nsr_id]._state = \
                [member.value for name, member in \
                 OpenmanoNSRecordState.__members__.items() \
                 if member.value == state.value]

    def create_nsr(self, nsr_config_msg, nsd_msg, key_pairs=None, ssh_key=None):
        """
        Create Network service record
        """
        openmano_nsr = OpenmanoNsr(
                self._dts,
                self._log,
                self._loop,
                self._publisher,
                self._cli_api,
                self._http_api,
                nsd_msg,
                nsr_config_msg,
                key_pairs,
                ssh_key,
                )
        self._openmano_nsrs[nsr_config_msg.id] = openmano_nsr

    @asyncio.coroutine
    def deploy(self, nsr_msg):
        self._log.debug("Received NSR Deploy msg : %s", nsr_msg)
        openmano_nsr = self._openmano_nsrs[nsr_msg.ns_instance_config_ref]
        yield from openmano_nsr.create()
        yield from openmano_nsr.deploy(nsr_msg)

    @asyncio.coroutine
    def instantiate_ns(self, nsr, xact):
        """
        Instantiate NSR with the passed nsr id
        """
        yield from nsr.instantiate(xact)

    @asyncio.coroutine
    def instantiate_vnf(self, nsr, vnfr, scaleout=False):
        """
        Instantiate NSR with the passed nsr id
        """
        openmano_nsr = self._openmano_nsrs[nsr.id]
        if scaleout:
            openmano_vnf_nsr = OpenmanoNsr(
                self._dts,
                self._log,
                self._loop,
                self._publisher,
                self._cli_api,
                self._http_api,
                openmano_nsr.nsd_msg,
                openmano_nsr.nsr_config_msg,
                openmano_nsr.key_pairs,
                None,
                rift_vnfd_id=vnfr.vnfd.id,
            )
            for vlr in openmano_nsr.vlrs:
                yield from openmano_vnf_nsr.add_vlr(vlr)
            try:
                yield from openmano_nsr.add_nsr(openmano_vnf_nsr, vnfr)
            except Exception as e:
                self.log.exception(str(e))
            try:
                yield from openmano_vnf_nsr.add_vnfr(vnfr)
            except Exception as e:
                self.log.exception(str(e))
            try:
                yield from openmano_vnf_nsr.scaling_scenario_create()
            except Exception as e:
                self.log.exception(str(e))
            try:
                yield from openmano_vnf_nsr.deploy_scaling(openmano_vnf_nsr.nsr_msg, vnfr.id)
            except Exception as e:
                self.log.exception(str(e))
        else:
            yield from openmano_nsr.add_vnfr(vnfr)

        # Mark the VNFR as running
        # TODO: Create a task to monitor nsr/vnfr status
        vnfr_msg = vnfr.vnfr_msg.deep_copy()
        vnfr_msg.operational_status = "init"

        self._log.debug("Attempting to publish openmano vnf: %s", vnfr_msg)
        with self._dts.transaction() as xact:
            yield from self._publisher.publish_vnfr(xact, vnfr_msg)
        self._log.debug("Creating a task to update uptime for vnfr: %s", vnfr.id)
        self._vnfr_uptime_tasks[vnfr.id] = self._loop.create_task(self.vnfr_uptime_update(vnfr))

    def update_vnfr(self, vnfr):
        vnfr_msg = vnfr.vnfr_msg.deep_copy()
        self._log.debug("Attempting to publish openmano vnf: %s", vnfr_msg)
        with self._dts.transaction() as xact:
            yield from self._publisher.publish_vnfr(xact, vnfr_msg)

    def vnfr_uptime_update(self, vnfr):
        try:
            vnfr_ = RwVnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr.from_dict({'id': vnfr.id})
            while True:
                vnfr_.uptime = int(time.time()) - vnfr._create_time
                yield from self._publisher.publish_vnfr(None, vnfr_)
                yield from asyncio.sleep(2, loop=self._loop)
        except asyncio.CancelledError:
            self._log.debug("Received cancellation request for vnfr_uptime_update task")

    @asyncio.coroutine
    def instantiate_vl(self, nsr, vlr):
        """
        Instantiate NSR with the passed nsr id
        """
        self._log.debug("Received instantiate VL for NSR {}; VLR {}".format(nsr.id,vlr))
        openmano_nsr = self._openmano_nsrs[nsr.id]
        if openmano_nsr._state == OpenmanoNSRecordState.RUNNING:
            yield from openmano_nsr.create_vlr(vlr)
            yield from self._publisher.publish_vlr(None, vlr.vlr_msg)
        else:
            yield from openmano_nsr.add_vlr(vlr)

    @asyncio.coroutine
    def terminate_ns(self, nsr):
        """
        Terminate the network service
        """
        nsr_id = nsr.id
        openmano_nsr = self._openmano_nsrs[nsr_id]

        for _,handler in openmano_nsr._vdur_console_handler.items():
            handler._regh.deregister()

        yield from self._loop.run_in_executor(
               None,
               self.terminate,
               openmano_nsr,
               )

        with self._dts.transaction() as xact:
            for vnfr in openmano_nsr.vnfrs:
                self._log.debug("Unpublishing VNFR: %s", vnfr.vnfr.vnfr_msg)
                yield from self._publisher.unpublish_vnfr(xact, vnfr.vnfr.vnfr_msg)

        del self._openmano_nsrs[nsr_id]

    def terminate(self, openmano_nsr):
        openmano_nsr.terminate()
        openmano_nsr.delete()

    @asyncio.coroutine
    def terminate_vnf(self, vnfr):
        """
        Terminate the network service
        """
        if vnfr.id in self._vnfr_uptime_tasks:
            self._vnfr_uptime_tasks[vnfr.id].cancel()

    @asyncio.coroutine
    def terminate_vl(self, vlr):
        """
        Terminate the virtual link
        """
        self._log.debug("Received terminate VL for VLR {}".format(vlr))
        openmano_nsr = self._openmano_nsrs[vlr._nsr_id]
        if openmano_nsr._state == OpenmanoNSRecordState.RUNNING:
            yield from openmano_nsr.delete_vlr(vlr)
        else:
            yield from openmano_nsr.remove_vlr(vlr)
