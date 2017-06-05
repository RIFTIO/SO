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
import collections
import enum
import logging
import uuid
import time
import os.path
import re
import shutil
import sys
import yaml

import gi
gi.require_version('RwDts', '1.0')
gi.require_version('RwVnfrYang', '1.0')
gi.require_version('RwVnfmYang', '1.0')
gi.require_version('RwVlrYang', '1.0')
gi.require_version('RwManifestYang', '1.0')
gi.require_version('RwBaseYang', '1.0')
gi.require_version('RwResourceMgrYang', '1.0')

from gi.repository import (
    RwDts as rwdts,
    RwVnfrYang,
    RwVnfmYang,
    RwVlrYang,
    VnfrYang,
    RwManifestYang,
    RwBaseYang,
    RwResourceMgrYang,
    ProtobufC,
)

import rift.tasklets
import rift.package.store
import rift.package.cloud_init
import rift.package.script
import rift.mano.dts as mano_dts
import rift.mano.utils.short_name as mano_short_name
from . import subscriber

VCP_FIELDS = ['name', 'id', 'connection_point_id', 'static_ip_address', 'type_yang', 'ip_address', 'mac_address']

class VMResourceError(Exception):
    """ VM resource Error"""
    pass


class VnfRecordError(Exception):
    """ VNF record instatiation failed"""
    pass


class VduRecordError(Exception):
    """ VDU record instatiation failed"""
    pass


class NotImplemented(Exception):
    """Not implemented """
    pass


class VnfrRecordExistsError(Exception):
    """VNFR record already exist with the same VNFR id"""
    pass


class InternalVirtualLinkRecordError(Exception):
    """Internal virtual link record error"""
    pass


class VDUImageNotFound(Exception):
    """VDU Image not found error"""
    pass


class VirtualDeploymentUnitRecordError(Exception):
    """VDU Instantiation failed"""
    pass


class VMNotReadyError(Exception):
    """ VM Not yet received from resource manager """
    pass


class VDURecordNotFound(Exception):
    """ Could not find a VDU record """
    pass


class VirtualNetworkFunctionRecordDescNotFound(Exception):
    """ Cannot find Virtual Network Function Record Descriptor """
    pass


class VirtualNetworkFunctionDescriptorError(Exception):
    """ Virtual Network Function Record Descriptor Error """
    pass


class VirtualNetworkFunctionDescriptorNotFound(Exception):
    """ Virtual Network Function Record Descriptor Not Found """
    pass


class VirtualNetworkFunctionRecordNotFound(Exception):
    """ Virtual Network Function Record Not Found """
    pass


class VirtualNetworkFunctionDescriptorRefCountExists(Exception):
    """ Virtual Network Funtion Descriptor reference count exists """
    pass


class VnfrInstantiationFailed(Exception):
    """ Virtual Network Funtion Instantiation failed"""
    pass


class VNFMPlacementGroupError(Exception):
    """ VNF placement group Error """
    pass


class VlrError(Exception):
    """ Virtual Link Record Error """
    pass


class VirtualNetworkFunctionRecordState(enum.Enum):
    """ VNFR state """
    INIT = 1
    VL_INIT_PHASE = 2
    VM_INIT_PHASE = 3
    READY = 4
    TERMINATE = 5
    VL_TERMINATE_PHASE = 6
    VDU_TERMINATE_PHASE = 7
    TERMINATED = 7
    FAILED = 10


class VDURecordState(enum.Enum):
    """VDU record state """
    INIT = 1
    INSTANTIATING = 2
    RESOURCE_ALLOC_PENDING = 3
    READY = 4
    TERMINATING = 5
    TERMINATED = 6
    FAILED = 10


class VcsComponent(object):
    """ VCS Component within the VNF descriptor """
    def __init__(self, dts, log, loop, cluster_name, vcs_handler, component, mangled_name):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._component = component
        self._cluster_name = cluster_name
        self._vcs_handler = vcs_handler
        self._mangled_name = mangled_name

    @staticmethod
    def mangle_name(component_name, vnf_name, vnfd_id):
        """ mangled  component name """
        return vnf_name + ":" + component_name + ":" + vnfd_id

    @property
    def name(self):
        """ name of this component"""
        return self._mangled_name

    @property
    def path(self):
        """ The path for this object """
        return("D,/rw-manifest:manifest" +
               "/rw-manifest:operational-inventory" +
               "/rw-manifest:component" +
               "[rw-manifest:component-name = '{}']").format(self.name)

    @property
    def instance_xpath(self):
        """ The path for this object """
        return("D,/rw-base:vcs" +
               "/instances" +
               "/instance" +
               "[instance-name = '{}']".format(self._cluster_name))

    @property
    def start_comp_xpath(self):
        """ start component xpath """
        return (self.instance_xpath +
                "/child-n[instance-name = 'START-REQ']")

    def get_start_comp_msg(self, ip_address):
        """ start this component """
        start_msg = RwBaseYang.VcsInstance_Instance_ChildN()
        start_msg.instance_name = 'START-REQ'
        start_msg.component_name = self.name
        start_msg.admin_command = "START"
        start_msg.ip_address = ip_address

        return start_msg

    @property
    def msg(self):
        """ Returns the message for this vcs component"""

        vcs_comp_dict = self._component.as_dict()

        def mangle_comp_names(comp_dict):
            """ mangle component name  with VNF name, id"""
            for key, val in comp_dict.items():
                if isinstance(val, dict):
                    comp_dict[key] = mangle_comp_names(val)
                elif isinstance(val, list):
                    i = 0
                    for ent in val:
                        if isinstance(ent, dict):
                            val[i] = mangle_comp_names(ent)
                        else:
                            val[i] = ent
                        i += 1
                elif key == "component_name":
                    comp_dict[key] = VcsComponent.mangle_name(val,
                                                              self._vnfd_name,
                                                              self._vnfd_id)
            return comp_dict

        mangled_dict = mangle_comp_names(vcs_comp_dict)
        msg = RwManifestYang.OpInventory_Component.from_dict(mangled_dict)
        return msg

    @asyncio.coroutine
    def publish(self, xact):
        """ Publishes the VCS component """
        self._log.debug("Publishing the VcsComponent %s, path = %s comp = %s",
                        self.name, self.path, self.msg)
        yield from self._vcs_handler.publish(xact, self.path, self.msg)

    @asyncio.coroutine
    def start(self, xact, parent, ip_addr=None):
        """ Starts this VCS component """
        # ATTN RV - replace with block add
        start_msg = self.get_start_comp_msg(ip_addr)
        self._log.debug("starting component %s %s",
                        self.start_comp_xpath, start_msg)
        yield from self._dts.query_create(self.start_comp_xpath,
                                          0,
                                          start_msg)
        self._log.debug("started component %s, %s",
                        self.start_comp_xpath, start_msg)


class VirtualDeploymentUnitRecord(object):
    """  Virtual Deployment Unit Record """
    def __init__(self,
                 dts,
                 log,
                 loop,
                 vdud,
                 vnfr,
                 nsr_config,
                 mgmt_intf,
                 mgmt_network,
                 cloud_account_name,
                 vnfd_package_store,
                 vdur_id=None,
                 placement_groups=[]):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._vdud = vdud
        self._vnfr = vnfr
        self._nsr_config = nsr_config
        self._mgmt_intf = mgmt_intf
        self._cloud_account_name = cloud_account_name
        self._vnfd_package_store = vnfd_package_store
        self._mgmt_network = mgmt_network

        self._vdur_id = vdur_id or str(uuid.uuid4())
        self._int_intf = []
        self._ext_intf = []
        self._state = VDURecordState.INIT
        self._state_failed_reason = None
        self._request_id = str(uuid.uuid4())
        self._name = vnfr.name + "__" + vdud.id
        self._placement_groups = placement_groups
        self._rm_regh = None
        self._vm_resp = None
        self._vdud_cloud_init = None
        self._vdur_console_handler = VnfrConsoleOperdataDtsHandler(dts, log, loop, self._vnfr._vnfm, self._vnfr.vnfr_id, self._vdur_id,self.vdu_id)

    @asyncio.coroutine
    def vdu_opdata_register(self):
        yield from self._vdur_console_handler.register()

    def vm_cp_info(self, cp_name):
        """ Find the VM Connection info by connection point name """
        if self._vm_resp is not None:
            for conn_point in self._vm_resp.connection_points:
                if conn_point.name == cp_name:
                    return conn_point
        return None

    def cp_ip_addr(self, cp_name):
        """ Find ip address by connection point name """
        vm_cp_info = self.vm_cp_info(cp_name)
        if vm_cp_info:
            return vm_cp_info.ip_address
        else:
            return "0.0.0.0"

    def cp_mac_addr(self, cp_name):
        """ Find mac address by connection point name """
        vm_cp_info = self.vm_cp_info(cp_name)
        if vm_cp_info:
            return vm_cp_info.mac_addr
        else:
            return "00:00:00:00:00:00"

    def cp_id(self, cp_name):
        """ Find connection point id  by connection point name """
        vm_cp_info = self.vm_cp_info(cp_name)
        if vm_cp_info:
            return vm_cp_info.connection_point_id
        else:
            return str()


    @property
    def vdu_id(self):
        return self._vdud.id

    @property
    def vm_resp(self):
        return self._vm_resp

    @property
    def name(self):
        """ Return this VDUR's name """
        return self._name

    # Truncated name confirming to RFC 1123
    @property
    def unique_short_name(self):
        """ Return this VDUR's unique short name """
        # Impose these restrictions on Unique name
        #  Max 64
        #    - Max 10 of NSR name (remove all specialcharacters, only numbers and alphabets)
        #    - 6 chars of shortened name
        #    - Max 10 of VDU name (remove all specialcharacters, only numbers and alphabets)
        #
        def _restrict_tag(input_str):
           # Exclude all characters except a-zA-Z0-9
           outstr = re.sub('[^a-zA-Z0-9]', '', input_str)
           # Take max of 10 chars
           return outstr[-10:]

        # Use NSR name for part1
        part1 = _restrict_tag(self._nsr_config.name)
        # Get unique short string (6 chars)
        part2 = mano_short_name.StringShortner(self._name)
        # Use VDU ID for part3
        part3 = _restrict_tag(self._vdud.id)
        shortstr = part1 + "-" + part2.short_string + "-" + part3
        return shortstr

    @property
    def cloud_account_name(self):
        """ Cloud account this VDU should be created in """
        return self._cloud_account_name

    @property
    def image_name(self):
        """ name that should be used to lookup the image on the CMP """
        if 'image' not in self._vdud:
            return None
        return os.path.basename(self._vdud.image)

    @property
    def image_checksum(self):
        """ name that should be used to lookup the image on the CMP """
        return self._vdud.image_checksum if self._vdud.has_field("image_checksum") else None

    @property
    def management_ip(self):
        if not self.active:
            return None
        return self._vm_resp.public_ip if self._vm_resp.has_field('public_ip') else self._vm_resp.management_ip

    @property
    def vm_management_ip(self):
        if not self.active:
            return None
        return self._vm_resp.management_ip

    @property
    def operational_status(self):
        """ Operational status of this VDU"""
        op_stats_dict = {"INIT": "init",
                         "INSTANTIATING": "vm_init_phase",
                         "RESOURCE_ALLOC_PENDING": "vm_alloc_pending",
                         "READY": "running",
                         "FAILED": "failed",
                         "TERMINATING": "terminated",
                         "TERMINATED": "terminated",
                         }
        return op_stats_dict[self._state.name]

    @property
    def msg(self):
        """ Process VDU message from resmgr"""
        vdu_fields = ["vm_flavor",
                      "guest_epa",
                      "vswitch_epa",
                      "hypervisor_epa",
                      "host_epa",
                      "volumes",
                      ]
        vdu_copy_dict = {k: v for k, v in
                         self._vdud.as_dict().items() if k in vdu_fields}
        vdur_dict = {"id": self._vdur_id,
                     "vdu_id_ref": self._vdud.id,
                     "operational_status": self.operational_status,
                     "operational_status_details": self._state_failed_reason,
                     "name": self.name,
                     "unique_short_name": self.unique_short_name
                     }

        if self.vm_resp is not None:
            vdur_dict.update({"vim_id": self.vm_resp.vdu_id,
                              "flavor_id": self.vm_resp.flavor_id
                              })
            if self._vm_resp.has_field('image_id'):
                vdur_dict.update({ "image_id": self.vm_resp.image_id })

        if self.management_ip:
            vdur_dict["management_ip"] = self.management_ip

        if self.vm_management_ip:
            vdur_dict["vm_management_ip"] = self.vm_management_ip

        vdur_dict.update(vdu_copy_dict)

        if self.vm_resp is not None:
            if self._vm_resp.has_field('volumes'):
                for opvolume in self._vm_resp.volumes:
                    vdurvol_data = [vduvol for vduvol in vdur_dict['volumes'] if vduvol['name'] == opvolume.name]
                    if len(vdurvol_data) == 1:
                       vdurvol_data[0]["volume_id"] = opvolume.volume_id
                       if opvolume.has_field('custom_meta_data'):
                           metadata_list = list()
                           for metadata_item in opvolume.custom_meta_data:
                               metadata_list.append(metadata_item.as_dict())
                           vdurvol_data[0]['custom_meta_data'] = metadata_list

            if self._vm_resp.has_field('supplemental_boot_data'):
                vdur_dict['supplemental_boot_data'] = dict()
                if self._vm_resp.supplemental_boot_data.has_field('boot_data_drive'):
                    vdur_dict['supplemental_boot_data']['boot_data_drive'] = self._vm_resp.supplemental_boot_data.boot_data_drive
                if self._vm_resp.supplemental_boot_data.has_field('custom_meta_data'):
                    metadata_list = list()
                    for metadata_item in self._vm_resp.supplemental_boot_data.custom_meta_data:
                       metadata_list.append(metadata_item.as_dict())
                    vdur_dict['supplemental_boot_data']['custom_meta_data'] = metadata_list
                if self._vm_resp.supplemental_boot_data.has_field('config_file'):
                    file_list = list()
                    for file_item in self._vm_resp.supplemental_boot_data.config_file:
                       file_list.append(file_item.as_dict())
                    vdur_dict['supplemental_boot_data']['config_file'] = file_list

        icp_list = []
        ii_list = []

        for intf, cp_id, vlr in self._int_intf:
            cp = self.find_internal_cp_by_cp_id(cp_id)

            cp_info = dict(name=cp.name,
                           id=cp.id,
                           type_yang='VPORT',
                           ip_address=self.cp_ip_addr(cp.name),
                           mac_address=self.cp_mac_addr(cp.name),
                           connection_point_id=self.cp_id(cp.name))

            virtual_cps = [ vcp for vcp in vlr._vlr.virtual_connection_points
                            if [ True for cp_ref in vcp.associated_cps if cp.name == cp_ref ]]

            if virtual_cps:
                for vcp in virtual_cps:
                    cp_info['virtual_cps'] = [ {k:v for k,v in vcp.as_dict().items() if k in VCP_FIELDS}
                                               for vcp in virtual_cps ]
            icp_list.append(cp_info)

            ii_list.append({"name": intf.name,
                            "vdur_internal_connection_point_ref": cp.id,
                            "virtual_interface": {}})

        vdur_dict["internal_connection_point"] = icp_list
        self._log.debug("internal_connection_point:%s", vdur_dict["internal_connection_point"])
        vdur_dict["internal_interface"] = ii_list

        ei_list = []
        for intf, cp, vlr in self._ext_intf:
            ei_list.append({"name": cp.name,
                            "vnfd_connection_point_ref": cp.name,
                            "virtual_interface": {}})

            virtual_cps = [ vcp for vcp in vlr.virtual_connection_points
                            if [ True for cp_ref in vcp.associated_cps if cp.name == cp_ref ]]

            if virtual_cps:
                for vcp in virtual_cps:
                    virtual_cp_info = [ {k:v for k,v in vcp.as_dict().items() if k in VCP_FIELDS}
                                        for vcp in virtual_cps ]
            else:
                virtual_cp_info = []

            self._vnfr.update_cp(cp.name,
                                 self.cp_ip_addr(cp.name),
                                 self.cp_mac_addr(cp.name),
                                 self.cp_id(cp.name),
                                 virtual_cp_info)

        vdur_dict["external_interface"] = ei_list


        vdur_dict['placement_groups_info'] = [group.as_dict()
                                              for group in self._placement_groups]

        return RwVnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr_Vdur.from_dict(vdur_dict)

    @property
    def resmgr_path(self):
        """ path for resource-mgr"""
        return ("D,/rw-resource-mgr:resource-mgmt" +
                "/vdu-event" +
                "/vdu-event-data[event-id='{}']".format(self._request_id))

    @property
    def vm_flavor_msg(self):
        """ VM flavor message """
        flavor = self._vdud.vm_flavor.__class__()
        flavor.copy_from(self._vdud.vm_flavor)

        return flavor

    @property
    def vdud_cloud_init(self):
        """ Return the cloud-init contents for the VDU """
        if self._vdud_cloud_init is None:
            ci = self.cloud_init()

            # VNFR ssh public key, if available
            if self._vnfr.public_key:
                if not ci:
                    ci = "#cloud-config"
                self._vdud_cloud_init = """{}
ssh_authorized_keys:
  - {}""". \
                  format(ci, self._vnfr.public_key)
            else:
                self._vdud_cloud_init = ci

            self._log.debug("Cloud init: {}".format(self._vdud_cloud_init))

        return self._vdud_cloud_init

    def cloud_init(self):
        """ Populate cloud_init with cloud-config script from
            either the inline contents or from the file provided
        """
        cloud_init_msg = None
        if self._vdud.cloud_init is not None:
            self._log.debug("cloud_init script provided inline %s", self._vdud.cloud_init)
            cloud_init_msg = self._vdud.cloud_init
        elif self._vdud.cloud_init_file is not None:
            # Get cloud-init script contents from the file provided in the cloud_init_file param
            self._log.debug("cloud_init script provided in file %s", self._vdud.cloud_init_file)
            filename = self._vdud.cloud_init_file
            self._vnfd_package_store.refresh()
            stored_package = self._vnfd_package_store.get_package(self._vnfr.vnfd_id)
            cloud_init_extractor = rift.package.cloud_init.PackageCloudInitExtractor(self._log)
            try:
                cloud_init_msg = cloud_init_extractor.read_script(stored_package, filename)
            except rift.package.cloud_init.CloudInitExtractionError as e:
                self.instantiation_failed(str(e))
                raise VirtualDeploymentUnitRecordError(e)
        else:
            if not self._vnfr._vnfr_msg.cloud_config.key_pair and not self._vnfr._vnfr_msg.cloud_config.user:
                self._log.debug("VDU Instantiation: cloud-init script not provided")
                return

        self._log.debug("Current cloud init msg is {}".format(cloud_init_msg))
        if not self._vnfr._vnfr_msg.cloud_config.key_pair and not self._vnfr._vnfr_msg.cloud_config.user:
            return cloud_init_msg

        cloud_init_dict = {}
        if cloud_init_msg:
            try:
                cloud_init_dict = yaml.load(cloud_init_msg)
            except Exception as e:
                self._log.exception(e)
                self._log.error("Error loading cloud init Yaml file with exception %s", str(e))
                return cloud_init_msg

        self._log.debug("Current cloud init dict is {}".format(cloud_init_dict))

        for key_pair in self._vnfr._vnfr_msg.cloud_config.key_pair:
            if "ssh_authorized_keys" not in cloud_init_dict:
                cloud_init_dict["ssh_authorized_keys"] = list()
            cloud_init_dict["ssh_authorized_keys"].append(key_pair.key)

        users = list()
        for user_entry in self._vnfr._vnfr_msg.cloud_config.user:
            if "users" not in cloud_init_dict:
                cloud_init_dict["users"] = list()
            user = {}
            user["name"] = user_entry.name
            user["gecos"] = user_entry.user_info
            user["sudo"] = "ALL=(ALL) NOPASSWD:ALL"
            user["ssh-authorized-keys"] = list()
            for ssh_key in user_entry.key_pair:
                user["ssh-authorized-keys"].append(ssh_key.key)
            cloud_init_dict["users"].append(user)

        cloud_msg = yaml.safe_dump(cloud_init_dict,width=1000,default_flow_style=False)
        cloud_init = "#cloud-config\n"+cloud_msg
        self._log.debug("Cloud init msg is {}".format(cloud_init))
        return cloud_init

    def process_openstack_placement_group_construct(self, vm_create_msg_dict):
        host_aggregates = []
        availability_zones = []
        server_groups = []
        for group in self._placement_groups:
            if group.has_field('host_aggregate'):
                for aggregate in group.host_aggregate:
                    host_aggregates.append(aggregate.as_dict())
            if group.has_field('availability_zone'):
                availability_zones.append(group.availability_zone.as_dict())
            if group.has_field('server_group'):
                server_groups.append(group.server_group.as_dict())

        if availability_zones:
            if len(availability_zones) > 1:
                self._log.error("Can not launch VDU: %s in multiple availability zones. Requested Zones: %s", self.name, availability_zones)
                raise VNFMPlacementGroupError("Can not launch VDU: {} in multiple availability zones. Requsted Zones".format(self.name, availability_zones))
            else:
                vm_create_msg_dict['availability_zone'] = availability_zones[0]

        if server_groups:
            if len(server_groups) > 1:
                self._log.error("Can not launch VDU: %s in multiple Server Group. Requested Groups: %s", self.name, server_groups)
                raise VNFMPlacementGroupError("Can not launch VDU: {} in multiple Server Groups. Requsted Groups".format(self.name, server_groups))
            else:
                vm_create_msg_dict['server_group'] = server_groups[0]

        if host_aggregates:
            vm_create_msg_dict['host_aggregate'] = host_aggregates

        return

    def process_placement_groups(self, vm_create_msg_dict):
        """Process the placement_groups and fill resource-mgr request"""
        if not self._placement_groups:
            return

        cloud_set = set([group.cloud_type for group in self._placement_groups])
        assert len(cloud_set) == 1
        cloud_type = cloud_set.pop()

        if cloud_type == 'openstack':
            self.process_openstack_placement_group_construct(vm_create_msg_dict)

        else:
            self._log.info("Ignoring placement group with cloud construct for cloud-type: %s", cloud_type)
        return

    def process_custom_bootdata(self, vm_create_msg_dict):
        """Process the custom boot data"""
        if 'config_file' not in vm_create_msg_dict['supplemental_boot_data']:
            return

        self._vnfd_package_store.refresh()
        stored_package = self._vnfd_package_store.get_package(self._vnfr.vnfd_id)
        cloud_init_extractor = rift.package.cloud_init.PackageCloudInitExtractor(self._log)
        for file_item in vm_create_msg_dict['supplemental_boot_data']['config_file']:
            if 'source' not in file_item or 'dest' not in file_item:
                continue
            source = file_item['source']
            # Find source file in scripts dir of VNFD
            self._log.debug("Checking for source config file at %s", source)
            try:
               source_file_str = cloud_init_extractor.read_script(stored_package, source)
            except rift.package.cloud_init.CloudInitExtractionError as e:
               raise  VirtualDeploymentUnitRecordError(e)
            # Update source file location with file contents
            file_item['source'] = source_file_str

        return

    def resmgr_msg(self, config=None):
        vdu_fields = ["vm_flavor",
                      "guest_epa",
                      "vswitch_epa",
                      "hypervisor_epa",
                      "host_epa",
                      "volumes",
                      "supplemental_boot_data"]

        def make_resmgr_cp_args(intf, cp, vlr):
            cp_info = dict(name = cp.name,
                           virtual_link_id = vlr.network_id,
                           type_yang = intf.virtual_interface.type_yang)

            if vlr.network_id is None:
                raise VlrError("Unresolved virtual link id for vlr id:%s, name:%s",
                               (vlr.id, vlr.name))

            if cp.has_field('port_security_enabled'):
                cp_info["port_security_enabled"] = cp.port_security_enabled

            try:
                if cp.static_ip_address:
                    cp_info["static_ip_address"] = cp.static_ip_address
            except AttributeError as e:
                ### This can happen because of model difference between OSM and RIFT. Ignore exception
                self._log.debug(str(e))

            if (intf.virtual_interface.has_field('vpci') and
                 intf.virtual_interface.vpci is not None):
                cp_info["vpci"] =  intf.virtual_interface.vpci

            if (vlr.has_field('ip_profile_params')) and (vlr.ip_profile_params.has_field('security_group')):
                cp_info['security_group'] = vlr.ip_profile_params.security_group

            if vlr.has_field('virtual_connection_points'):
                virtual_cps = [ vcp for vcp in vlr.virtual_connection_points
                                if [ True for cp_ref in vcp.associated_cps if cp.name == cp_ref ]]
                if virtual_cps:
                    fields = ['connection_point_id', 'name', 'ip_address', 'mac_address']
                    cp_info['virtual_cps'] = [ {k:v for k,v in vcp.as_dict().items() if k in fields}
                                               for vcp in virtual_cps ]

            self._log.debug("CP info {}".format(cp_info))
            return cp_info

        self._log.debug("Creating params based on VDUD: %s", self._vdud)
        vdu_copy_dict = {k: v for k, v in self._vdud.as_dict().items() if k in vdu_fields}

        vm_create_msg_dict = {
                "name": self.unique_short_name, # Truncated name confirming to RFC 1123
                "node_id": self.name,           # Rift assigned Id
                }

        if self.image_name is not None:
            vm_create_msg_dict["image_name"] = self.image_name

        if self.image_checksum is not None:
            vm_create_msg_dict["image_checksum"] = self.image_checksum

        vm_create_msg_dict["allocate_public_address"] = self._mgmt_intf
        if self._vdud.has_field('mgmt_vpci'):
            vm_create_msg_dict["mgmt_vpci"] = self._vdud.mgmt_vpci

        self._log.debug("VDUD: %s", self._vdud)
        if config is not None:
            vm_create_msg_dict['vdu_init'] = {'userdata': config}

        if self._mgmt_network:
            vm_create_msg_dict['mgmt_network'] = self._mgmt_network

        cp_list = list()
        for intf, cp, vlr in self._ext_intf:
            cp_list.append(make_resmgr_cp_args(intf, cp, vlr))

        for intf, cp_id, vlr in self._int_intf:
            cp = self.find_internal_cp_by_cp_id(cp_id)
            cp_list.append(make_resmgr_cp_args(intf, cp, vlr.msg()))

        vm_create_msg_dict["connection_points"] = cp_list
        vm_create_msg_dict.update(vdu_copy_dict)

        self.process_placement_groups(vm_create_msg_dict)
        if 'supplemental_boot_data' in vm_create_msg_dict:
             self.process_custom_bootdata(vm_create_msg_dict)

        msg = RwResourceMgrYang.VDUEventData()
        msg.event_id = self._request_id
        msg.cloud_account = self.cloud_account_name
        msg.request_info.from_dict(vm_create_msg_dict)

        for volume in self._vdud.volumes:
            v = msg.request_info.volumes.add()
            v.from_dict(volume.as_dict())

        return msg

    @asyncio.coroutine
    def terminate(self, xact):
        """ Delete resource in VIM """
        if self._state != VDURecordState.READY and self._state != VDURecordState.FAILED:
            self._log.warning("VDU terminate in not ready state - Ignoring request")
            return

        self._state = VDURecordState.TERMINATING
        if self._vm_resp is not None:
            try:
                with self._dts.transaction() as new_xact:
                    yield from self.delete_resource(new_xact)
            except Exception:
                self._log.exception("Caught exception while deleting VDU %s", self.vdu_id)

        if self._rm_regh is not None:
            self._log.debug("Deregistering resource manager registration handle")
            self._rm_regh.deregister()
            self._rm_regh = None

        if self._vdur_console_handler is not None:
            self._log.debug("Deregistering vnfr vdur console registration handle")
            self._vdur_console_handler._regh.deregister()
            self._vdur_console_handler._regh = None

        self._state = VDURecordState.TERMINATED

    def find_internal_cp_by_cp_id(self, cp_id):
        """ Find the CP corresponding to the connection point id"""
        cp = None

        self._log.debug("find_internal_cp_by_cp_id(%s) called",
                        cp_id)

        for int_cp in self._vdud.internal_connection_point:
            self._log.debug("Checking for int cp %s in internal connection points",
                            int_cp.id)
            if int_cp.id == cp_id:
                cp = int_cp
                break

        if cp is None:
            self._log.debug("Failed to find cp %s in internal connection points",
                            cp_id)
            msg = "Failed to find cp %s in internal connection points" % cp_id
            raise VduRecordError(msg)

        # return the VLR associated with the connection point
        return cp

    @asyncio.coroutine
    def create_resource(self, xact, vnfr, config=None):
        """ Request resource from ResourceMgr """
        def find_cp_by_name(cp_name):
            """ Find a connection point by name """
            cp = None
            self._log.debug("find_cp_by_name(%s) called", cp_name)
            for ext_cp in vnfr._cprs:
                self._log.debug("Checking ext cp (%s) called", ext_cp.name)
                if ext_cp.name == cp_name:
                    cp = ext_cp
                    break
            if cp is None:
                self._log.debug("Failed to find cp %s in external connection points",
                                cp_name)
            return cp

        def find_internal_vlr_by_cp_id(cp_id):
            self._log.debug("find_internal_vlr_by_cp_id(%s) called",
                            cp_id)

            # Validate the cp
            cp = self.find_internal_cp_by_cp_id(cp_id)

            # return the VLR associated with the connection point
            return vnfr.find_vlr_by_cp(cp_id)

        block = xact.block_create()

        self._log.debug("Executing vm request id: %s, action: create",
                        self._request_id)

        # Resolve the networks associated external interfaces
        for ext_intf in self._vdud.external_interface:
            self._log.debug("Resolving external interface name [%s], cp[%s]",
                            ext_intf.name, ext_intf.vnfd_connection_point_ref)
            cp = find_cp_by_name(ext_intf.vnfd_connection_point_ref)
            if cp is None:
                self._log.debug("Failed to find connection point - %s",
                                ext_intf.vnfd_connection_point_ref)
                continue
            self._log.debug("Connection point name [%s], type[%s]",
                            cp.name, cp.type_yang)

            vlr = vnfr.ext_vlr_by_id(cp.vlr_ref)

            etuple = (ext_intf, cp, vlr)
            self._ext_intf.append(etuple)

            self._log.debug("Created external interface tuple  : %s", etuple)

        # Resolve the networks associated internal interfaces
        for intf in self._vdud.internal_interface:
            cp_id = intf.vdu_internal_connection_point_ref
            self._log.debug("Resolving internal interface name [%s], cp[%s]",
                            intf.name, cp_id)

            try:
                vlr = find_internal_vlr_by_cp_id(cp_id)
                iter = yield from self._dts.query_read(vlr.vlr_path())
                for itr in iter:
                    vlr._vlr = (yield from itr).result
            except Exception as e:
                self._log.debug("Failed to find cp %s in internal VLR list", cp_id)
                msg = "Failed to find cp %s in internal VLR list, e = %s" % (cp_id, e)
                raise VduRecordError(msg)

            ituple = (intf, cp_id, vlr)
            self._int_intf.append(ituple)

            self._log.debug("Created internal interface tuple  : %s", ituple)

        resmgr_path = self.resmgr_path
        resmgr_msg = self.resmgr_msg(config)

        self._log.debug("Creating new VM request at: %s, params: %s", resmgr_path, resmgr_msg)
        block.add_query_create(resmgr_path, resmgr_msg)

        res_iter = yield from block.execute(now=True)

        resp = None

        for i in res_iter:
            r = yield from i
            resp = r.result

        if resp is None or not (resp.has_field('resource_info') and resp.resource_info.has_field('resource_state')):
            raise VMResourceError("Did not get a vm resource response (resp: %s)", resp)
        self._log.debug("Got vm request response: %s", resp.resource_info)
        return resp.resource_info

    @asyncio.coroutine
    def delete_resource(self, xact):
        block = xact.block_create()

        self._log.debug("Executing vm request id: %s, action: delete",
                        self._request_id)

        block.add_query_delete(self.resmgr_path)

        yield from block.execute(flags=0, now=True)

    @asyncio.coroutine
    def read_resource(self, xact):
        block = xact.block_create()

        self._log.debug("Executing vm request id: %s, action: delete",
                        self._request_id)

        block.add_query_read(self.resmgr_path)

        res_iter = yield from block.execute(flags=0, now=True)
        for i in res_iter:
            r = yield from i
            resp = r.result

        if resp is None or not (resp.has_field('resource_info') and resp.resource_info.has_field('resource_state')):
            raise VMResourceError("Did not get a vm resource response (resp: %s)", resp)
        self._log.debug("Got vm request response: %s", resp.resource_info)
        #self._vm_resp = resp.resource_info
        return resp.resource_info


    @asyncio.coroutine
    def start_component(self):
        """ This VDUR is active """
        self._log.debug("Starting component %s for  vdud %s vdur %s",
                        self._vdud.vcs_component_ref,
                        self._vdud,
                        self._vdur_id)
        yield from self._vnfr.start_component(self._vdud.vcs_component_ref,
                                              self.vm_resp.management_ip)

    @property
    def active(self):
        """ Is this VDU active """
        return True if self._state is VDURecordState.READY else False

    @asyncio.coroutine
    def instantiation_failed(self, failed_reason=None):
        """ VDU instantiation failed """
        self._log.debug("VDU %s instantiation failed ", self._vdur_id)
        self._state = VDURecordState.FAILED
        self._state_failed_reason = failed_reason
        yield from self._vnfr.instantiation_failed(failed_reason)

    @asyncio.coroutine
    def vdu_is_active(self):
        """ This VDU is active"""
        if self.active:
            self._log.warning("VDU %s was already marked as active", self._vdur_id)
            return

        self._log.debug("VDUR id %s in VNFR %s is active", self._vdur_id, self._vnfr.vnfr_id)

        if self._vdud.vcs_component_ref is not None:
            yield from self.start_component()

        self._state = VDURecordState.READY

        if self._vnfr.all_vdus_active():
            self._log.debug("Inside vdu_is_active. VNFR is READY. Info: %s", self._vnfr)
            yield from self._vnfr.is_ready()

    @asyncio.coroutine
    def instantiate(self, xact, vnfr, config=None):
        """ Instantiate this VDU """
        self._state = VDURecordState.INSTANTIATING

        @asyncio.coroutine
        def on_prepare(xact_info, query_action, ks_path, msg):
            """ This VDUR is active """
            self._log.debug("Received VDUR instantiate on_prepare (%s:%s:%s)",
                            query_action,
                            ks_path,
                            msg)

            if (query_action == rwdts.QueryAction.UPDATE or
                    query_action == rwdts.QueryAction.CREATE):
                self._vm_resp = msg

                if msg.resource_state == "active":
                    # Move this VDU to ready state
                    yield from self.vdu_is_active()
                elif msg.resource_state == "failed":
                    yield from self.instantiation_failed(msg.resource_errors)
            elif query_action == rwdts.QueryAction.DELETE:
                self._log.debug("DELETE action in on_prepare for VDUR instantiation, ignoring")
            else:
                raise NotImplementedError(
                    "%s action on VirtualDeployementUnitRecord not supported",
                    query_action)

            xact_info.respond_xpath(rwdts.XactRspCode.ACK)

        try:
            reg_event = asyncio.Event(loop=self._loop)

            @asyncio.coroutine
            def on_ready(regh, status):
                reg_event.set()

            handler = rift.tasklets.DTS.RegistrationHandler(on_prepare=on_prepare, on_ready=on_ready)
            self._rm_regh = yield from self._dts.register(self.resmgr_path + '/resource-info',
                                                          flags=rwdts.Flag.SUBSCRIBER,
                                                          handler=handler)
            yield from reg_event.wait()

            vm_resp = yield from self.create_resource(xact, vnfr, config)
            self._vm_resp = vm_resp
            self._state = VDURecordState.RESOURCE_ALLOC_PENDING

            self._log.debug("Requested VM from resource manager response %s",
                            vm_resp)
            if vm_resp.resource_state == "active":
                self._log.debug("Resourcemgr responded wih an active vm resp %s",
                                vm_resp)
                yield from self.vdu_is_active()
                self._state = VDURecordState.READY
            elif (vm_resp.resource_state == "pending" or
                  vm_resp.resource_state == "inactive"):
                self._log.debug("Resourcemgr responded wih a pending vm resp %s",
                                vm_resp)
                # handler = rift.tasklets.DTS.RegistrationHandler(on_prepare=on_prepare)
                # self._rm_regh = yield from self._dts.register(self.resmgr_path + '/resource-info',
                #                                              flags=rwdts.Flag.SUBSCRIBER,
                #                                              handler=handler)
            else:
                self._log.debug("Resourcemgr responded wih an error vm resp %s",
                                vm_resp)
                raise VirtualDeploymentUnitRecordError(
                    "Failed VDUR instantiation %s " % vm_resp)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._log.exception(e)
            self._log.error("Instantiation of VDU record failed: %s", str(e))
            self._state = VDURecordState.FAILED
            yield from self.instantiation_failed(str(e))


class VlRecordState(enum.Enum):
    """ VL Record State """
    INIT = 101
    INSTANTIATION_PENDING = 102
    ACTIVE = 103
    TERMINATE_PENDING = 104
    TERMINATED = 105
    FAILED = 106


class InternalVirtualLinkRecord(object):
    """ Internal Virtual Link record """
    def __init__(self, dts, log, loop, vnfm, ivld_msg, vnfr_name, cloud_account_name, ip_profile=None):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._vnfm = vnfm
        self._ivld_msg = ivld_msg
        self._vnfr_name = vnfr_name
        self._cloud_account_name = cloud_account_name
        self._ip_profile = ip_profile

        self._vlr_req = self.create_vlr()
        self._vlr = None
        self._network_id = None
        self._state = VlRecordState.INIT

    @property
    def vlr_id(self):
        """ Find VLR by id """
        return self._vlr_req.id

    @property
    def name(self):
        """ Name of this VL """
        if self._ivld_msg.vim_network_name:
            return self._ivld_msg.vim_network_name
        else:
            return self._vnfr_name + "." + self._ivld_msg.name

    @property
    def network_id(self):
        """ Find VLR by id """
        return self._network_id

    @network_id.setter
    def network_id(self, network_id):
        """ network id setter"""
        self._network_id = network_id

    @property
    def active(self):
        """  """
        return self._state == VlRecordState.ACTIVE

    @property
    def state(self):
        """ state for this VLR """
        return self._state

    def vlr_path(self):
        """ VLR path for this VLR instance"""
        return "D,/vlr:vlr-catalog/vlr:vlr[vlr:id = '{}']".format(self.vlr_id)

    def create_vlr(self):
        """ Create the VLR record which will be instantiated """

        vld_fields = ["short_name",
                      "vendor",
                      "description",
                      "version",
                      "type_yang",
                      "vim_network_name",
                      "provider_network"]

        vld_copy_dict = {k: v for k, v in self._ivld_msg.as_dict().items() if k in vld_fields}

        vlr_dict = {"id": str(uuid.uuid4()),
                    "name": self.name,
                    "cloud_account": self._cloud_account_name,
                    }

        if self._ip_profile and self._ip_profile.has_field('ip_profile_params'):
            vlr_dict['ip_profile_params' ] = self._ip_profile.ip_profile_params.as_dict()

        vlr_dict.update(vld_copy_dict)

        vlr = RwVlrYang.YangData_Vlr_VlrCatalog_Vlr.from_dict(vlr_dict)

        if self._ivld_msg.has_field('virtual_connection_points'):
            for cp in self._ivld_msg.virtual_connection_points:
                vcp = vlr.virtual_connection_points.add()
                vcp.from_dict(cp.as_dict())

        return vlr

    @asyncio.coroutine
    def instantiate(self, xact, restart_mode=False):
        """ Instantiate VL """

        @asyncio.coroutine
        def instantiate_vlr():
            """ Instantiate VLR"""
            self._log.debug("Create VL with xpath %s and vlr %s",
                            self.vlr_path(), self._vlr_req)

            try:
                with self._dts.transaction(flags=0) as xact:
                    block = xact.block_create()
                    block.add_query_create(xpath=self.vlr_path(), msg=self._vlr_req)
                    self._log.debug("Executing VL create path:%s msg:%s",
                                    self.vlr_path(), self._vlr_req)

                    self._state = VlRecordState.INSTANTIATION_PENDING
                    res_iter = None
                    try:
                        res_iter = yield from block.execute()
                    except Exception:
                        self._state = VlRecordState.FAILED
                        self._log.exception("Caught exception while instantial VL")
                        raise

                    for ent in res_iter:
                        res = yield from ent
                        self._vlr = res.result

                if self._vlr.operational_status == 'failed':
                    self._log.debug("VL creation failed for vlr id %s", self._vlr.id)
                    self._state = VlRecordState.FAILED
                    raise VnfrInstantiationFailed("instantiation due to VL failure %s" % (self._vlr.id))

            except Exception as e:
                self._log.error("Caught exception while instantiating VL:%s:%s, e:%s",
                                self.vlr_id, self._vlr.name, e)
                raise

            self._log.info("Created VL with xpath %s and vlr %s",
                           self.vlr_path(), self._vlr)

        @asyncio.coroutine
        def get_vlr():
            """ Get the network id """
            res_iter = yield from self._dts.query_read(self.vlr_path(), rwdts.XactFlag.MERGE)
            vlr = None
            for ent in res_iter:
                res = yield from ent
                vlr = res.result

            if vlr is None:
                err = "Failed to get VLR for path  %s" % self.vlr_path()
                self._log.warn(err)
                raise InternalVirtualLinkRecordError(err)
            return vlr

        self._state = VlRecordState.INSTANTIATION_PENDING

        if restart_mode:
            vl = yield from get_vlr()
            if vl is None:
                yield from instantiate_vlr()
        else:
            yield from instantiate_vlr()


    def vlr_in_vns(self):
        """ Is there a VLR record in VNS """
        if (self._state == VlRecordState.ACTIVE or
            self._state == VlRecordState.INSTANTIATION_PENDING or
            self._state == VlRecordState.FAILED):
            return True

        return False

    @asyncio.coroutine
    def terminate(self, xact):
        """Terminate this VL """
        if not self.vlr_in_vns():
            self._log.debug("Ignoring terminate request for id %s in state %s",
                            self.vlr_id, self._state)
            return

        self._log.debug("Terminating VL with path %s", self.vlr_path())
        self._state = VlRecordState.TERMINATE_PENDING
        block = xact.block_create()
        block.add_query_delete(self.vlr_path())
        yield from block.execute(flags=0, now=True)
        self._state = VlRecordState.TERMINATED
        self._log.debug("Terminated VL with path %s", self.vlr_path())

    def set_state_from_op_status(self, operational_status):
        """ Set the state of this VL based on operational_status"""

        if operational_status == 'running':
            self._log.info("VL %s moved to active state", self.vlr_id)
            self._state = VlRecordState.ACTIVE
        elif operational_status == 'failed':
            self._log.info("VL %s moved to failed state", self.vlr_id)
            self._state = VlRecordState.FAILED
        elif operational_status == 'vl_alloc_pending':
            self._log.debug("VL %s is in alloc pending  state", self.vlr_id)
            self._state = VlRecordState.INSTANTIATION_PENDING
        else:
            raise VirtualLinkRecordError("Unknown operational_status %s" % (operational_status))

    def msg(self):
        """ Get a proto corresponding to this VLR """
        msg = self._vlr
        return msg

class VirtualNetworkFunctionRecord(object):
    """ Virtual Network Function Record """
    def __init__(self, dts, log, loop, cluster_name, vnfm, vcs_handler, vnfr_msg, mgmt_network=None):
        self._dts = dts
        self._log = log
        self._loop = loop###
        self._cluster_name = cluster_name
        self._vnfr_msg = vnfr_msg
        self._vnfr_id = vnfr_msg.id
        self._vnfd_id = vnfr_msg.vnfd.id
        self._vnfm = vnfm
        self._vcs_handler = vcs_handler
        self._vnfr = vnfr_msg
        self._mgmt_network = mgmt_network

        self._vnfd = vnfr_msg.vnfd
        self._state = VirtualNetworkFunctionRecordState.INIT
        self._state_failed_reason = None
        self._ext_vlrs = {}  # The list of external virtual links
        self._vlrs = {}  # The list of internal virtual links
        self._vdus = []  # The list of vdu
        self._vlr_by_cp = {}
        self._cprs = []
        self._inventory = {}
        self._create_time = int(time.time())
        self._vnf_mon = None
        self._config_status = vnfr_msg.config_status
        self._vnfd_package_store = rift.package.store.VnfdPackageFilesystemStore(self._log)
        self._rw_vnfd = None
        self._vnfd_ref_count = 0

        self._ssh_pub_key = None
        self._ssh_key_file = None
        # Create an asyncio loop to know when the virtual links are ready
        self._vls_ready = asyncio.Event(loop=self._loop)

    def _get_vdur_from_vdu_id(self, vdu_id):
        self._log.debug("Finding vdur for vdu_id %s", vdu_id)
        self._log.debug("Searching through vdus: %s", self._vdus)
        for vdu in self._vdus:
            self._log.debug("vdu_id: %s", vdu.vdu_id)
            if vdu.vdu_id == vdu_id:
                return vdu

        raise VDURecordNotFound("Could not find vdu record from id: %s", vdu_id)

    @property
    def operational_status(self):
        """ Operational status of this VNFR """
        op_status_map = {"INIT": "init",
                         "VL_INIT_PHASE": "vl_init_phase",
                         "VM_INIT_PHASE": "vm_init_phase",
                         "READY": "running",
                         "TERMINATE": "terminate",
                         "VL_TERMINATE_PHASE": "vl_terminate_phase",
                         "VDU_TERMINATE_PHASE": "vm_terminate_phase",
                         "TERMINATED": "terminated",
                         "FAILED": "failed", }
        return op_status_map[self._state.name]

    @staticmethod
    def vnfd_xpath(vnfd_id):
        """ VNFD xpath associated with this VNFR """
        return "C,/vnfd:vnfd-catalog/vnfd:vnfd[vnfd:id = '{}']".format(vnfd_id)

    @property
    def vnfd_ref_count(self):
        """ Returns the VNFD reference count associated with this VNFR """
        return self._vnfd_ref_count

    def vnfd_in_use(self):
        """ Returns whether vnfd is in use or not """
        return True if self._vnfd_ref_count > 0 else False

    def vnfd_ref(self):
        """ Take a reference on this object """
        self._vnfd_ref_count += 1
        return self._vnfd_ref_count

    def vnfd_unref(self):
        """ Release reference on this object """
        if self._vnfd_ref_count < 1:
            msg = ("Unref on a VNFD object - vnfd id %s, vnfd_ref_count = %s" %
                   (self.vnfd.id, self._vnfd_ref_count))
            self._log.critical(msg)
            raise VnfRecordError(msg)
        self._log.debug("Releasing ref on VNFD %s - curr vnfd_ref_count:%s",
                        self.vnfd.id, self._vnfd_ref_count)
        self._vnfd_ref_count -= 1
        return self._vnfd_ref_count

    @property
    def vnfd(self):
        """ VNFD for this VNFR """
        return self._vnfd

    @property
    def vnf_name(self):
        """ VNFD name associated with this VNFR """
        return self.vnfd.name

    @property
    def name(self):
        """ Name of this VNF in the record """
        return self._vnfr.name

    @property
    def cloud_account_name(self):
        """ Name of the cloud account this VNFR is instantiated in """
        return self._vnfr.cloud_account

    @property
    def vnfd_id(self):
        """ VNFD Id associated with this VNFR """
        return self.vnfd.id

    @property
    def vnfr_id(self):
        """ VNFR Id associated with this VNFR """
        return self._vnfr_id

    @property
    def member_vnf_index(self):
        """ Member VNF index associated with this VNFR """
        return self._vnfr.member_vnf_index_ref

    @property
    def config_status(self):
        """ Config agent status for this VNFR """
        return self._config_status

    @property
    def public_key(self):
        return self._ssh_pub_key

    def component_by_name(self, component_name):
        """ Find a component by name in the inventory list"""
        mangled_name = VcsComponent.mangle_name(component_name,
                                                self.vnf_name,
                                                self.vnfd_id)
        return self._inventory[mangled_name]



    @asyncio.coroutine
    def get_nsr_config(self):
        ### Need access to NS instance configuration for runtime resolution.
        ### This shall be replaced when deployment flavors are implemented
        xpath = "C,/nsr:ns-instance-config"
        results = yield from self._dts.query_read(xpath, rwdts.XactFlag.MERGE)

        for result in results:
            entry = yield from result
            ns_instance_config = entry.result
            for nsr in ns_instance_config.nsr:
                if nsr.id == self._vnfr_msg.nsr_id_ref:
                    return nsr
        return None

    @asyncio.coroutine
    def get_nsr_opdata(self):
        """ NSR opdata associated with this VNFR """
        xpath = "D,/nsr:ns-instance-opdata/nsr:nsr" \
            "[nsr:ns-instance-config-ref = '{}']". \
            format(self._vnfr_msg.nsr_id_ref)

        results = yield from self._dts.query_read(xpath, rwdts.XactFlag.MERGE)

        for result in results:
            entry = yield from result
            nsr_op = entry.result
            return nsr_op

        return None

    @asyncio.coroutine
    def start_component(self, component_name, ip_addr):
        """ Start a component in the VNFR by name """
        comp = self.component_by_name(component_name)
        yield from comp.start(None, None, ip_addr)

    def cp_ip_addr(self, cp_name):
        """ Get ip address for connection point """
        self._log.debug("cp_ip_addr()")
        for cp in self._cprs:
            if cp.name == cp_name and cp.ip_address is not None:
                return cp.ip_address
        return "0.0.0.0"

    def mgmt_intf_info(self):
        """ Get Management interface info for this VNFR """
        mgmt_intf_desc = self.vnfd.mgmt_interface
        ip_addr = None
        if mgmt_intf_desc.has_field("cp"):
            ip_addr = self.cp_ip_addr(mgmt_intf_desc.cp)
        elif mgmt_intf_desc.has_field("vdu_id"):
            try:
                vdur = self._get_vdur_from_vdu_id(mgmt_intf_desc.vdu_id)
                ip_addr = vdur.management_ip
            except VDURecordNotFound:
                self._log.debug("Did not find mgmt interface for vnfr id %s", self._vnfr_id)
                ip_addr = None
        else:
            ip_addr = mgmt_intf_desc.ip_address
        port = mgmt_intf_desc.port

        return ip_addr, port

    @property
    def msg(self):
        """ Message associated with this VNFR """
        vnfd_fields = ["short_name", "vendor", "description", "version"]
        vnfd_copy_dict = {k: v for k, v in self.vnfd.as_dict().items() if k in vnfd_fields}

        mgmt_intf = VnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr_MgmtInterface()
        ip_address, port = self.mgmt_intf_info()

        if ip_address:
            mgmt_intf.ip_address = ip_address
        if port is not None:
            mgmt_intf.port = port

        if self._ssh_pub_key:
            mgmt_intf.ssh_key.public_key = self._ssh_pub_key
            mgmt_intf.ssh_key.private_key_file = self._ssh_key_file

        vnfr_dict = {"id": self._vnfr_id,
                     "nsr_id_ref": self._vnfr_msg.nsr_id_ref,
                     "name": self.name,
                     "member_vnf_index_ref": self.member_vnf_index,
                     "operational_status": self.operational_status,
                     "operational_status_details": self._state_failed_reason,
                     "cloud_account": self.cloud_account_name,
                     "config_status": self._config_status
                     }

        vnfr_dict.update(vnfd_copy_dict)

        vnfr_msg = RwVnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr.from_dict(vnfr_dict)
        vnfr_msg.vnfd = RwVnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr_Vnfd.from_dict(self.vnfd.as_dict())

        vnfr_msg.create_time = self._create_time
        vnfr_msg.uptime = int(time.time()) - self._create_time
        vnfr_msg.mgmt_interface = mgmt_intf

        # Add all the VLRs  to  VNFR
        for vlr_id, vlr in self._vlrs.items():
            ivlr = vnfr_msg.internal_vlr.add()
            ivlr.vlr_ref = vlr.vlr_id

        # Add all the VDURs to VDUR
        if self._vdus is not None:
            for vdu in self._vdus:
                vdur = vnfr_msg.vdur.add()
                vdur.from_dict(vdu.msg.as_dict())

        if self.vnfd.mgmt_interface.has_field('dashboard_params'):
            vnfr_msg.dashboard_url = self.dashboard_url

        for cpr in self._cprs:
            new_cp = VnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr_ConnectionPoint.from_dict(cpr.as_dict())
            vnfr_msg.connection_point.append(new_cp)

        if self._vnf_mon is not None:
            for monp in self._vnf_mon.msg:
                vnfr_msg.monitoring_param.append(
                    VnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr_MonitoringParam.from_dict(monp.as_dict()))

        if self._vnfr.vnf_configuration is not None:
            vnfr_msg.vnf_configuration.from_dict(self._vnfr.vnf_configuration.as_dict())
            if (ip_address and
                    (not vnfr_msg.vnf_configuration.config_access.mgmt_ip_address)):
                vnfr_msg.vnf_configuration.config_access.mgmt_ip_address = ip_address

        for group in self._vnfr_msg.placement_groups_info:
            group_info = VnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr_PlacementGroupsInfo()
            group_info.from_dict(group.as_dict())
            vnfr_msg.placement_groups_info.append(group_info)

        return vnfr_msg

    @asyncio.coroutine
    def update_config(self, msg, xact):
        self._log.debug("VNFM vnf config: {}".
                        format(msg.vnf_configuration.as_dict()))
        self._config_status = msg.config_status
        self._vnfr = RwVnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr.from_dict(
            msg.as_dict())
        self._log.debug("VNFR msg config: {}".
                        format(self._vnfr.as_dict()))
        yield from self.publish(xact)

    @property
    def dashboard_url(self):
        ip, cfg_port = self.mgmt_intf_info()
        protocol = 'http'
        http_port = 80
        if self.vnfd.mgmt_interface.dashboard_params.has_field('https'):
            if self.vnfd.mgmt_interface.dashboard_params.https is True:
                protocol = 'https'
                http_port = 443
        if self.vnfd.mgmt_interface.dashboard_params.has_field('port'):
            http_port = self.vnfd.mgmt_interface.dashboard_params.port

        url = "{protocol}://{ip_address}:{port}/{path}".format(
                protocol=protocol,
                ip_address=ip,
                port=http_port,
                path=self.vnfd.mgmt_interface.dashboard_params.path.lstrip("/"),
                )

        return url

    @property
    def xpath(self):
        """ path for this  VNFR """
        return("D,/vnfr:vnfr-catalog"
               "/vnfr:vnfr[vnfr:id='{}']".format(self.vnfr_id))

    @asyncio.coroutine
    def publish(self, xact):
        """ publish this VNFR """
        vnfr = self.msg
        self._log.debug("Publishing VNFR path = [%s], record = [%s]",
                        self.xpath, self.msg)
        vnfr.create_time = self._create_time
        yield from self._vnfm.publish_vnfr(xact, self.xpath, self.msg)
        self._log.debug("Published VNFR path = [%s], record = [%s]",
                        self.xpath, self.msg)

    def resolve_vld_ip_profile(self, vnfd_msg, vld):
        self._log.debug("Receieved ip profile ref is %s",vld.ip_profile_ref)
        if not vld.has_field('ip_profile_ref'):
            return None
        profile = [profile for profile in vnfd_msg.ip_profiles if profile.name == vld.ip_profile_ref]
        return profile[0] if profile else None

    @asyncio.coroutine
    def create_vls(self):
        """ Publish The VLs associated with this VNF """
        self._log.debug("Publishing Internal Virtual Links for vnfd id: %s",
                        self.vnfd_id)
        for ivld_msg in self.vnfd.internal_vld:
            self._log.debug("Creating internal vld:"
                            " %s, int_cp_ref = %s",
                            ivld_msg, ivld_msg.internal_connection_point
                            )
            vlr = InternalVirtualLinkRecord(dts=self._dts,
                                            log=self._log,
                                            loop=self._loop,
                                            vnfm=self._vnfm,
                                            ivld_msg=ivld_msg,
                                            vnfr_name=self.name,
                                            cloud_account_name=self.cloud_account_name,
                                            ip_profile=self.resolve_vld_ip_profile(self.vnfd, ivld_msg)
                                            )
            self._vlrs[vlr.vlr_id] = vlr
            self._vnfm.add_vlr_id_vnfr_map(vlr.vlr_id, self)

            for int_cp in ivld_msg.internal_connection_point:
                if int_cp.id_ref in self._vlr_by_cp:
                    msg = ("Connection point %s already "
                           " bound %s" % (int_cp.id_ref, self._vlr_by_cp[int_cp.id_ref]))
                    raise InternalVirtualLinkRecordError(msg)
                self._log.debug("Setting vlr %s to internal cp = %s",
                                vlr, int_cp.id_ref)
                self._vlr_by_cp[int_cp.id_ref] = vlr

    @asyncio.coroutine
    def instantiate_vls(self, xact, restart_mode=False):
        """ Instantiate the VLs associated with this VNF """
        self._log.debug("Instantiating Internal Virtual Links for vnfd id: %s",
                        self.vnfd_id)

        for vlr_id, vlr in self._vlrs.items():
            self._log.debug("Instantiating VLR %s", vlr)
            yield from vlr.instantiate(xact, restart_mode)

        # Wait for the VLs to be ready before yielding control out
        if self._vlrs:
            self._log.debug("VNFR id:%s, name:%s - Waiting for %d VLs to be ready",
                            self.vnfr_id, self.name, len(self._vlrs))
            yield from self._vls_ready.wait()
        else:
            self._log.debug("VNFR id:%s, name:%s, No virtual links found",
                            self.vnfr_id, self.name)
            self._vls_ready.set()

    def find_vlr_by_cp(self, cp_name):
        """ Find the VLR associated with the cp name """
        return self._vlr_by_cp[cp_name]

    def resolve_placement_group_cloud_construct(self, input_group, nsr_config):
        """
        Returns the cloud specific construct for placement group
        Arguments:
            input_group: VNFD PlacementGroup
            nsr_config: Configuration for VNFDGroup MAP in the NSR config
        """
        copy_dict = ['name', 'requirement', 'strategy']
        for group_info in nsr_config.vnfd_placement_group_maps:
            if group_info.placement_group_ref == input_group.name and \
               group_info.vnfd_id_ref == self.vnfd_id:
                group = VnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr_Vdur_PlacementGroupsInfo()
                group_dict = {k:v for k,v in
                              group_info.as_dict().items()
                              if (k != 'placement_group_ref' and k !='vnfd_id_ref')}
                for param in copy_dict:
                    group_dict.update({param: getattr(input_group, param)})
                group.from_dict(group_dict)
                return group
        return None

    @asyncio.coroutine
    def get_vdu_placement_groups(self, vdu, nsr_config):
        placement_groups = []
        ### Step-1: Get VNF level placement groups
        for group in self._vnfr_msg.placement_groups_info:
            #group_info = VnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr_Vdur_PlacementGroupsInfo()
            #group_info.from_dict(group.as_dict())
            placement_groups.append(group)

        ### Step-2: Get VDU level placement groups
        for group in self.vnfd.placement_groups:
            for member_vdu in group.member_vdus:
                if member_vdu.member_vdu_ref == vdu.id:
                    group_info = self.resolve_placement_group_cloud_construct(group,
                                                                              nsr_config)
                    if group_info is None:
                        self._log.info("Could not resolve cloud-construct for placement group: %s", group.name)
                        ### raise VNFMPlacementGroupError("Could not resolve cloud-construct for placement group: {}".format(group.name))
                    else:
                        self._log.info("Successfully resolved cloud construct for placement group: %s for VDU: %s in VNF: %s (Member Index: %s)",
                                       str(group_info),
                                       vdu.name,
                                       self.vnf_name,
                                       self.member_vnf_index)
                        placement_groups.append(group_info)

        return placement_groups

    @asyncio.coroutine
    def vdu_cloud_init_instantiation(self):
        [vdu.vdud_cloud_init for vdu in self._vdus]

    @asyncio.coroutine
    def create_vdus(self, vnfr, restart_mode=False):
        """ Create the VDUs associated with this VNF """

        def get_vdur_id(vdud):
            """Get the corresponding VDUR's id for the VDUD. This is useful in
            case of a restart.

            In restart mode we check for exiting VDUR's ID and use them, if
            available. This way we don't end up creating duplicate VDURs
            """
            vdur_id = None

            if restart_mode and vdud is not None:
                try:
                    vdur = [vdur.id for vdur in vnfr._vnfr.vdur if vdur.vdu_id_ref == vdud.id]
                    vdur_id = vdur[0]
                except IndexError:
                    self._log.error("Unable to find a VDUR for VDUD {}".format(vdud))

            return vdur_id


        self._log.info("Creating VDU's for vnfd id: %s", self.vnfd_id)

        # Get NSR config - Needed for placement groups and to derive VDU short-name
        nsr_config = yield from self.get_nsr_config()

        for vdu in self._rw_vnfd.vdu:
            self._log.debug("Creating vdu: %s", vdu)
            vdur_id = get_vdur_id(vdu)


            placement_groups = yield from self.get_vdu_placement_groups(vdu, nsr_config)
            self._log.info("Launching VDU: %s from VNFD :%s (Member Index: %s) with Placement Groups: %s, Existing vdur_id %s",
                           vdu.name,
                           self.vnf_name,
                           self.member_vnf_index,
                           [ group.name for group in placement_groups],
                           vdur_id)

            vdur = VirtualDeploymentUnitRecord(
                dts=self._dts,
                log=self._log,
                loop=self._loop,
                vdud=vdu,
                vnfr=vnfr,
                nsr_config=nsr_config,
                mgmt_intf=self.has_mgmt_interface(vdu),
                mgmt_network=self._mgmt_network,
                cloud_account_name=self.cloud_account_name,
                vnfd_package_store=self._vnfd_package_store,
                vdur_id=vdur_id,
                placement_groups = placement_groups,
                )
            yield from vdur.vdu_opdata_register()

            self._vdus.append(vdur)

    @asyncio.coroutine
    def instantiate_vdus(self, xact, vnfr):
        """ Instantiate the VDUs associated with this VNF """
        self._log.debug("Instantiating VDU's for vnfd id %s: %s", self.vnfd_id, self._vdus)

        lookup = {vdu.vdu_id: vdu for vdu in self._vdus}

        # Identify any dependencies among the VDUs
        dependencies = collections.defaultdict(list)
        vdu_id_pattern = re.compile(r"\{\{ vdu\[([^]]+)\]\S* \}\}")

        for vdu in self._vdus:
            if vdu._vdud_cloud_init is not None:
                for vdu_id in vdu_id_pattern.findall(vdu._vdud_cloud_init):
                    if vdu_id != vdu.vdu_id:
                        # This means that vdu.vdu_id depends upon vdu_id,
                        # i.e. vdu_id must be instantiated before
                        # vdu.vdu_id.
                        dependencies[vdu.vdu_id].append(lookup[vdu_id])

        # Define the terminal states of VDU instantiation
        terminal = (
                VDURecordState.READY,
                VDURecordState.TERMINATED,
                VDURecordState.FAILED,
                )

        datastore = VdurDatastore()
        processed = set()

        @asyncio.coroutine
        def instantiate_monitor(vdu):
            """Monitor the state of the VDU during instantiation

            Arguments:
                vdu - a VirtualDeploymentUnitRecord

            """
            # wait for the VDUR to enter a terminal state
            while vdu._state not in terminal:
                yield from asyncio.sleep(1, loop=self._loop)
            # update the datastore
            datastore.update(vdu)

            # add the VDU to the set of processed VDUs
            processed.add(vdu.vdu_id)

        @asyncio.coroutine
        def instantiate(vdu):
            """Instantiate the specified VDU

            Arguments:
                vdu - a VirtualDeploymentUnitRecord

            Raises:
                if the VDU, or any of the VDUs this VDU depends upon, are
                terminated or fail to instantiate properly, a
                VirtualDeploymentUnitRecordError is raised.

            """
            for dependency in dependencies[vdu.vdu_id]:
                self._log.debug("{}: waiting for {}".format(vdu.vdu_id, dependency.vdu_id))

                while dependency.vdu_id not in processed:
                    yield from asyncio.sleep(1, loop=self._loop)

                if not dependency.active:
                    raise VirtualDeploymentUnitRecordError()

            self._log.debug('instantiating {}'.format(vdu.vdu_id))

            # Populate the datastore with the current values of the VDU
            datastore.add(vdu)

            # Substitute any variables contained in the cloud config script
            config = str(vdu.vdud_cloud_init) if vdu.vdud_cloud_init is not None else ""

            parts = re.split("\{\{ ([^\}]+) \}\}", config)
            if len(parts) > 1:

                # Extract the variable names
                variables = list()
                for variable in parts[1::2]:
                    variables.append(variable.lstrip('{{').rstrip('}}').strip())

                # Iterate of the variables and substitute values from the
                # datastore.
                for variable in variables:

                    # Handle a reference to a VDU by ID
                    if variable.startswith('vdu['):
                        value = datastore.get(variable)
                        if value is None:
                            msg = "Unable to find a substitute for {} in {} cloud-init script"
                            raise ValueError(msg.format(variable, vdu.vdu_id))

                        config = config.replace("{{ %s }}" % variable, value)
                        continue

                    # Handle a reference to the current VDU
                    if variable.startswith('vdu'):
                        value = datastore.get('vdu[{}]'.format(vdu.vdu_id) + variable[3:])
                        config = config.replace("{{ %s }}" % variable, value)
                        continue

                    # Handle unrecognized variables
                    msg = 'unrecognized cloud-config variable: {}'
                    raise ValueError(msg.format(variable))

            # Instantiate the VDU
            with self._dts.transaction() as xact:
                self._log.debug("Instantiating vdu: %s", vdu)
                yield from vdu.instantiate(xact, vnfr, config=config)
                if self._state == VirtualNetworkFunctionRecordState.FAILED:
                    self._log.error("Instatiation of VNF %s failed while instantiating vdu %s",
                                    self.vnfr_id, vdu)

        # First create a set of tasks to monitor the state of the VDUs and
        # report when they have entered a terminal state
        for vdu in self._vdus:
            self._loop.create_task(instantiate_monitor(vdu))

        for vdu in self._vdus:
            self._loop.create_task(instantiate(vdu))

    def has_mgmt_interface(self, vdu):
        # ## TODO: Support additional mgmt_interface type options
        if self.vnfd.mgmt_interface.vdu_id == vdu.id:
            return True
        return False

    def vlr_xpath(self, vlr_id):
        """ vlr xpath """
        return(
            "D,/vlr:vlr-catalog/"
            "vlr:vlr[vlr:id = '{}']".format(vlr_id))

    def ext_vlr_by_id(self, vlr_id):
        """ find ext vlr by id """
        return self._ext_vlrs[vlr_id]

    @asyncio.coroutine
    def publish_inventory(self, xact):
        """ Publish the inventory associated with this VNF """
        self._log.debug("Publishing inventory for VNFR id: %s", self._vnfr_id)

        for component in self._rw_vnfd.component:
            self._log.debug("Creating inventory component %s", component)
            mangled_name = VcsComponent.mangle_name(component.component_name,
                                                    self.vnf_name,
                                                    self.vnfd_id
                                                    )
            comp = VcsComponent(dts=self._dts,
                                log=self._log,
                                loop=self._loop,
                                cluster_name=self._cluster_name,
                                vcs_handler=self._vcs_handler,
                                component=component,
                                mangled_name=mangled_name,
                                )
            if comp.name in self._inventory:
                self._log.debug("Duplicate entries in inventory  %s for vnfr %s",
                                component, self._vnfd_id)
                return
            self._log.debug("Adding component %s for vnrf %s",
                            comp.name, self._vnfr_id)
            self._inventory[comp.name] = comp
            yield from comp.publish(xact)

    def all_vdus_active(self):
        """ Are all VDUS in this VNFR active? """
        for vdu in self._vdus:
            if not vdu.active:
                return False

        self._log.debug("Inside all_vdus_active. Returning True")
        return True

    @asyncio.coroutine
    def instantiation_failed(self, failed_reason=None):
        """ VNFR instantiation failed """
        self._log.debug("VNFR %s instantiation failed ", self.vnfr_id)
        self.set_state(VirtualNetworkFunctionRecordState.FAILED)
        self._state_failed_reason = failed_reason

        # Update the VNFR with the changed status
        yield from self.publish(None)

    @asyncio.coroutine
    def is_ready(self):
        """ This VNF is ready"""
        self._log.debug("VNFR id %s is ready", self.vnfr_id)

        if self._state != VirtualNetworkFunctionRecordState.FAILED:
            self.set_state(VirtualNetworkFunctionRecordState.READY)

        else:
            self._log.debug("VNFR id %s ignoring state change", self.vnfr_id)

        # Update the VNFR with the changed status
        yield from self.publish(None)

    def update_cp(self, cp_name, ip_address, mac_addr, cp_id, virtual_cps = list()):
        """Updated the connection point with ip address"""
        for cp in self._cprs:
            if cp.name == cp_name:
                self._log.debug("Setting ip address and id for cp %s, cpr %s with ip %s id %s",
                                cp_name, cp, ip_address, cp_id)
                cp.ip_address = ip_address
                cp.mac_address = mac_addr
                cp.connection_point_id = cp_id
                if virtual_cps:
                    cp.virtual_cps = [VnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr_ConnectionPoint_VirtualCps.from_dict(v) for v in virtual_cps]
                return

        err = "No connection point %s found in VNFR id %s" % (cp.name, self._vnfr_id)
        self._log.debug(err)
        raise VirtualDeploymentUnitRecordError(err)

    def set_state(self, state):
        """ Set state for this VNFR"""
        self._state = state

    @asyncio.coroutine
    def instantiate(self, xact, restart_mode=False):
        """ instantiate this VNF """
        self.set_state(VirtualNetworkFunctionRecordState.VL_INIT_PHASE)
        self._rw_vnfd = yield from self._vnfm.fetch_vnfd(self._vnfd_id)

        nsr_op = yield from self.get_nsr_opdata()
        if nsr_op:
            self._ssh_key_file = nsr_op.ssh_key_generated.private_key_file
            self._ssh_pub_key = nsr_op.ssh_key_generated.public_key

        @asyncio.coroutine
        def fetch_vlrs():
            """ Fetch VLRs """
            # Iterate over all the connection points in VNFR and fetch the
            # associated VLRs

            def cpr_from_cp(cp):
                """ Creates a record level connection point from the desciptor cp"""
                cp_fields = ["name", "image", "vm-flavor", "static_ip_address", "port_security_enabled"]
                cp_copy_dict = {k: v for k, v in cp.as_dict().items() if k in cp_fields}
                cpr_dict = {}
                cpr_dict.update(cp_copy_dict)
                return VnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr_ConnectionPoint.from_dict(cpr_dict)

            self._log.debug("Fetching VLRs for VNFR id = %s, cps = %s",
                            self._vnfr_id, self._vnfr.connection_point)

            for cp in self._vnfr.connection_point:
                cpr = cpr_from_cp(cp)
                self._cprs.append(cpr)
                self._log.debug("Adding Connection point record  %s ", cp)

                vlr_path = self.vlr_xpath(cp.vlr_ref)
                self._log.debug("Fetching VLR with path = %s", vlr_path)
                res_iter = yield from self._dts.query_read(self.vlr_xpath(cp.vlr_ref),
                                                           rwdts.XactFlag.MERGE)
                for i in res_iter:
                    r = yield from i
                    d = r.result
                    self._ext_vlrs[cp.vlr_ref] = d
                    cpr.vlr_ref = cp.vlr_ref
                    self._log.debug("Fetched VLR [%s] with path = [%s]", d, vlr_path)

        # Increase the VNFD reference count
        self.vnfd_ref()

        assert self.vnfd

        # Fetch External VLRs
        self._log.debug("VNFR-ID %s: Fetching vlrs", self._vnfr_id)
        yield from fetch_vlrs()

        # Publish inventory
        self._log.debug("VNFR-ID %s: Publishing Inventory", self._vnfr_id)
        yield from self.publish_inventory(xact)

        # Publish inventory
        self._log.debug("VNFR-ID %s: Creating VLs", self._vnfr_id)
        yield from self.create_vls()

        # publish the VNFR
        self._log.debug("VNFR-ID %s: Publish VNFR", self._vnfr_id)
        yield from self.publish(xact)


        # instantiate VLs
        self._log.debug("VNFR-ID %s: Instantiate VLs, restart mode %s", self._vnfr_id, restart_mode)
        try:
            yield from self.instantiate_vls(xact, restart_mode)
        except Exception as e:
            self._log.exception("VL instantiation failed (%s)", str(e))
            yield from self.instantiation_failed(str(e))
            return

        self.set_state(VirtualNetworkFunctionRecordState.VM_INIT_PHASE)

        # instantiate VDUs
        self._log.debug("VNFR-ID %s: Create VDUs, restart mode %s", self._vnfr_id, restart_mode)
        yield from self.create_vdus(self, restart_mode)

        try:
            yield from self.vdu_cloud_init_instantiation()
        except Exception as e:
            self.set_state(VirtualNetworkFunctionRecordState.FAILED)
            self._state_failed_reason = str(e)
            yield from self.publish(xact)

        # publish the VNFR
        self._log.debug("VNFR-ID %s: Publish VNFR", self._vnfr_id)
        yield from self.publish(xact)

        # instantiate VDUs
        # ToDo: Check if this should be prevented during restart
        self._log.debug("VNFR-ID %s: Instantiate VDUs", self._vnfr_id)
        _ = self._loop.create_task(self.instantiate_vdus(xact, self))

        # publish the VNFR
        self._log.debug("VNFR-ID %s: Publish VNFR", self._vnfr_id)
        yield from self.publish(xact)

        self._log.debug("VNFR-ID %s: Instantiation Done", self._vnfr_id)

        # create task updating uptime for this vnfr
        self._log.debug("VNFR-ID %s: Starting task to update uptime", self._vnfr_id)
        self._loop.create_task(self.vnfr_uptime_update(xact))

    @asyncio.coroutine
    def terminate(self, xact):
        """ Terminate this virtual network function """

        self._log.debug("Terminatng VNF id %s", self.vnfr_id)

        self.set_state(VirtualNetworkFunctionRecordState.TERMINATE)

        # stop monitoring
        if self._vnf_mon is not None:
            self._vnf_mon.stop()
            self._vnf_mon.deregister()
            self._vnf_mon = None

        @asyncio.coroutine
        def terminate_vls():
            """ Terminate VLs in this VNF """
            for vlr_id, vl in self._vlrs.items():
                self._vnfm.remove_vlr_id_vnfr_map(vlr_id)
                yield from vl.terminate(xact)

        @asyncio.coroutine
        def terminate_vdus():
            """ Terminate VDUS in this VNF """
            for vdu in self._vdus:
                yield from vdu.terminate(xact)

        self._log.debug("Terminatng VLs in VNF id %s", self.vnfr_id)
        self.set_state(VirtualNetworkFunctionRecordState.VL_TERMINATE_PHASE)
        yield from terminate_vls()

        self._log.debug("Terminatng VDUs in VNF id %s", self.vnfr_id)
        self.set_state(VirtualNetworkFunctionRecordState.VDU_TERMINATE_PHASE)
        yield from terminate_vdus()

        self._log.debug("Terminated  VNF id %s", self.vnfr_id)
        self.set_state(VirtualNetworkFunctionRecordState.TERMINATED)

    @asyncio.coroutine
    def vnfr_uptime_update(self, xact):
        while True:
            # Return when vnfr state is FAILED or TERMINATED etc
            if self._state not in [VirtualNetworkFunctionRecordState.INIT,
                                   VirtualNetworkFunctionRecordState.VL_INIT_PHASE,
                                   VirtualNetworkFunctionRecordState.VM_INIT_PHASE,
                                   VirtualNetworkFunctionRecordState.READY]:
                return
            yield from self.publish(xact)
            yield from asyncio.sleep(2, loop=self._loop)

    def vl_instantiation_state(self):
        """ Get the state of VL instantiation of  this VNF """
        for vl_id, vlr in self._vlrs.items():
            if vlr.state == VlRecordState.ACTIVE:
                continue
            elif vlr.state == VlRecordState.FAILED:
                return VlRecordState.FAILED
            elif vlr.state == VlRecordState.INSTANTIATION_PENDING:
                return VlRecordState.INSTANTIATION_PENDING
            else:
                self._log.debug("vlr %s still in state %s", vlr, vlr.state)
                raise VlRecordError("Invalid state %s", vlr.state)
        return VlRecordState.ACTIVE

    def vl_instantiation_successful(self):
        """ Mark that all VLs in this VNF are active """
        if self._vls_ready.is_set():
            self._log.debug("VNFR id %s, vls_ready is already set", self.id)

        if self.vl_instantiation_state() == VlRecordState.ACTIVE:
            self._log.info("VNFR id:%s name:%s has all Virtual Links in active state, Ready to orchestrate VDUs",
                           self.vnfr_id, self.name)
            self._vls_ready.set()

    def find_vlr(self, vlr_id):
        """ Find VLR matching the passed VLR id """

        if vlr_id in self._vlrs:
            return self._vlrs[vlr_id]
        return None

    def vlr_event(self, vlr, action):
        self._log.debug("Received VLR %s with action:%s", vlr, action)

        vlr_local = self.find_vlr(vlr.id)
        if vlr_local is None:
            self._log.error("VLR %s:%s  received  for unknown id, state:%s ignoring event",
                            vlr.id, vlr.name, vlr.state)
            return

        if action == rwdts.QueryAction.CREATE or action == rwdts.QueryAction.UPDATE:
            if vlr.operational_status == 'running':
                vlr_local.set_state_from_op_status(vlr.operational_status)
                self._log.info("VLR %s:%s moving to active state",
                               vlr.id, vlr.name)
            elif vlr.operational_status == 'failed':
                vlr_local.set_state_from_op_status(vlr.operational_status)
                self._log.info("VLR %s:%s moving to failed state",
                               vlr.id, vlr.name)
            else:
                self._log.warning("VLR %s:%s  received  state:%s",
                                  vlr.id, vlr.name, vlr.operational_status)

        if vlr.has_field('network_id'):
            vlr_local.network_id = vlr.network_id

        # Check  if vl instantiation successful for this VNFR
        self.vl_instantiation_successful()


class VnfdDtsHandler(object):
    """ DTS handler for VNFD config changes """
    XPATH = "C,/vnfd:vnfd-catalog/vnfd:vnfd"

    def __init__(self, dts, log, loop, vnfm):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._vnfm = vnfm
        self._regh = None
        self._reg_ready = 0

    @asyncio.coroutine
    def regh(self):
        """ DTS registration handle """
        return self._regh

    @asyncio.coroutine
    def register(self):
        """ Register for VNFD configuration"""

        @asyncio.coroutine
        def on_apply(dts, acg, xact, action, scratch):
            """Apply the  configuration"""
            self._log.debug("Got VNFM VNFD apply (xact: %s) (action: %s)(scr: %s)",
                            xact, action, scratch)

            is_recovery = xact.xact is None and action == rwdts.AppconfAction.INSTALL
            # Create/Update a VNFD record
            for cfg in self._regh.get_xact_elements(xact):
                # Only interested in those VNFD cfgs whose ID was received in prepare callback
                if cfg.id in scratch.get('vnfds', []) or is_recovery:
                    self._vnfm.update_vnfd(cfg)

            scratch.pop('vnfds', None)

            if (action == rwdts.AppconfAction.INSTALL and self._reg_ready == 0):
                self._reg_ready = 1
                yield from self._vnfm.vnfr_handler.register()
                yield from self._vnfm.vnfr_ref_handler.register()

        @asyncio.coroutine
        def on_prepare(dts, acg, xact, xact_info, ks_path, msg, scratch):
            """ on prepare callback """
            self._log.debug("Got on prepare for VNFD (path: %s) (action: %s)",
                            ks_path.to_xpath(RwVnfmYang.get_schema()), msg)
            fref = ProtobufC.FieldReference.alloc()
            fref.goto_whole_message(msg.to_pbcm())

            # Handle deletes in prepare_callback
            if fref.is_field_deleted():
                # Delete an VNFD record
                self._log.debug("Deleting VNFD with id %s", msg.id)
                if self._vnfm.vnfd_in_use(msg.id):
                    self._log.debug("Cannot delete VNFD in use - %s", msg)
                    err = "Cannot delete a VNFD in use - %s" % msg
                    raise VirtualNetworkFunctionDescriptorRefCountExists(err)
                # Delete a VNFD record
                yield from self._vnfm.delete_vnfd(msg.id)

            xact_info.respond_xpath(rwdts.XactRspCode.ACK)

        self._log.debug(
            "Registering for VNFD config using xpath: %s",
            VnfdDtsHandler.XPATH,
            )
        acg_hdl = rift.tasklets.AppConfGroup.Handler(on_apply=on_apply)
        with self._dts.appconf_group_create(handler=acg_hdl) as acg:
            self._regh = acg.register(
                xpath=VnfdDtsHandler.XPATH,
                flags=rwdts.Flag.SUBSCRIBER | rwdts.Flag.DELTA_READY,
                on_prepare=on_prepare)


class VcsComponentDtsHandler(object):
    """ Vcs Component DTS handler """
    XPATH = ("D,/rw-manifest:manifest" +
             "/rw-manifest:operational-inventory" +
             "/rw-manifest:component")

    def __init__(self, dts, log, loop, vnfm):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._regh = None
        self._vnfm = vnfm

    @property
    def regh(self):
        """ DTS registration handle """
        return self._regh

    @asyncio.coroutine
    def register(self):
        """ Registers VCS component dts publisher registration"""
        self._log.debug("VCS Comp publisher DTS handler registering path %s",
                        VcsComponentDtsHandler.XPATH)

        hdl = rift.tasklets.DTS.RegistrationHandler()
        handlers = rift.tasklets.Group.Handler()
        with self._dts.group_create(handler=handlers) as group:
            self._regh = group.register(xpath=VcsComponentDtsHandler.XPATH,
                                        handler=hdl,
                                        flags=(rwdts.Flag.PUBLISHER |
                                               rwdts.Flag.NO_PREP_READ |
                                               rwdts.Flag.DATASTORE),)

    @asyncio.coroutine
    def publish(self, xact, path, msg):
        """ Publishes the VCS component """
        self._log.debug("Publishing the VcsComponent xact = %s, %s:%s",
                        xact, path, msg)
        self.regh.create_element(path, msg)
        self._log.debug("Published the VcsComponent to %s xact = %s, %s:%s",
                        VcsComponentDtsHandler.XPATH, xact, path, msg)

class VnfrConsoleOperdataDtsHandler(object):
    """ registers 'D,/vnfr:vnfr-console/vnfr:vnfr[id]/vdur[id]' and handles CRUD from DTS"""
    @property
    def vnfr_vdu_console_xpath(self):
        """ path for resource-mgr"""
        return ("D,/rw-vnfr:vnfr-console/rw-vnfr:vnfr[rw-vnfr:id='{}']/rw-vnfr:vdur[vnfr:id='{}']".format(self._vnfr_id,self._vdur_id))

    def __init__(self, dts, log, loop, vnfm, vnfr_id, vdur_id, vdu_id):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._regh = None
        self._vnfm = vnfm

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
                self._log.debug("VDU Opdata path is {}".format(path_entry.key00.id))
                try:
                    vnfr = self._vnfm.get_vnfr(self._vnfr_id)
                except VnfRecordError as e:
                    self._log.error("VNFR id %s not found", self._vnfr_id)
                    xact_info.respond_xpath(rsp_code=rwdts.XactRspCode.ACK)
                    return
                try:
                    vdur= vnfr._get_vdur_from_vdu_id(self._vdu_id)
                    if not vdur._state == VDURecordState.READY:
                        self._log.debug("VDUR state is not READY. current state is {}".format(vdur._state))
                        xact_info.respond_xpath(rsp_code=rwdts.XactRspCode.ACK)
                        return
                    with self._dts.transaction() as new_xact:
                        resp = yield from vdur.read_resource(new_xact)
                        vdur_console = RwVnfrYang.YangData_RwVnfr_VnfrConsole_Vnfr_Vdur()
                        vdur_console.id = self._vdur_id
                        if resp.console_url:
                            vdur_console.console_url = resp.console_url
                        else:
                            vdur_console.console_url = 'none'
                        self._log.debug("Recevied console URL for vdu {} is {}".format(self._vdu_id,vdur_console))
                except Exception:
                    self._log.exception("Caught exception while reading VDU %s", self._vdu_id)
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


class VnfrDtsHandler(object):
    """ registers 'D,/vnfr:vnfr-catalog/vnfr:vnfr' and handles CRUD from DTS"""
    XPATH = "D,/vnfr:vnfr-catalog/vnfr:vnfr"

    def __init__(self, dts, log, loop, vnfm):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._vnfm = vnfm

        self._regh = None

    @property
    def regh(self):
        """ Return registration handle"""
        return self._regh

    @property
    def vnfm(self):
        """ Return VNF manager instance """
        return self._vnfm

    @asyncio.coroutine
    def register(self):
        """ Register for vnfr create/update/delete/read requests from dts """
        def on_commit(xact_info):
            """ The transaction has been committed """
            self._log.debug("Got vnfr commit (xact_info: %s)", xact_info)
            return rwdts.MemberRspCode.ACTION_OK

        def on_abort(*args):
            """ Abort callback """
            self._log.debug("VNF  transaction got aborted")

        @asyncio.coroutine
        def on_event(dts, g_reg, xact, xact_event, scratch_data):

            @asyncio.coroutine
            def instantiate_realloc_vnfr(vnfr):
                """Re-populate the vnfm after restart

                Arguments:
                    vlink

                """

                yield from vnfr.instantiate(None, restart_mode=True)

            if xact_event == rwdts.MemberEvent.INSTALL:
                curr_cfg = self.regh.elements
                for cfg in curr_cfg:
                    vnfr = self.vnfm.create_vnfr(cfg)
                    self._loop.create_task(instantiate_realloc_vnfr(vnfr))

            self._log.debug("Got on_event in vnfm")

            return rwdts.MemberRspCode.ACTION_OK

        @asyncio.coroutine
        def on_prepare(xact_info, action, ks_path, msg):
            """ prepare callback from dts """
            self._log.debug(
                "Got vnfr on_prepare callback (xact_info: %s, action: %s): %s",
                xact_info, action, msg
                )

            if action == rwdts.QueryAction.CREATE:
                if not msg.has_field("vnfd"):
                    err = "Vnfd not provided"
                    self._log.error(err)
                    raise VnfRecordError(err)

                vnfr = self.vnfm.create_vnfr(msg)
                try:
                    # RIFT-9105: Unable to add a READ query under an existing transaction
                    # xact = xact_info.xact
                    yield from vnfr.instantiate(None)
                except Exception as e:
                    self._log.exception(e)
                    self._log.error("Error while instantiating vnfr:%s", vnfr.vnfr_id)
                    vnfr.set_state(VirtualNetworkFunctionRecordState.FAILED)
                    yield from vnfr.publish(None)
            elif action == rwdts.QueryAction.DELETE:
                schema = RwVnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr.schema()
                path_entry = schema.keyspec_to_entry(ks_path)
                vnfr = self._vnfm.get_vnfr(path_entry.key00.id)

                if vnfr is None:
                    self._log.debug("VNFR id %s not found for delete", path_entry.key00.id)
                    raise VirtualNetworkFunctionRecordNotFound(
                        "VNFR id %s", path_entry.key00.id)

                try:
                    yield from vnfr.terminate(xact_info.xact)
                    # Unref the VNFD
                    vnfr.vnfd_unref()
                    yield from self._vnfm.delete_vnfr(xact_info.xact, vnfr)
                except Exception as e:
                    self._log.exception(e)
                    self._log.error("Caught exception while deleting vnfr %s", path_entry.key00.id)

            elif action == rwdts.QueryAction.UPDATE:
                schema = RwVnfrYang.YangData_Vnfr_VnfrCatalog_Vnfr.schema()
                path_entry = schema.keyspec_to_entry(ks_path)
                vnfr = None
                try:
                    vnfr = self._vnfm.get_vnfr(path_entry.key00.id)
                except Exception as e:
                    self._log.debug("No vnfr found with id %s", path_entry.key00.id)
                    xact_info.respond_xpath(rwdts.XactRspCode.NA)
                    return

                if vnfr is None:
                    self._log.debug("VNFR id %s not found for update", path_entry.key00.id)
                    xact_info.respond_xpath(rwdts.XactRspCode.NA)
                    return

                self._log.debug("VNFR {} update config status {} (current {})".
                                format(vnfr.name, msg.config_status, vnfr.config_status))
                # Update the config and publish
                yield from vnfr.update_config(msg, xact_info)

            else:
                raise NotImplementedError(
                    "%s action on VirtualNetworkFunctionRecord not supported",
                    action)

            xact_info.respond_xpath(rwdts.XactRspCode.ACK)

        self._log.debug("Registering for VNFR using xpath: %s",
                        VnfrDtsHandler.XPATH,)

        hdl = rift.tasklets.DTS.RegistrationHandler(on_commit=on_commit,
                                                    on_prepare=on_prepare,)
        handlers = rift.tasklets.Group.Handler(on_event=on_event,)
        with self._dts.group_create(handler=handlers) as group:
            self._regh = group.register(xpath=VnfrDtsHandler.XPATH,
                                        handler=hdl,
                                        flags=(rwdts.Flag.PUBLISHER |
                                               rwdts.Flag.NO_PREP_READ |
                                               rwdts.Flag.DATASTORE),)

    @asyncio.coroutine
    def create(self, xact, path, msg):
        """
        Create a VNFR record in DTS with path and message
        """
        self._log.debug("Creating VNFR xact = %s, %s:%s",
                        xact, path, msg)

        self.regh.create_element(path, msg)
        self._log.debug("Created VNFR xact = %s, %s:%s",
                        xact, path, msg)

    @asyncio.coroutine
    def update(self, xact, path, msg, flags=rwdts.XactFlag.REPLACE):
        """
        Update a VNFR record in DTS with path and message
        """
        self._log.debug("Updating VNFR xact = %s, %s:%s",
                        xact, path, msg)
        self.regh.update_element(path, msg, flags)
        self._log.debug("Updated VNFR xact = %s, %s:%s",
                        xact, path, msg)

    @asyncio.coroutine
    def delete(self, xact, path):
        """
        Delete a VNFR record in DTS with path and message
        """
        self._log.debug("Deleting VNFR xact = %s, %s", xact, path)
        self.regh.delete_element(path)
        self._log.debug("Deleted VNFR xact = %s, %s", xact, path)


class VnfdRefCountDtsHandler(object):
    """ The VNFD Ref Count DTS handler """
    XPATH = "D,/vnfr:vnfr-catalog/rw-vnfr:vnfd-ref-count"

    def __init__(self, dts, log, loop, vnfm):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._vnfm = vnfm

        self._regh = None

    @property
    def regh(self):
        """ Return registration handle """
        return self._regh

    @property
    def vnfm(self):
        """ Return the NS manager instance """
        return self._vnfm

    @asyncio.coroutine
    def register(self):
        """ Register for VNFD ref count read from dts """

        @asyncio.coroutine
        def on_prepare(xact_info, action, ks_path, msg):
            """ prepare callback from dts """
            xpath = ks_path.to_xpath(RwVnfrYang.get_schema())
            self._log.debug(
                "Got VNFD ref count get xact_info: %s, action: %s): %s:%s",
                xact_info, action, xpath, msg
                )

            if action == rwdts.QueryAction.READ:
                schema = RwVnfrYang.YangData_Vnfr_VnfrCatalog_VnfdRefCount.schema()
                path_entry = schema.keyspec_to_entry(ks_path)
                vnfd_list = yield from self._vnfm.get_vnfd_refcount(path_entry.key00.vnfd_id_ref)
                for xpath, msg in vnfd_list:
                    self._log.debug("Responding to ref count query path:%s, msg:%s",
                                    xpath, msg)
                    xact_info.respond_xpath(rsp_code=rwdts.XactRspCode.MORE,
                                            xpath=xpath,
                                            msg=msg)
                xact_info.respond_xpath(rwdts.XactRspCode.ACK)
            else:
                raise VnfRecordError("Not supported operation %s" % action)

        hdl = rift.tasklets.DTS.RegistrationHandler(on_prepare=on_prepare,)
        with self._dts.group_create() as group:
            self._regh = group.register(xpath=VnfdRefCountDtsHandler.XPATH,
                                        handler=hdl,
                                        flags=rwdts.Flag.PUBLISHER,
                                        )


class VdurDatastore(object):
    """
    This VdurDatastore is intended to expose select information about a VDUR
    such that it can be referenced in a cloud config file. The data that is
    exposed does not necessarily follow the structure of the data in the yang
    model. This is intentional. The data that are exposed are intended to be
    agnostic of the yang model so that changes in the model do not necessarily
    require changes to the interface provided to the user. It also means that
    the user does not need to be familiar with the RIFT.ware yang models.
    """

    def __init__(self):
        """Create an instance of VdurDatastore"""
        self._vdur_data = dict()
        self._pattern = re.compile("vdu\[([^]]+)\]\.(.+)")

    def add(self, vdur):
        """Add a new VDUR to the datastore

        Arguments:
            vdur - a VirtualDeploymentUnitRecord instance

        Raises:
            A ValueError is raised if the VDUR is (1) None or (2) already in
            the datastore.

        """
        if vdur.vdu_id is None:
            raise ValueError('VDURs are required to have an ID')

        if vdur.vdu_id in self._vdur_data:
            raise ValueError('cannot add a VDUR more than once')

        self._vdur_data[vdur.vdu_id] = dict()

        def set_if_not_none(key, attr):
            if attr is not None:
                self._vdur_data[vdur.vdu_id][key] = attr

        set_if_not_none('name', vdur._vdud.name)
        set_if_not_none('mgmt.ip', vdur.vm_management_ip)
        # The below can be used for hostname
        set_if_not_none('vdur_name', vdur.unique_short_name)

    def update(self, vdur):
        """Update the VDUR information in the datastore

        Arguments:
            vdur - a GI representation of a VDUR

        Raises:
            A ValueError is raised if the VDUR is (1) None or (2) already in
            the datastore.

        """
        if vdur.vdu_id is None:
            raise ValueError('VNFDs are required to have an ID')

        if vdur.vdu_id not in self._vdur_data:
            raise ValueError('VNF is not recognized')

        def set_or_delete(key, attr):
            if attr is None:
                if key in self._vdur_data[vdur.vdu_id]:
                    del self._vdur_data[vdur.vdu_id][key]

            else:
                self._vdur_data[vdur.vdu_id][key] = attr

        set_or_delete('name', vdur._vdud.name)
        set_or_delete('mgmt.ip', vdur.vm_management_ip)
        # The below can be used for hostname
        set_or_delete('vdur_name', vdur.unique_short_name)

    def remove(self, vdur_id):
        """Remove all of the data associated with specified VDUR

        Arguments:
            vdur_id - the identifier of a VNFD in the datastore

        Raises:
            A ValueError is raised if the VDUR is not contained in the
            datastore.

        """
        if vdur_id not in self._vdur_data:
            raise ValueError('VNF is not recognized')

        del self._vdur_data[vdur_id]

    def get(self, expr):
        """Retrieve VDUR information from the datastore

        An expression should be of the form,

            vdu[<id>].<attr>

        where <id> is the VDUR ID (an unquoted UUID), and <attr> is the name of
        the exposed attribute that the user wishes to retrieve.

        If the requested data is not available, None is returned.

        Arguments:
            expr - a string that specifies the data to return

        Raises:
            A ValueError is raised if the provided expression cannot be parsed.

        Returns:
            The requested data or None

        """
        result = self._pattern.match(expr)
        if result is None:
            raise ValueError('data expression not recognized ({})'.format(expr))

        vdur_id, key = result.groups()

        if vdur_id not in self._vdur_data:
            return None

        return self._vdur_data[vdur_id].get(key, None)


class VnfManager(object):
    """ The virtual network function manager class """
    def __init__(self, dts, log, loop, cluster_name):
        self._dts = dts
        self._log = log
        self._loop = loop
        self._cluster_name = cluster_name

        self._vcs_handler = VcsComponentDtsHandler(dts, log, loop, self)
        self._vnfr_handler = VnfrDtsHandler(dts, log, loop, self)
        self._vnfr_ref_handler = VnfdRefCountDtsHandler(dts, log, loop, self)
        self._nsr_handler = mano_dts.NsInstanceConfigSubscriber(log, dts, loop, callback=self.handle_nsr)
        self._vlr_handler = subscriber.VlrSubscriberDtsHandler(log, dts, loop, callback=self.vlr_event)

        self._dts_handlers = [VnfdDtsHandler(dts, log, loop, self),
                              self._nsr_handler,
                              self._vcs_handler,
                              self._vlr_handler]
        self._vnfrs = {}
        self._vnfds_to_vnfr = {}
        self._nsrs = {}
        self._vnfr_for_vlr = {}

    @property
    def vnfr_handler(self):
        """ VNFR dts handler """
        return self._vnfr_handler

    @property
    def vnfr_ref_handler(self):
        """ VNFR dts handler """
        return self._vnfr_ref_handler

    @property
    def vcs_handler(self):
        """ VCS dts handler """
        return self._vcs_handler

    @asyncio.coroutine
    def register(self):
        """ Register all static DTS handlers """
        for hdl in self._dts_handlers:
            yield from hdl.register()

    @asyncio.coroutine
    def run(self):
        """ Run this VNFM instance """
        self._log.debug("Run VNFManager - registering static DTS handlers""")
        yield from self.register()

    def handle_nsr(self, nsr, action):
        if action in [rwdts.QueryAction.CREATE]:
            self._nsrs[nsr.id] = nsr
        elif action == rwdts.QueryAction.DELETE:
            if nsr.id in self._nsrs:
                del self._nsrs[nsr.id]

    def get_linked_mgmt_network(self, vnfr):
        """For the given VNFR get the related mgmt network from the NSD, if
        available.
        """
        vnfd_id = vnfr.vnfd.id
        nsr_id = vnfr.nsr_id_ref

        # for the given related VNFR, get the corresponding NSR-config
        nsr_obj = None
        try:
            nsr_obj = self._nsrs[nsr_id]
        except KeyError:
            raise("Unable to find the NS with the ID: {}".format(nsr_id))

        # for the related NSD check if a VLD exists such that it's a mgmt
        # network
        for vld in nsr_obj.nsd.vld:
            if vld.mgmt_network:
                return vld.name

        return None

    def get_vnfr(self, vnfr_id):
        """ get VNFR by vnfr id """

        if vnfr_id not in self._vnfrs:
            raise VnfRecordError("VNFR id %s not found", vnfr_id)

        return self._vnfrs[vnfr_id]

    def create_vnfr(self, vnfr):
        """ Create a VNFR instance """
        if vnfr.id in self._vnfrs:
            msg = "Vnfr id %s already exists" % vnfr.id
            self._log.error(msg)
            raise VnfRecordError(msg)

        self._log.info("Create VirtualNetworkFunctionRecord %s from vnfd_id: %s",
                       vnfr.id,
                       vnfr.vnfd.id)

        mgmt_network = self.get_linked_mgmt_network(vnfr)

        self._vnfrs[vnfr.id] = VirtualNetworkFunctionRecord(
            self._dts, self._log, self._loop, self._cluster_name, self, self.vcs_handler, vnfr,
            mgmt_network=mgmt_network
            )

        #Update ref count
        if vnfr.vnfd.id in self._vnfds_to_vnfr:
            self._vnfds_to_vnfr[vnfr.vnfd.id] += 1
        else:
            self._vnfds_to_vnfr[vnfr.vnfd.id] = 1

        return self._vnfrs[vnfr.id]

    @asyncio.coroutine
    def delete_vnfr(self, xact, vnfr):
        """ Create a VNFR instance """
        if vnfr.vnfr_id in self._vnfrs:
            self._log.debug("Deleting VNFR id %s", vnfr.vnfr_id)
            yield from self._vnfr_handler.delete(xact, vnfr.xpath)

            if vnfr.vnfd.id in self._vnfds_to_vnfr:
                if self._vnfds_to_vnfr[vnfr.vnfd.id]:
                    self._vnfds_to_vnfr[vnfr.vnfd.id] -= 1

            del self._vnfrs[vnfr.vnfr_id]

    @asyncio.coroutine
    def fetch_vnfd(self, vnfd_id):
        """ Fetch VNFDs based with the vnfd id"""
        vnfd_path = VirtualNetworkFunctionRecord.vnfd_xpath(vnfd_id)
        self._log.debug("Fetch vnfd with path %s", vnfd_path)
        vnfd = None

        res_iter = yield from self._dts.query_read(vnfd_path, rwdts.XactFlag.MERGE)

        for ent in res_iter:
            res = yield from ent
            vnfd = res.result

        if vnfd is None:
            err = "Failed to get  Vnfd %s" % vnfd_id
            self._log.error(err)
            raise VnfRecordError(err)

        self._log.debug("Fetched vnfd for path %s, vnfd - %s", vnfd_path, vnfd)

        return vnfd

    def vnfd_in_use(self, vnfd_id):
        """ Is this VNFD in use """
        self._log.debug("Is this VNFD in use - msg:%s", vnfd_id)
        if vnfd_id in self._vnfds_to_vnfr:
            return (self._vnfds_to_vnfr[vnfd_id] > 0)
        return False

    @asyncio.coroutine
    def publish_vnfr(self, xact, path, msg):
        """ Publish a VNFR """
        self._log.debug("publish_vnfr called with path %s, msg %s",
                        path, msg)
        yield from self.vnfr_handler.update(xact, path, msg)

    @asyncio.coroutine
    def delete_vnfd(self, vnfd_id):
        """ Delete the Virtual Network Function descriptor with the passed id """
        self._log.debug("Deleting the virtual network function descriptor - %s", vnfd_id)
        if vnfd_id in self._vnfds_to_vnfr:
            if self._vnfds_to_vnfr[vnfd_id]:
                self._log.debug("Cannot delete VNFD id %s reference exists %s",
                                vnfd_id,
                                self._vnfds_to_vnfr[vnfd_id].vnfd_ref_count)
                raise VirtualNetworkFunctionDescriptorRefCountExists(
                    "Cannot delete :%s, ref_count:%s",
                    vnfd_id,
                    self._vnfds_to_vnfr[vnfd_id].vnfd_ref_count)

            del self._vnfds_to_vnfr[vnfd_id]

        # Remove any files uploaded with VNFD and stored under $RIFT_ARTIFACTS/libs/<id>
        try:
            rift_artifacts_dir = os.environ['RIFT_ARTIFACTS']
            vnfd_dir = os.path.join(rift_artifacts_dir, 'launchpad/libs', vnfd_id)
            if os.path.exists(vnfd_dir):
                shutil.rmtree(vnfd_dir, ignore_errors=True)
        except Exception as e:
            self._log.error("Exception in cleaning up VNFD {}: {}".
                            format(self._vnfds_to_vnfr[vnfd_id].vnfd.name, e))
            self._log.exception(e)


    def vnfd_refcount_xpath(self, vnfd_id):
        """ xpath for ref count entry """
        return (VnfdRefCountDtsHandler.XPATH +
                "[rw-vnfr:vnfd-id-ref = '{}']").format(vnfd_id)

    @asyncio.coroutine
    def get_vnfd_refcount(self, vnfd_id):
        """ Get the vnfd_list from this VNFM"""
        vnfd_list = []
        if vnfd_id is None or vnfd_id == "":
            for vnfd in self._vnfds_to_vnfr.keys():
                vnfd_msg = RwVnfrYang.YangData_Vnfr_VnfrCatalog_VnfdRefCount()
                vnfd_msg.vnfd_id_ref = vnfd
                vnfd_msg.instance_ref_count = self._vnfds_to_vnfr[vnfd]
                vnfd_list.append((self.vnfd_refcount_xpath(vnfd), vnfd_msg))
        elif vnfd_id in self._vnfds_to_vnfr:
                vnfd_msg = RwVnfrYang.YangData_Vnfr_VnfrCatalog_VnfdRefCount()
                vnfd_msg.vnfd_id_ref = vnfd_id
                vnfd_msg.instance_ref_count = self._vnfds_to_vnfr[vnfd_id]
                vnfd_list.append((self.vnfd_refcount_xpath(vnfd_id), vnfd_msg))

        return vnfd_list

    def add_vlr_id_vnfr_map(self, vlr_id, vnfr):
        """ Add a mapping for vlr_id into VNFR """
        self._vnfr_for_vlr[vlr_id] = vnfr

    def remove_vlr_id_vnfr_map(self, vlr_id):
        """ Remove a mapping for vlr_id into VNFR """
        del self._vnfr_for_vlr[vlr_id]

    def find_vnfr_for_vlr_id(self, vlr_id):
        """ Find VNFR for VLR id """
        vnfr = None
        if vlr_id in self._vnfr_for_vlr:
            vnfr = self._vnfr_for_vlr[vlr_id]

    def vlr_event(self, vlr, action):
        """ VLR event handler """
        self._log.debug("VnfManager: Received VLR %s with action:%s", vlr, action)

        if vlr.id not in self._vnfr_for_vlr:
            self._log.warning("VLR %s:%s  received  for unknown id; %s",
                              vlr.id, vlr.name, vlr)
            return
        vnfr  = self._vnfr_for_vlr[vlr.id]

        vnfr.vlr_event(vlr, action)


class VnfmTasklet(rift.tasklets.Tasklet):
    """ VNF Manager tasklet class """
    def __init__(self, *args, **kwargs):
        super(VnfmTasklet, self).__init__(*args, **kwargs)
        self.rwlog.set_category("rw-mano-log")
        self.rwlog.set_subcategory("vnfm")

        self._dts = None
        self._vnfm = None

    def start(self):
        try:
            super(VnfmTasklet, self).start()
            self.log.info("Starting VnfmTasklet")

            self.log.setLevel(logging.DEBUG)

            self.log.debug("Registering with dts")
            self._dts = rift.tasklets.DTS(self.tasklet_info,
                                          RwVnfmYang.get_schema(),
                                          self.loop,
                                          self.on_dts_state_change)

            self.log.debug("Created DTS Api GI Object: %s", self._dts)
        except Exception:
            print("Caught Exception in VNFM start:", sys.exc_info()[0])
            raise

    def on_instance_started(self):
        """ Task insance started callback """
        self.log.debug("Got instance started callback")

    def stop(self):
        try:
            self._dts.deinit()
        except Exception:
            print("Caught Exception in VNFM stop:", sys.exc_info()[0])
            raise

    @asyncio.coroutine
    def init(self):
        """ Task init callback """
        try:
            vm_parent_name = self.tasklet_info.get_parent_vm_parent_instance_name()
            assert vm_parent_name is not None
            self._vnfm = VnfManager(self._dts, self.log, self.loop, vm_parent_name)
            yield from self._vnfm.run()
        except Exception:
            print("Caught Exception in VNFM init:", sys.exc_info()[0])
            raise

    @asyncio.coroutine
    def run(self):
        """ Task run callback """
        pass

    @asyncio.coroutine
    def on_dts_state_change(self, state):
        """Take action according to current dts state to transition
        application into the corresponding application state

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
            self._dts.handle.set_state(next_state)
