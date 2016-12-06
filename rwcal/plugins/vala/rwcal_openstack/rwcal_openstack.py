
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

import contextlib
import logging
import os
import subprocess
import uuid

import rift.rwcal.openstack as openstack_drv
import rw_status
import rift.cal.rwcal_status as rwcal_status
import rwlogger
import neutronclient.common.exceptions as NeutronException

from gi.repository import (
    GObject,
    RwCal,
    RwTypes,
    RwcalYang)

PREPARE_VM_CMD = "prepare_vm.py --auth_url {auth_url} --username {username} --password {password} --tenant_name {tenant_name} --mgmt_network {mgmt_network} --server_id {server_id} --port_metadata"

rwstatus_exception_map = { IndexError: RwTypes.RwStatus.NOTFOUND,
                           KeyError: RwTypes.RwStatus.NOTFOUND,
                           NotImplementedError: RwTypes.RwStatus.NOT_IMPLEMENTED,}

rwstatus = rw_status.rwstatus_from_exc_map(rwstatus_exception_map)
rwcalstatus = rwcal_status.rwcalstatus_from_exc_map(rwstatus_exception_map)


espec_utils = openstack_drv.OpenstackExtraSpecUtils()

class OpenstackCALOperationFailure(Exception):
    pass

class UninitializedPluginError(Exception):
    pass


class OpenstackServerGroupError(Exception):
    pass


class ImageUploadError(Exception):
    pass


class RwcalOpenstackPlugin(GObject.Object, RwCal.Cloud):
    """This class implements the CAL VALA methods for openstack."""

    instance_num = 1

    def __init__(self):
        GObject.Object.__init__(self)
        self._driver_class = openstack_drv.OpenstackDriver
        self.log = logging.getLogger('rwcal.openstack.%s' % RwcalOpenstackPlugin.instance_num)
        self.log.setLevel(logging.DEBUG)

        self._rwlog_handler = None
        RwcalOpenstackPlugin.instance_num += 1


    @contextlib.contextmanager
    def _use_driver(self, account):
        if self._rwlog_handler is None:
            raise UninitializedPluginError("Must call init() in CAL plugin before use.")

        with rwlogger.rwlog_root_handler(self._rwlog_handler):
            try:
                drv = self._driver_class(username      = account.openstack.key,
                                         password      = account.openstack.secret,
                                         auth_url      = account.openstack.auth_url,
                                         tenant_name   = account.openstack.tenant,
                                         mgmt_network  = account.openstack.mgmt_network,
                                         cert_validate = account.openstack.cert_validate )
            except Exception as e:
                self.log.error("RwcalOpenstackPlugin: OpenstackDriver init failed. Exception: %s" %(str(e)))
                raise

            yield drv


    @rwstatus
    def do_init(self, rwlog_ctx):
        self._rwlog_handler = rwlogger.RwLogger(
                category="rw-cal-log",
                subcategory="openstack",
                log_hdl=rwlog_ctx,
                )
        self.log.addHandler(self._rwlog_handler)
        self.log.propagate = False

    @rwstatus(ret_on_failure=[None])
    def do_validate_cloud_creds(self, account):
        """
        Validates the cloud account credentials for the specified account.
        Performs an access to the resources using Keystone API. If creds
        are not valid, returns an error code & reason string
        Arguments:
            account - a cloud account to validate

        Returns:
            Validation Code and Details String
        """
        status = RwcalYang.CloudConnectionStatus()

        try:
            with self._use_driver(account) as drv:
                drv.validate_account_creds()

        except openstack_drv.ValidationError as e:
            self.log.error("RwcalOpenstackPlugin: OpenstackDriver credential validation failed. Exception: %s", str(e))
            status.status = "failure"
            status.details = "Invalid Credentials: %s" % str(e)

        except Exception as e:
            msg = "RwcalOpenstackPlugin: OpenstackDriver connection failed. Exception: %s" %(str(e))
            self.log.error(msg)
            status.status = "failure"
            status.details = msg

        else:
            status.status = "success"
            status.details = "Connection was successful"

        return status

    @rwstatus(ret_on_failure=[""])
    def do_get_management_network(self, account):
        """
        Returns the management network associated with the specified account.
        Arguments:
            account - a cloud account

        Returns:
            The management network
        """
        return account.openstack.mgmt_network

    @rwstatus(ret_on_failure=[""])
    def do_create_tenant(self, account, name):
        """Create a new tenant.

        Arguments:
            account - a cloud account
            name - name of the tenant

        Returns:
            The tenant id
        """
        raise NotImplementedError

    @rwstatus
    def do_delete_tenant(self, account, tenant_id):
        """delete a tenant.

        Arguments:
            account - a cloud account
            tenant_id - id of the tenant
        """
        raise NotImplementedError

    @rwstatus(ret_on_failure=[[]])
    def do_get_tenant_list(self, account):
        """List tenants.

        Arguments:
            account - a cloud account

        Returns:
            List of tenants
        """
        raise NotImplementedError

    @rwstatus(ret_on_failure=[""])
    def do_create_role(self, account, name):
        """Create a new user.

        Arguments:
            account - a cloud account
            name - name of the user

        Returns:
            The user id
        """
        raise NotImplementedError

    @rwstatus
    def do_delete_role(self, account, role_id):
        """Delete a user.

        Arguments:
            account - a cloud account
            role_id - id of the user
        """
        raise NotImplementedError

    @rwstatus(ret_on_failure=[[]])
    def do_get_role_list(self, account):
        """List roles.

        Arguments:
            account - a cloud account

        Returns:
            List of roles
        """
        raise NotImplementedError

    @rwstatus(ret_on_failure=[""])
    def do_create_image(self, account, image):
        """Create an image

        Arguments:
            account - a cloud account
            image - a description of the image to create

        Returns:
            The image id
        """

        try:
            # If the use passed in a file descriptor, use that to
            # upload the image.
            if image.has_field("fileno"):
                new_fileno = os.dup(image.fileno)
                hdl = os.fdopen(new_fileno, 'rb')
            else:
                hdl = open(image.location, "rb")
        except Exception as e:
            self.log.error("Could not open file for upload. Exception received: %s", str(e))
            raise

        with hdl as fd:
            kwargs = {}
            kwargs['name'] = image.name

            if image.disk_format:
                kwargs['disk_format'] = image.disk_format
            if image.container_format:
                kwargs['container_format'] = image.container_format

            with self._use_driver(account) as drv:
                # Create Image
                image_id = drv.glance_image_create(**kwargs)
                # Upload the Image
                drv.glance_image_upload(image_id, fd)

                # Update image properties, if they are provided
                if image.has_field("properties") and image.properties is not None:
                    img_prop = {}
                    for key in image.properties:
                        img_prop[key.name] = key.property_value
                    drv.glance_image_update(image_id, **img_prop)

                if image.checksum:
                    stored_image = drv.glance_image_get(image_id)
                    if stored_image.checksum != image.checksum:
                        drv.glance_image_delete(image_id=image_id)
                        raise ImageUploadError(
                                "image checksum did not match (actual: %s, expected: %s). Deleting." %
                                (stored_image.checksum, image.checksum)
                                )

        return image_id

    @rwstatus
    def do_delete_image(self, account, image_id):
        """Delete a vm image.

        Arguments:
            account - a cloud account
            image_id - id of the image to delete
        """
        with self._use_driver(account) as drv:
            drv.glance_image_delete(image_id=image_id)


    @staticmethod
    def _fill_image_info(img_info):
        """Create a GI object from image info dictionary

        Converts image information dictionary object returned by openstack
        driver into Protobuf Gi Object

        Arguments:
            account - a cloud account
            img_info - image information dictionary object from openstack

        Returns:
            The ImageInfoItem
        """
        img = RwcalYang.ImageInfoItem()
        img.name = img_info['name']
        img.id = img_info['id']
        img.checksum = img_info['checksum']
        img.disk_format = img_info['disk_format']
        img.container_format = img_info['container_format']
        if img_info['status'] == 'active':
            img.state = 'active'
        else:
            img.state = 'inactive'
        return img

    @rwstatus(ret_on_failure=[[]])
    def do_get_image_list(self, account):
        """Return a list of the names of all available images.

        Arguments:
            account - a cloud account

        Returns:
            The the list of images in VimResources object
        """
        response = RwcalYang.VimResources()
        with self._use_driver(account) as drv:
            images = drv.glance_image_list()
        for img in images:
            response.imageinfo_list.append(RwcalOpenstackPlugin._fill_image_info(img))
        return response

    @rwstatus(ret_on_failure=[None])
    def do_get_image(self, account, image_id):
        """Return a image information.

        Arguments:
            account - a cloud account
            image_id - an id of the image

        Returns:
            ImageInfoItem object containing image information.
        """
        with self._use_driver(account) as drv:
            image = drv.glance_image_get(image_id)
        return RwcalOpenstackPlugin._fill_image_info(image)

    @rwstatus(ret_on_failure=[""])
    def do_create_vm(self, account, vminfo):
        """Create a new virtual machine.

        Arguments:
            account - a cloud account
            vminfo - information that defines the type of VM to create

        Returns:
            The image id
        """
        kwargs = {}
        kwargs['name']      = vminfo.vm_name
        kwargs['flavor_id'] = vminfo.flavor_id
        if vminfo.has_field('image_id'):
            kwargs['image_id']  = vminfo.image_id

        with self._use_driver(account) as drv:
            ### If floating_ip is required and we don't have one, better fail before any further allocation
            if vminfo.has_field('allocate_public_address') and vminfo.allocate_public_address:
                if account.openstack.has_field('floating_ip_pool'):
                    pool_name = account.openstack.floating_ip_pool
                else:
                    pool_name = None
                floating_ip = self._allocate_floating_ip(drv, pool_name)
            else:
                floating_ip = None

        if vminfo.has_field('cloud_init') and vminfo.cloud_init.has_field('userdata'):
            kwargs['userdata']  = vminfo.cloud_init.userdata
        else:
            kwargs['userdata'] = ''

        if account.openstack.security_groups:
            kwargs['security_groups'] = account.openstack.security_groups

        port_list = []
        for port in vminfo.port_list:
            port_list.append(port.port_id)

        if port_list:
            kwargs['port_list'] = port_list

        network_list = []
        for network in vminfo.network_list:
            network_list.append(network.network_id)

        if network_list:
            kwargs['network_list'] = network_list

        metadata = {}
        for field in vminfo.user_tags.fields:
            if vminfo.user_tags.has_field(field):
                metadata[field] = getattr(vminfo.user_tags, field)
        kwargs['metadata']  = metadata

        if vminfo.has_field('availability_zone'):
            kwargs['availability_zone']  = vminfo.availability_zone
        else:
            kwargs['availability_zone'] = None

        if vminfo.has_field('server_group'):
            kwargs['scheduler_hints'] = {'group': vminfo.server_group }
        else:
            kwargs['scheduler_hints'] = None

        with self._use_driver(account) as drv:
            vm_id = drv.nova_server_create(**kwargs)
            if floating_ip:
                self.prepare_vdu_on_boot(account, vm_id, floating_ip)

        return vm_id

    @rwstatus
    def do_start_vm(self, account, vm_id):
        """Start an existing virtual machine.

        Arguments:
            account - a cloud account
            vm_id - an id of the VM
        """
        with self._use_driver(account) as drv:
            drv.nova_server_start(vm_id)

    @rwstatus
    def do_stop_vm(self, account, vm_id):
        """Stop a running virtual machine.

        Arguments:
            account - a cloud account
            vm_id - an id of the VM
        """
        with self._use_driver(account) as drv:
            drv.nova_server_stop(vm_id)

    @rwstatus
    def do_delete_vm(self, account, vm_id):
        """Delete a virtual machine.

        Arguments:
            account - a cloud account
            vm_id - an id of the VM
        """
        with self._use_driver(account) as drv:
            drv.nova_server_delete(vm_id)

    @rwstatus
    def do_reboot_vm(self, account, vm_id):
        """Reboot a virtual machine.

        Arguments:
            account - a cloud account
            vm_id - an id of the VM
        """
        with self._use_driver(account) as drv:
            drv.nova_server_reboot(vm_id)

    @staticmethod
    def _fill_vm_info(vm_info, mgmt_network):
        """Create a GI object from vm info dictionary

        Converts VM information dictionary object returned by openstack
        driver into Protobuf Gi Object

        Arguments:
            vm_info - VM information from openstack
            mgmt_network - Management network

        Returns:
            Protobuf Gi object for VM
        """
        vm = RwcalYang.VMInfoItem()
        vm.vm_id     = vm_info['id']
        vm.vm_name   = vm_info['name']
        vm.image_id  = vm_info['image']['id']
        vm.flavor_id = vm_info['flavor']['id']
        vm.state     = vm_info['status']
        for network_name, network_info in vm_info['addresses'].items():
            if network_info:
                if network_name == mgmt_network:
                    vm.public_ip = next((item['addr']
                                            for item in network_info
                                            if item['OS-EXT-IPS:type'] == 'floating'),
                                        network_info[0]['addr'])
                    vm.management_ip = network_info[0]['addr']
                else:
                    for interface in network_info:
                        addr = vm.private_ip_list.add()
                        addr.ip_address = interface['addr']

        for network_name, network_info in vm_info['addresses'].items():
            if network_info and network_name == mgmt_network and not vm.public_ip:
                for interface in network_info:
                    if 'OS-EXT-IPS:type' in interface and interface['OS-EXT-IPS:type'] == 'floating':
                        vm.public_ip = interface['addr']

        # Look for any metadata
        for key, value in vm_info['metadata'].items():
            if key in vm.user_tags.fields:
                setattr(vm.user_tags, key, value)
        if 'OS-EXT-SRV-ATTR:host' in vm_info:
            if vm_info['OS-EXT-SRV-ATTR:host'] != None:
                vm.host_name = vm_info['OS-EXT-SRV-ATTR:host']
        if 'OS-EXT-AZ:availability_zone' in vm_info:
            if vm_info['OS-EXT-AZ:availability_zone'] != None:
                vm.availability_zone = vm_info['OS-EXT-AZ:availability_zone']
        return vm

    @rwstatus(ret_on_failure=[[]])
    def do_get_vm_list(self, account):
        """Return a list of the VMs as vala boxed objects

        Arguments:
            account - a cloud account

        Returns:
            List containing VM information
        """
        response = RwcalYang.VimResources()
        with self._use_driver(account) as drv:
            vms = drv.nova_server_list()
        for vm in vms:
            response.vminfo_list.append(RwcalOpenstackPlugin._fill_vm_info(vm, account.openstack.mgmt_network))
        return response

    @rwstatus(ret_on_failure=[None])
    def do_get_vm(self, account, id):
        """Return vm information.

        Arguments:
            account - a cloud account
            id - an id for the VM

        Returns:
            VM information
        """
        with self._use_driver(account) as drv:
            vm = drv.nova_server_get(id)
        return RwcalOpenstackPlugin._fill_vm_info(vm, account.openstack.mgmt_network)

    @staticmethod
    def _get_guest_epa_specs(guest_epa):
        """
        Returns EPA Specs dictionary for guest_epa attributes
        """
        epa_specs = {}
        if guest_epa.has_field('mempage_size'):
            mempage_size = espec_utils.guest.mano_to_extra_spec_mempage_size(guest_epa.mempage_size)
            if mempage_size is not None:
                epa_specs['hw:mem_page_size'] = mempage_size

        if guest_epa.has_field('cpu_pinning_policy'):
            cpu_pinning_policy = espec_utils.guest.mano_to_extra_spec_cpu_pinning_policy(guest_epa.cpu_pinning_policy)
            if cpu_pinning_policy is not None:
                epa_specs['hw:cpu_policy'] = cpu_pinning_policy

        if guest_epa.has_field('cpu_thread_pinning_policy'):
            cpu_thread_pinning_policy = espec_utils.guest.mano_to_extra_spec_cpu_thread_pinning_policy(guest_epa.cpu_thread_pinning_policy)
            if cpu_thread_pinning_policy is None:
                epa_specs['hw:cpu_threads_policy'] = cpu_thread_pinning_policy

        if guest_epa.has_field('trusted_execution'):
            trusted_execution = espec_utils.guest.mano_to_extra_spec_trusted_execution(guest_epa.trusted_execution)
            if trusted_execution is not None:
                epa_specs['trust:trusted_host'] = trusted_execution

        if guest_epa.has_field('numa_node_policy'):
            if guest_epa.numa_node_policy.has_field('node_cnt'):
                numa_node_count = espec_utils.guest.mano_to_extra_spec_numa_node_count(guest_epa.numa_node_policy.node_cnt)
                if numa_node_count is not None:
                    epa_specs['hw:numa_nodes'] = numa_node_count

            if guest_epa.numa_node_policy.has_field('mem_policy'):
                numa_memory_policy = espec_utils.guest.mano_to_extra_spec_numa_memory_policy(guest_epa.numa_node_policy.mem_policy)
                if numa_memory_policy is not None:
                    epa_specs['hw:numa_mempolicy'] = numa_memory_policy

            if guest_epa.numa_node_policy.has_field('node'):
                for node in guest_epa.numa_node_policy.node:
                    if node.has_field('vcpu') and node.vcpu:
                        epa_specs['hw:numa_cpus.'+str(node.id)] = ','.join([str(j.id) for j in node.vcpu])
                    if node.memory_mb:
                        epa_specs['hw:numa_mem.'+str(node.id)] = str(node.memory_mb)

        if guest_epa.has_field('pcie_device'):
            pci_devices = []
            for device in guest_epa.pcie_device:
                pci_devices.append(device.device_id +':'+str(device.count))
            epa_specs['pci_passthrough:alias'] = ','.join(pci_devices)

        return epa_specs

    @staticmethod
    def _get_host_epa_specs(host_epa):
        """
        Returns EPA Specs dictionary for host_epa attributes
        """

        epa_specs = {}

        if host_epa.has_field('cpu_model'):
            cpu_model = espec_utils.host.mano_to_extra_spec_cpu_model(host_epa.cpu_model)
            if cpu_model is not None:
                epa_specs['capabilities:cpu_info:model'] = cpu_model

        if host_epa.has_field('cpu_arch'):
            cpu_arch = espec_utils.host.mano_to_extra_spec_cpu_arch(host_epa.cpu_arch)
            if cpu_arch is not None:
                epa_specs['capabilities:cpu_info:arch'] = cpu_arch

        if host_epa.has_field('cpu_vendor'):
            cpu_vendor = espec_utils.host.mano_to_extra_spec_cpu_vendor(host_epa.cpu_vendor)
            if cpu_vendor is not None:
                epa_specs['capabilities:cpu_info:vendor'] = cpu_vendor

        if host_epa.has_field('cpu_socket_count'):
            cpu_socket_count = espec_utils.host.mano_to_extra_spec_cpu_socket_count(host_epa.cpu_socket_count)
            if cpu_socket_count is not None:
                epa_specs['capabilities:cpu_info:topology:sockets'] = cpu_socket_count

        if host_epa.has_field('cpu_core_count'):
            cpu_core_count = espec_utils.host.mano_to_extra_spec_cpu_core_count(host_epa.cpu_core_count)
            if cpu_core_count is not None:
                epa_specs['capabilities:cpu_info:topology:cores'] = cpu_core_count

        if host_epa.has_field('cpu_core_thread_count'):
            cpu_core_thread_count = espec_utils.host.mano_to_extra_spec_cpu_core_thread_count(host_epa.cpu_core_thread_count)
            if cpu_core_thread_count is not None:
                epa_specs['capabilities:cpu_info:topology:threads'] = cpu_core_thread_count

        if host_epa.has_field('cpu_feature'):
            cpu_features = []
            espec_cpu_features = []
            for feature in host_epa.cpu_feature:
                cpu_features.append(feature.feature)
            espec_cpu_features = espec_utils.host.mano_to_extra_spec_cpu_features(cpu_features)
            if espec_cpu_features is not None:
                epa_specs['capabilities:cpu_info:features'] = espec_cpu_features
        return epa_specs

    @staticmethod
    def _get_hypervisor_epa_specs(guest_epa):
        """
        Returns EPA Specs dictionary for hypervisor_epa attributes
        """
        hypervisor_epa = {}
        return hypervisor_epa

    @staticmethod
    def _get_vswitch_epa_specs(guest_epa):
        """
        Returns EPA Specs dictionary for vswitch_epa attributes
        """
        vswitch_epa = {}
        return vswitch_epa

    @staticmethod
    def _get_host_aggregate_epa_specs(host_aggregate):
        """
        Returns EPA Specs dictionary for host aggregates
        """
        epa_specs = {}
        for aggregate in host_aggregate:
            epa_specs['aggregate_instance_extra_specs:'+aggregate.metadata_key] = aggregate.metadata_value

        return epa_specs

    @staticmethod
    def _get_epa_specs(flavor):
        """
        Returns epa_specs dictionary based on flavor information
        """
        epa_specs = {}
        if flavor.has_field('guest_epa'):
            guest_epa = RwcalOpenstackPlugin._get_guest_epa_specs(flavor.guest_epa)
            epa_specs.update(guest_epa)
        if flavor.has_field('host_epa'):
            host_epa = RwcalOpenstackPlugin._get_host_epa_specs(flavor.host_epa)
            epa_specs.update(host_epa)
        if flavor.has_field('hypervisor_epa'):
            hypervisor_epa = RwcalOpenstackPlugin._get_hypervisor_epa_specs(flavor.hypervisor_epa)
            epa_specs.update(hypervisor_epa)
        if flavor.has_field('vswitch_epa'):
            vswitch_epa = RwcalOpenstackPlugin._get_vswitch_epa_specs(flavor.vswitch_epa)
            epa_specs.update(vswitch_epa)
        if flavor.has_field('host_aggregate'):
            host_aggregate = RwcalOpenstackPlugin._get_host_aggregate_epa_specs(flavor.host_aggregate)
            epa_specs.update(host_aggregate)
        return epa_specs

    @rwstatus(ret_on_failure=[""])
    def do_create_flavor(self, account, flavor):
        """Create new flavor.

        Arguments:
            account - a cloud account
            flavor - flavor of the VM

        Returns:
            flavor id
        """
        epa_specs = RwcalOpenstackPlugin._get_epa_specs(flavor)
        with self._use_driver(account) as drv:
            return drv.nova_flavor_create(name      = flavor.name,
                                          ram       = flavor.vm_flavor.memory_mb,
                                          vcpus     = flavor.vm_flavor.vcpu_count,
                                          disk      = flavor.vm_flavor.storage_gb,
                                          epa_specs = epa_specs)


    @rwstatus
    def do_delete_flavor(self, account, flavor_id):
        """Delete flavor.

        Arguments:
            account - a cloud account
            flavor_id - id flavor of the VM
        """
        with self._use_driver(account) as drv:
            drv.nova_flavor_delete(flavor_id)

    @staticmethod
    def _fill_epa_attributes(flavor, flavor_info):
        """Helper function to populate the EPA attributes

        Arguments:
              flavor     : Object with EPA attributes
              flavor_info: A dictionary of flavor_info received from openstack
        Returns:
              None
        """
        getattr(flavor, 'vm_flavor').vcpu_count  = flavor_info['vcpus']
        getattr(flavor, 'vm_flavor').memory_mb   = flavor_info['ram']
        getattr(flavor, 'vm_flavor').storage_gb  = flavor_info['disk']

        ### If extra_specs in flavor_info
        if not 'extra_specs' in flavor_info:
            return

        for attr in flavor_info['extra_specs']:
            if attr == 'hw:cpu_policy':
                cpu_pinning_policy = espec_utils.guest.extra_spec_to_mano_cpu_pinning_policy(flavor_info['extra_specs']['hw:cpu_policy'])
                if cpu_pinning_policy is not None:
                    getattr(flavor, 'guest_epa').cpu_pinning_policy = cpu_pinning_policy

            elif attr == 'hw:cpu_threads_policy':
                cpu_thread_pinning_policy = espec_utils.guest.extra_spec_to_mano_cpu_thread_pinning_policy(flavor_info['extra_specs']['hw:cpu_threads_policy'])
                if cpu_thread_pinning_policy is not None:
                    getattr(flavor, 'guest_epa').cpu_thread_pinning_policy = cpu_thread_pinning_policy

            elif attr == 'hw:mem_page_size':
                mempage_size = espec_utils.guest.extra_spec_to_mano_mempage_size(flavor_info['extra_specs']['hw:mem_page_size'])
                if mempage_size is not None:
                    getattr(flavor, 'guest_epa').mempage_size = mempage_size


            elif attr == 'hw:numa_nodes':
                numa_node_count = espec_utils.guest.extra_specs_to_mano_numa_node_count(flavor_info['extra_specs']['hw:numa_nodes'])
                if numa_node_count is not None:
                    getattr(flavor,'guest_epa').numa_node_policy.node_cnt = numa_node_count

            elif attr.startswith('hw:numa_cpus.'):
                node_id = attr.split('.')[1]
                nodes = [ n for n in flavor.guest_epa.numa_node_policy.node if n.id == int(node_id) ]
                if nodes:
                    numa_node = nodes[0]
                else:
                    numa_node = getattr(flavor,'guest_epa').numa_node_policy.node.add()
                    numa_node.id = int(node_id)

                for x in flavor_info['extra_specs'][attr].split(','):
                   numa_node_vcpu = numa_node.vcpu.add()
                   numa_node_vcpu.id = int(x)

            elif attr.startswith('hw:numa_mem.'):
                node_id = attr.split('.')[1]
                nodes = [ n for n in flavor.guest_epa.numa_node_policy.node if n.id == int(node_id) ]
                if nodes:
                    numa_node = nodes[0]
                else:
                    numa_node = getattr(flavor,'guest_epa').numa_node_policy.node.add()
                    numa_node.id = int(node_id)

                numa_node.memory_mb =  int(flavor_info['extra_specs'][attr])

            elif attr == 'hw:numa_mempolicy':
                numa_memory_policy = espec_utils.guest.extra_to_mano_spec_numa_memory_policy(flavor_info['extra_specs']['hw:numa_mempolicy'])
                if numa_memory_policy is not None:
                    getattr(flavor,'guest_epa').numa_node_policy.mem_policy = numa_memory_policy

            elif attr == 'trust:trusted_host':
                trusted_execution = espec_utils.guest.extra_spec_to_mano_trusted_execution(flavor_info['extra_specs']['trust:trusted_host'])
                if trusted_execution is not None:
                    getattr(flavor,'guest_epa').trusted_execution = trusted_execution

            elif attr == 'pci_passthrough:alias':
                device_types = flavor_info['extra_specs']['pci_passthrough:alias']
                for device in device_types.split(','):
                    dev = getattr(flavor,'guest_epa').pcie_device.add()
                    dev.device_id = device.split(':')[0]
                    dev.count = int(device.split(':')[1])

            elif attr == 'capabilities:cpu_info:model':
                cpu_model = espec_utils.host.extra_specs_to_mano_cpu_model(flavor_info['extra_specs']['capabilities:cpu_info:model'])
                if cpu_model is not None:
                    getattr(flavor, 'host_epa').cpu_model = cpu_model

            elif attr == 'capabilities:cpu_info:arch':
                cpu_arch = espec_utils.host.extra_specs_to_mano_cpu_arch(flavor_info['extra_specs']['capabilities:cpu_info:arch'])
                if cpu_arch is not None:
                    getattr(flavor, 'host_epa').cpu_arch = cpu_arch

            elif attr == 'capabilities:cpu_info:vendor':
                cpu_vendor = espec_utils.host.extra_spec_to_mano_cpu_vendor(flavor_info['extra_specs']['capabilities:cpu_info:vendor'])
                if cpu_vendor is not None:
                    getattr(flavor, 'host_epa').cpu_vendor = cpu_vendor

            elif attr == 'capabilities:cpu_info:topology:sockets':
                cpu_sockets = espec_utils.host.extra_spec_to_mano_cpu_socket_count(flavor_info['extra_specs']['capabilities:cpu_info:topology:sockets'])
                if cpu_sockets is not None:
                    getattr(flavor, 'host_epa').cpu_socket_count = cpu_sockets

            elif attr == 'capabilities:cpu_info:topology:cores':
                cpu_cores = espec_utils.host.extra_spec_to_mano_cpu_core_count(flavor_info['extra_specs']['capabilities:cpu_info:topology:cores'])
                if cpu_cores is not None:
                    getattr(flavor, 'host_epa').cpu_core_count = cpu_cores

            elif attr == 'capabilities:cpu_info:topology:threads':
                cpu_threads = espec_utils.host.extra_spec_to_mano_cpu_core_thread_count(flavor_info['extra_specs']['capabilities:cpu_info:topology:threads'])
                if cpu_threads is not None:
                    getattr(flavor, 'host_epa').cpu_core_thread_count = cpu_threads

            elif attr == 'capabilities:cpu_info:features':
                cpu_features = espec_utils.host.extra_spec_to_mano_cpu_features(flavor_info['extra_specs']['capabilities:cpu_info:features'])
                if cpu_features is not None:
                    for feature in cpu_features:
                        getattr(flavor, 'host_epa').cpu_feature.append(feature)
            elif attr.startswith('aggregate_instance_extra_specs:'):
                    aggregate = getattr(flavor, 'host_aggregate').add()
                    aggregate.metadata_key = ":".join(attr.split(':')[1::])
                    aggregate.metadata_value = flavor_info['extra_specs'][attr]

    @staticmethod
    def _fill_flavor_info(flavor_info):
        """Create a GI object from flavor info dictionary

        Converts Flavor information dictionary object returned by openstack
        driver into Protobuf Gi Object

        Arguments:
            flavor_info: Flavor information from openstack

        Returns:
             Object of class FlavorInfoItem
        """
        flavor = RwcalYang.FlavorInfoItem()
        flavor.name                       = flavor_info['name']
        flavor.id                         = flavor_info['id']
        RwcalOpenstackPlugin._fill_epa_attributes(flavor, flavor_info)
        return flavor


    @rwstatus(ret_on_failure=[[]])
    def do_get_flavor_list(self, account):
        """Return flavor information.

        Arguments:
            account - a cloud account

        Returns:
            List of flavors
        """
        response = RwcalYang.VimResources()
        with self._use_driver(account) as drv:
            flavors = drv.nova_flavor_list()
        for flv in flavors:
            response.flavorinfo_list.append(RwcalOpenstackPlugin._fill_flavor_info(flv))
        return response

    @rwstatus(ret_on_failure=[None])
    def do_get_flavor(self, account, id):
        """Return flavor information.

        Arguments:
            account - a cloud account
            id - an id for the flavor

        Returns:
            Flavor info item
        """
        with self._use_driver(account) as drv:
            flavor = drv.nova_flavor_get(id)
        return RwcalOpenstackPlugin._fill_flavor_info(flavor)


    def _fill_network_info(self, network_info, account):
        """Create a GI object from network info dictionary

        Converts Network information dictionary object returned by openstack
        driver into Protobuf Gi Object

        Arguments:
            network_info - Network information from openstack
            account - a cloud account

        Returns:
            Network info item
        """
        network                  = RwcalYang.NetworkInfoItem()
        network.network_name     = network_info['name']
        network.network_id       = network_info['id']
        if ('provider:network_type' in network_info) and (network_info['provider:network_type'] != None):
            network.provider_network.overlay_type = network_info['provider:network_type'].upper()
        if ('provider:segmentation_id' in network_info) and (network_info['provider:segmentation_id']):
            network.provider_network.segmentation_id = network_info['provider:segmentation_id']
        if ('provider:physical_network' in network_info) and (network_info['provider:physical_network']):
            network.provider_network.physical_network = network_info['provider:physical_network'].upper()

        if 'subnets' in network_info and network_info['subnets']:
            subnet_id = network_info['subnets'][0]
            with self._use_driver(account) as drv:
                subnet = drv.neutron_subnet_get(subnet_id)
            network.subnet = subnet['cidr']
        return network

    @rwstatus(ret_on_failure=[[]])
    def do_get_network_list(self, account):
        """Return a list of networks

        Arguments:
            account - a cloud account

        Returns:
            List of networks
        """
        response = RwcalYang.VimResources()
        with self._use_driver(account) as drv:
            networks = drv.neutron_network_list()
        for network in networks:
            response.networkinfo_list.append(self._fill_network_info(network, account))
        return response

    @rwstatus(ret_on_failure=[None])
    def do_get_network(self, account, id):
        """Return a network

        Arguments:
            account - a cloud account
            id - an id for the network

        Returns:
            Network info item
        """
        with self._use_driver(account) as drv:
            network = drv.neutron_network_get(id)
        return self._fill_network_info(network, account)

    @rwstatus(ret_on_failure=[""])
    def do_create_network(self, account, network):
        """Create a new network

        Arguments:
            account - a cloud account
            network - Network object

        Returns:
            Network id
        """
        kwargs = {}
        kwargs['name']            = network.network_name
        kwargs['admin_state_up']  = True
        kwargs['external_router'] = False
        kwargs['shared']          = False

        if network.has_field('provider_network'):
            if network.provider_network.has_field('physical_network'):
                kwargs['physical_network'] = network.provider_network.physical_network
            if network.provider_network.has_field('overlay_type'):
                kwargs['network_type'] = network.provider_network.overlay_type.lower()
            if network.provider_network.has_field('segmentation_id'):
                kwargs['segmentation_id'] = network.provider_network.segmentation_id

        with self._use_driver(account) as drv:
            network_id = drv.neutron_network_create(**kwargs)
            drv.neutron_subnet_create(network_id = network_id,
                                      cidr = network.subnet)
        return network_id

    @rwstatus
    def do_delete_network(self, account, network_id):
        """Delete a network

        Arguments:
            account - a cloud account
            network_id - an id for the network
        """
        with self._use_driver(account) as drv:
            drv.neutron_network_delete(network_id)

    @staticmethod
    def _fill_port_info(port_info):
        """Create a GI object from port info dictionary

        Converts Port information dictionary object returned by openstack
        driver into Protobuf Gi Object

        Arguments:
            port_info - Port information from openstack

        Returns:
            Port info item
        """
        port = RwcalYang.PortInfoItem()

        port.port_name  = port_info['name']
        port.port_id    = port_info['id']
        port.network_id = port_info['network_id']
        port.port_state = port_info['status']
        if 'device_id' in port_info:
            port.vm_id = port_info['device_id']
        if 'fixed_ips' in port_info:
            port.ip_address = port_info['fixed_ips'][0]['ip_address']
        return port

    @rwstatus(ret_on_failure=[None])
    def do_get_port(self, account, port_id):
        """Return a port

        Arguments:
            account - a cloud account
            port_id - an id for the port

        Returns:
            Port info item
        """
        with self._use_driver(account) as drv:
            port = drv.neutron_port_get(port_id)

        return RwcalOpenstackPlugin._fill_port_info(port)

    @rwstatus(ret_on_failure=[[]])
    def do_get_port_list(self, account):
        """Return a list of ports

        Arguments:
            account - a cloud account

        Returns:
            Port info list
        """
        response = RwcalYang.VimResources()
        with self._use_driver(account) as drv:
            ports = drv.neutron_port_list(*{})
        for port in ports:
            response.portinfo_list.append(RwcalOpenstackPlugin._fill_port_info(port))
        return response

    @rwstatus(ret_on_failure=[""])
    def do_create_port(self, account, port):
        """Create a new port

        Arguments:
            account - a cloud account
            port - port object

        Returns:
            Port id
        """
        kwargs = {}
        kwargs['name'] = port.port_name
        kwargs['network_id'] = port.network_id
        kwargs['admin_state_up'] = True
        if port.has_field('vm_id'):
            kwargs['vm_id'] = port.vm_id
        if port.has_field('port_type'):
            kwargs['port_type'] = port.port_type
        else:
            kwargs['port_type'] = "normal"

        with self._use_driver(account) as drv:
            return drv.neutron_port_create(**kwargs)

    @rwstatus
    def do_delete_port(self, account, port_id):
        """Delete a port

        Arguments:
            account - a cloud account
            port_id - an id for port
        """
        with self._use_driver(account) as drv:
            drv.neutron_port_delete(port_id)

    @rwstatus(ret_on_failure=[""])
    def do_add_host(self, account, host):
        """Add a new host

        Arguments:
            account - a cloud account
            host - a host object

        Returns:
            An id for the host
        """
        raise NotImplementedError

    @rwstatus
    def do_remove_host(self, account, host_id):
        """Remove a host

        Arguments:
            account - a cloud account
            host_id - an id for the host
        """
        raise NotImplementedError

    @rwstatus(ret_on_failure=[None])
    def do_get_host(self, account, host_id):
        """Return a host

        Arguments:
            account - a cloud account
            host_id - an id for host

        Returns:
            Host info item
        """
        raise NotImplementedError

    @rwstatus(ret_on_failure=[[]])
    def do_get_host_list(self, account):
        """Return a list of hosts

        Arguments:
            account - a cloud account

        Returns:
            List of hosts
        """
        raise NotImplementedError

    @staticmethod
    def _fill_connection_point_info(c_point, port_info):
        """Create a GI object for RwcalYang.VDUInfoParams_ConnectionPoints()

        Converts Port information dictionary object returned by openstack
        driver into Protobuf Gi Object

        Arguments:
            port_info - Port information from openstack
        Returns:
            Protobuf Gi object for RwcalYang.VDUInfoParams_ConnectionPoints
        """
        c_point.name = port_info['name']
        c_point.connection_point_id = port_info['id']
        if ('fixed_ips' in port_info) and (len(port_info['fixed_ips']) >= 1):
            if 'ip_address' in port_info['fixed_ips'][0]:
                c_point.ip_address = port_info['fixed_ips'][0]['ip_address']
        if port_info['status'] == 'ACTIVE':
            c_point.state = 'active'
        else:
            c_point.state = 'inactive'
        if 'network_id' in port_info:
            c_point.virtual_link_id = port_info['network_id']
        if ('device_id' in port_info) and (port_info['device_id']):
            c_point.vdu_id = port_info['device_id']

    @staticmethod
    def _fill_virtual_link_info(network_info, port_list, subnet):
        """Create a GI object for VirtualLinkInfoParams

        Converts Network and Port information dictionary object
        returned by openstack driver into Protobuf Gi Object

        Arguments:
            network_info - Network information from openstack
            port_list - A list of port information from openstack
            subnet: Subnet information from openstack
        Returns:
            Protobuf Gi object for VirtualLinkInfoParams
        """
        link = RwcalYang.VirtualLinkInfoParams()
        link.name  = network_info['name']
        if network_info['status'] == 'ACTIVE':
            link.state = 'active'
        else:
            link.state = 'inactive'
        link.virtual_link_id = network_info['id']
        for port in port_list:
            if port['device_owner'] == 'compute:None':
                c_point = link.connection_points.add()
                RwcalOpenstackPlugin._fill_connection_point_info(c_point, port)

        if subnet != None:
            link.subnet = subnet['cidr']

        if ('provider:network_type' in network_info) and (network_info['provider:network_type'] != None):
            link.provider_network.overlay_type = network_info['provider:network_type'].upper()
        if ('provider:segmentation_id' in network_info) and (network_info['provider:segmentation_id']):
            link.provider_network.segmentation_id = network_info['provider:segmentation_id']
        if ('provider:physical_network' in network_info) and (network_info['provider:physical_network']):
            link.provider_network.physical_network = network_info['provider:physical_network'].upper()

        return link

    @staticmethod
    def _fill_vdu_info(vm_info, flavor_info, mgmt_network, port_list, server_group, volume_list = None):
        """Create a GI object for VDUInfoParams

        Converts VM information dictionary object returned by openstack
        driver into Protobuf Gi Object

        Arguments:
            vm_info - VM information from openstack
            flavor_info - VM Flavor information from openstack
            mgmt_network - Management network
            port_list - A list of port information from openstack
            server_group - A list (with one element or empty list) of server group to which this VM belongs
        Returns:
            Protobuf Gi object for VDUInfoParams
        """
        vdu = RwcalYang.VDUInfoParams()
        vdu.name = vm_info['name']
        vdu.vdu_id = vm_info['id']
        for network_name, network_info in vm_info['addresses'].items():
            if network_info and network_name == mgmt_network:
                for interface in network_info:
                    if 'OS-EXT-IPS:type' in interface:
                        if interface['OS-EXT-IPS:type'] == 'fixed':
                            vdu.management_ip = interface['addr']
                        elif interface['OS-EXT-IPS:type'] == 'floating':
                            vdu.public_ip = interface['addr']

        # Look for any metadata
        for key, value in vm_info['metadata'].items():
            if key == 'node_id':
                vdu.node_id = value
        if ('image' in vm_info) and ('id' in vm_info['image']):
            vdu.image_id = vm_info['image']['id']
        if ('flavor' in vm_info) and ('id' in vm_info['flavor']):
            vdu.flavor_id = vm_info['flavor']['id']

        if vm_info['status'] == 'ACTIVE':
            vdu.state = 'active'
        elif vm_info['status'] == 'ERROR':
            vdu.state = 'failed'
        else:
            vdu.state = 'inactive'

        if 'availability_zone' in vm_info:
            vdu.availability_zone = vm_info['availability_zone']

        if server_group:
            vdu.server_group.name = server_group[0]

        vdu.cloud_type  = 'openstack'
        # Fill the port information
        for port in port_list:
            c_point = vdu.connection_points.add()
            RwcalOpenstackPlugin._fill_connection_point_info(c_point, port)

        if flavor_info is not None:
            RwcalOpenstackPlugin._fill_epa_attributes(vdu, flavor_info)

        # Fill the volume information
        if volume_list is not None:
            for os_volume in volume_list:
                volr = vdu.volumes.add()
                try:
                   " Device name is of format /dev/vda"
                   vol_name = (os_volume['device']).split('/')[2]
                except:
                   continue
                volr.name = vol_name
                volr.volume_id = os_volume['volumeId']

        return vdu

    @rwcalstatus(ret_on_failure=[""])
    def do_create_virtual_link(self, account, link_params):
        """Create a new virtual link

        Arguments:
            account     - a cloud account
            link_params - information that defines the type of VDU to create

        Returns:
            The vdu_id
        """
        kwargs = {}
        kwargs['name']            = link_params.name
        kwargs['admin_state_up']  = True
        kwargs['external_router'] = False
        kwargs['shared']          = False

        if link_params.has_field('provider_network'):
            if link_params.provider_network.has_field('physical_network'):
                kwargs['physical_network'] = link_params.provider_network.physical_network
            if link_params.provider_network.has_field('overlay_type'):
                kwargs['network_type'] = link_params.provider_network.overlay_type.lower()
            if link_params.provider_network.has_field('segmentation_id'):
                kwargs['segmentation_id'] = link_params.provider_network.segmentation_id


        with self._use_driver(account) as drv:
            try:
                network_id = drv.neutron_network_create(**kwargs)
            except Exception as e:
                self.log.error("Encountered exceptions during network creation. Exception: %s", str(e))
                raise

            kwargs = {'network_id' : network_id,
                      'dhcp_params': {'enable_dhcp': True},
                      'gateway_ip' : None,}

            if link_params.ip_profile_params.has_field('ip_version'):
                kwargs['ip_version'] = 6 if link_params.ip_profile_params.ip_version == 'ipv6' else 4
            else:
                kwargs['ip_version'] = 4

            if link_params.ip_profile_params.has_field('subnet_address'):
                kwargs['cidr'] = link_params.ip_profile_params.subnet_address
            elif link_params.ip_profile_params.has_field('subnet_prefix_pool'):
                subnet_pool = drv.netruon_subnetpool_by_name(link_params.ip_profile_params.subnet_prefix_pool)
                if subnet_pool is None:
                    self.log.error("Could not find subnet pool with name :%s to be used for network: %s",
                                   link_params.ip_profile_params.subnet_prefix_pool,
                                   link_params.name)
                    raise NeutronException.NotFound("SubnetPool with name %s not found"%(link_params.ip_profile_params.subnet_prefix_pool))

                kwargs['subnetpool_id'] = subnet_pool['id']
            elif link_params.has_field('subnet'):
                kwargs['cidr'] = link_params.subnet
            else:
                assert 0, "No IP Prefix or Pool name specified"

            if link_params.ip_profile_params.has_field('dhcp_params'):
                if link_params.ip_profile_params.dhcp_params.has_field('enabled'):
                    kwargs['dhcp_params']['enable_dhcp'] = link_params.ip_profile_params.dhcp_params.enabled
                if link_params.ip_profile_params.dhcp_params.has_field('start_address'):
                    kwargs['dhcp_params']['start_address']  = link_params.ip_profile_params.dhcp_params.start_address
                if link_params.ip_profile_params.dhcp_params.has_field('count'):
                    kwargs['dhcp_params']['count']  = link_params.ip_profile_params.dhcp_params.count

            if link_params.ip_profile_params.has_field('dns_server'):
                kwargs['dns_server'] = []
                for server in link_params.ip_profile_params.dns_server:
                    kwargs['dns_server'].append(server.address)

            if link_params.ip_profile_params.has_field('gateway_address'):
                kwargs['gateway_ip'] = link_params.ip_profile_params.gateway_address

            drv.neutron_subnet_create(**kwargs)

        return network_id


    @rwstatus
    def do_delete_virtual_link(self, account, link_id):
        """Delete a virtual link

        Arguments:
            account - a cloud account
            link_id - id for the virtual-link to be deleted

        Returns:
            None
        """
        if not link_id:
            self.log.error("Empty link_id during the virtual link deletion")
            raise Exception("Empty link_id during the virtual link deletion")

        with self._use_driver(account) as drv:
            port_list = drv.neutron_port_list(**{'network_id': link_id})

        for port in port_list:
            if ((port['device_owner'] == 'compute:None') or (port['device_owner'] == '')):
                self.do_delete_port(account, port['id'], no_rwstatus=True)
        self.do_delete_network(account, link_id, no_rwstatus=True)

    @rwstatus(ret_on_failure=[None])
    def do_get_virtual_link(self, account, link_id):
        """Get information about virtual link.

        Arguments:
            account  - a cloud account
            link_id  - id for the virtual-link

        Returns:
            Object of type RwcalYang.VirtualLinkInfoParams
        """
        if not link_id:
            self.log.error("Empty link_id during the virtual link get request")
            raise Exception("Empty link_id during the virtual link get request")

        with self._use_driver(account) as drv:
            network = drv.neutron_network_get(link_id)
            if network:
                port_list = drv.neutron_port_list(**{'network_id': network['id']})
                if 'subnets' in network:
                    subnet = drv.neutron_subnet_get(network['subnets'][0])
                else:
                    subnet = None
                virtual_link = RwcalOpenstackPlugin._fill_virtual_link_info(network, port_list, subnet)
            else:
                virtual_link = None
            return virtual_link

    @rwstatus(ret_on_failure=[None])
    def do_get_virtual_link_list(self, account):
        """Get information about all the virtual links

        Arguments:
            account  - a cloud account

        Returns:
            A list of objects of type RwcalYang.VirtualLinkInfoParams
        """
        vnf_resources = RwcalYang.VNFResources()
        with self._use_driver(account) as drv:
            networks = drv.neutron_network_list()
            for network in networks:
                port_list = drv.neutron_port_list(**{'network_id': network['id']})
                if ('subnets' in network) and (network['subnets']):
                    subnet = drv.neutron_subnet_get(network['subnets'][0])
                else:
                    subnet = None
                virtual_link = RwcalOpenstackPlugin._fill_virtual_link_info(network, port_list, subnet)
                vnf_resources.virtual_link_info_list.append(virtual_link)
            return vnf_resources

    def _create_connection_point(self, account, c_point):
        """
        Create a connection point
        Arguments:
           account  - a cloud account
           c_point  - connection_points
        """
        kwargs = {}
        kwargs['name'] = c_point.name
        kwargs['network_id'] = c_point.virtual_link_id
        kwargs['admin_state_up'] = True

        if c_point.type_yang == 'VIRTIO' or c_point.type_yang == 'E1000':
            kwargs['port_type'] = 'normal'
        elif c_point.type_yang == 'SR_IOV':
            kwargs['port_type'] = 'direct'
        else:
            raise NotImplementedError("Port Type: %s not supported" %(c_point.type_yang))

        with self._use_driver(account) as drv:
            if c_point.has_field('security_group'):
                group = drv.neutron_security_group_by_name(c_point.security_group)
                if group is not None:
                    kwargs['security_groups'] = [group['id']]
            return drv.neutron_port_create(**kwargs)

    def _allocate_floating_ip(self, drv, pool_name):
        """
        Allocate a floating_ip. If unused floating_ip exists then its reused.
        Arguments:
          drv:       OpenstackDriver instance
          pool_name: Floating IP pool name

        Returns:
          An object of floating IP nova class (novaclient.v2.floating_ips.FloatingIP)
        """

        # available_ip = [ ip for ip in drv.nova_floating_ip_list() if ip.instance_id == None ]

        # if pool_name is not None:
        #     ### Filter further based on IP address
        #     available_ip = [ ip for ip in available_ip if ip.pool == pool_name ]

        # if not available_ip:
        #     floating_ip = drv.nova_floating_ip_create(pool_name)
        # else:
        #     floating_ip = available_ip[0]

        floating_ip = drv.nova_floating_ip_create(pool_name)
        return floating_ip

    def _match_vm_flavor(self, required, available):
        self.log.info("Matching VM Flavor attributes")
        if available.vcpu_count != required.vcpu_count:
            self.log.debug("VCPU requirement mismatch. Required: %d, Available: %d",
                            required.vcpu_count,
                            available.vcpu_count)
            return False
        if available.memory_mb != required.memory_mb:
            self.log.debug("Memory requirement mismatch. Required: %d MB, Available: %d MB",
                            required.memory_mb,
                            available.memory_mb)
            return False
        if available.storage_gb != required.storage_gb:
            self.log.debug("Storage requirement mismatch. Required: %d GB, Available: %d GB",
                            required.storage_gb,
                            available.storage_gb)
            return False
        self.log.debug("VM Flavor match found")
        return True

    def _match_guest_epa(self, required, available):
        self.log.info("Matching Guest EPA attributes")
        if required.has_field('pcie_device'):
            self.log.debug("Matching pcie_device")
            if available.has_field('pcie_device') == False:
                self.log.debug("Matching pcie_device failed. Not available in flavor")
                return False
            else:
                for dev in required.pcie_device:
                    if not [ d for d in available.pcie_device
                             if ((d.device_id == dev.device_id) and (d.count == dev.count)) ]:
                        self.log.debug("Matching pcie_device failed. Required: %s, Available: %s", required.pcie_device, available.pcie_device)
                        return False
        elif available.has_field('pcie_device'):
            self.log.debug("Rejecting available flavor because pcie_device not required but available")
            return False


        if required.has_field('mempage_size'):
            self.log.debug("Matching mempage_size")
            if available.has_field('mempage_size') == False:
                self.log.debug("Matching mempage_size failed. Not available in flavor")
                return False
            else:
                if required.mempage_size != available.mempage_size:
                    self.log.debug("Matching mempage_size failed. Required: %s, Available: %s", required.mempage_size, available.mempage_size)
                    return False
        elif available.has_field('mempage_size'):
            self.log.debug("Rejecting available flavor because mempage_size not required but available")
            return False

        if required.has_field('cpu_pinning_policy'):
            self.log.debug("Matching cpu_pinning_policy")
            if required.cpu_pinning_policy != 'ANY':
                if available.has_field('cpu_pinning_policy') == False:
                    self.log.debug("Matching cpu_pinning_policy failed. Not available in flavor")
                    return False
                else:
                    if required.cpu_pinning_policy != available.cpu_pinning_policy:
                        self.log.debug("Matching cpu_pinning_policy failed. Required: %s, Available: %s", required.cpu_pinning_policy, available.cpu_pinning_policy)
                        return False
        elif available.has_field('cpu_pinning_policy'):
            self.log.debug("Rejecting available flavor because cpu_pinning_policy not required but available")
            return False

        if required.has_field('cpu_thread_pinning_policy'):
            self.log.debug("Matching cpu_thread_pinning_policy")
            if available.has_field('cpu_thread_pinning_policy') == False:
                self.log.debug("Matching cpu_thread_pinning_policy failed. Not available in flavor")
                return False
            else:
                if required.cpu_thread_pinning_policy != available.cpu_thread_pinning_policy:
                    self.log.debug("Matching cpu_thread_pinning_policy failed. Required: %s, Available: %s", required.cpu_thread_pinning_policy, available.cpu_thread_pinning_policy)
                    return False
        elif available.has_field('cpu_thread_pinning_policy'):
            self.log.debug("Rejecting available flavor because cpu_thread_pinning_policy not required but available")
            return False

        if required.has_field('trusted_execution'):
            self.log.debug("Matching trusted_execution")
            if required.trusted_execution == True:
                if available.has_field('trusted_execution') == False:
                    self.log.debug("Matching trusted_execution failed. Not available in flavor")
                    return False
                else:
                    if required.trusted_execution != available.trusted_execution:
                        self.log.debug("Matching trusted_execution failed. Required: %s, Available: %s", required.trusted_execution, available.trusted_execution)
                        return False
        elif available.has_field('trusted_execution'):
            self.log.debug("Rejecting available flavor because trusted_execution not required but available")
            return False

        if required.has_field('numa_node_policy'):
            self.log.debug("Matching numa_node_policy")
            if available.has_field('numa_node_policy') == False:
                self.log.debug("Matching numa_node_policy failed. Not available in flavor")
                return False
            else:
                if required.numa_node_policy.has_field('node_cnt'):
                    self.log.debug("Matching numa_node_policy node_cnt")
                    if available.numa_node_policy.has_field('node_cnt') == False:
                        self.log.debug("Matching numa_node_policy node_cnt failed. Not available in flavor")
                        return False
                    else:
                        if required.numa_node_policy.node_cnt != available.numa_node_policy.node_cnt:
                            self.log.debug("Matching numa_node_policy node_cnt failed. Required: %s, Available: %s",required.numa_node_policy.node_cnt, available.numa_node_policy.node_cnt)
                            return False
                elif available.numa_node_policy.has_field('node_cnt'):
                    self.log.debug("Rejecting available flavor because numa node count not required but available")
                    return False

                if required.numa_node_policy.has_field('mem_policy'):
                    self.log.debug("Matching numa_node_policy mem_policy")
                    if available.numa_node_policy.has_field('mem_policy') == False:
                        self.log.debug("Matching numa_node_policy mem_policy failed. Not available in flavor")
                        return False
                    else:
                        if required.numa_node_policy.mem_policy != available.numa_node_policy.mem_policy:
                            self.log.debug("Matching numa_node_policy mem_policy failed. Required: %s, Available: %s", required.numa_node_policy.mem_policy, available.numa_node_policy.mem_policy)
                            return False
                elif available.numa_node_policy.has_field('mem_policy'):
                    self.log.debug("Rejecting available flavor because num node mem_policy not required but available")
                    return False

                if required.numa_node_policy.has_field('node'):
                    self.log.debug("Matching numa_node_policy nodes configuration")
                    if available.numa_node_policy.has_field('node') == False:
                        self.log.debug("Matching numa_node_policy nodes configuration failed. Not available in flavor")
                        return False
                    for required_node in required.numa_node_policy.node:
                        self.log.debug("Matching numa_node_policy nodes configuration for node %s", required_node)
                        numa_match = False
                        for available_node in available.numa_node_policy.node:
                            if required_node.id != available_node.id:
                                self.log.debug("Matching numa_node_policy nodes configuration failed. Required: %s, Available: %s", required_node, available_node)
                                continue
                            if required_node.vcpu != available_node.vcpu:
                                self.log.debug("Matching numa_node_policy nodes configuration failed. Required: %s, Available: %s", required_node, available_node)
                                continue
                            if required_node.memory_mb != available_node.memory_mb:
                                self.log.debug("Matching numa_node_policy nodes configuration failed. Required: %s, Available: %s", required_node, available_node)
                                continue
                            numa_match = True
                        if numa_match == False:
                            return False
                elif available.numa_node_policy.has_field('node'):
                    self.log.debug("Rejecting available flavor because numa nodes not required but available")
                    return False
        elif available.has_field('numa_node_policy'):
            self.log.debug("Rejecting available flavor because numa_node_policy not required but available")
            return False
        self.log.info("Successful match for Guest EPA attributes")
        return True

    def _match_vswitch_epa(self, required, available):
        self.log.debug("VSwitch EPA match found")
        return True

    def _match_hypervisor_epa(self, required, available):
        self.log.debug("Hypervisor EPA match found")
        return True

    def _match_host_epa(self, required, available):
        self.log.info("Matching Host EPA attributes")
        if required.has_field('cpu_model'):
            self.log.debug("Matching CPU model")
            if available.has_field('cpu_model') == False:
                self.log.debug("Matching CPU model failed. Not available in flavor")
                return False
            else:
                #### Convert all PREFER to REQUIRE since flavor will only have REQUIRE attributes
                if required.cpu_model.replace('PREFER', 'REQUIRE') != available.cpu_model:
                    self.log.debug("Matching CPU model failed. Required: %s, Available: %s", required.cpu_model, available.cpu_model)
                    return False
        elif available.has_field('cpu_model'):
            self.log.debug("Rejecting available flavor because cpu_model not required but available")
            return False

        if required.has_field('cpu_arch'):
            self.log.debug("Matching CPU architecture")
            if available.has_field('cpu_arch') == False:
                self.log.debug("Matching CPU architecture failed. Not available in flavor")
                return False
            else:
                #### Convert all PREFER to REQUIRE since flavor will only have REQUIRE attributes
                if required.cpu_arch.replace('PREFER', 'REQUIRE') != available.cpu_arch:
                    self.log.debug("Matching CPU architecture failed. Required: %s, Available: %s", required.cpu_arch, available.cpu_arch)
                    return False
        elif available.has_field('cpu_arch'):
            self.log.debug("Rejecting available flavor because cpu_arch not required but available")
            return False

        if required.has_field('cpu_vendor'):
            self.log.debug("Matching CPU vendor")
            if available.has_field('cpu_vendor') == False:
                self.log.debug("Matching CPU vendor failed. Not available in flavor")
                return False
            else:
                #### Convert all PREFER to REQUIRE since flavor will only have REQUIRE attributes
                if required.cpu_vendor.replace('PREFER', 'REQUIRE') != available.cpu_vendor:
                    self.log.debug("Matching CPU vendor failed. Required: %s, Available: %s", required.cpu_vendor, available.cpu_vendor)
                    return False
        elif available.has_field('cpu_vendor'):
            self.log.debug("Rejecting available flavor because cpu_vendor not required but available")
            return False

        if required.has_field('cpu_socket_count'):
            self.log.debug("Matching CPU socket count")
            if available.has_field('cpu_socket_count') == False:
                self.log.debug("Matching CPU socket count failed. Not available in flavor")
                return False
            else:
                if required.cpu_socket_count != available.cpu_socket_count:
                    self.log.debug("Matching CPU socket count failed. Required: %s, Available: %s", required.cpu_socket_count, available.cpu_socket_count)
                    return False
        elif available.has_field('cpu_socket_count'):
            self.log.debug("Rejecting available flavor because cpu_socket_count not required but available")
            return False

        if required.has_field('cpu_core_count'):
            self.log.debug("Matching CPU core count")
            if available.has_field('cpu_core_count') == False:
                self.log.debug("Matching CPU core count failed. Not available in flavor")
                return False
            else:
                if required.cpu_core_count != available.cpu_core_count:
                    self.log.debug("Matching CPU core count failed. Required: %s, Available: %s", required.cpu_core_count, available.cpu_core_count)
                    return False
        elif available.has_field('cpu_core_count'):
            self.log.debug("Rejecting available flavor because cpu_core_count not required but available")
            return False

        if required.has_field('cpu_core_thread_count'):
            self.log.debug("Matching CPU core thread count")
            if available.has_field('cpu_core_thread_count') == False:
                self.log.debug("Matching CPU core thread count failed. Not available in flavor")
                return False
            else:
                if required.cpu_core_thread_count != available.cpu_core_thread_count:
                    self.log.debug("Matching CPU core thread count failed. Required: %s, Available: %s", required.cpu_core_thread_count, available.cpu_core_thread_count)
                    return False
        elif available.has_field('cpu_core_thread_count'):
            self.log.debug("Rejecting available flavor because cpu_core_thread_count not required but available")
            return False

        if required.has_field('cpu_feature'):
            self.log.debug("Matching CPU feature list")
            if available.has_field('cpu_feature') == False:
                self.log.debug("Matching CPU feature list failed. Not available in flavor")
                return False
            else:
                for feature in required.cpu_feature:
                    if feature not in available.cpu_feature:
                        self.log.debug("Matching CPU feature list failed. Required feature: %s is not present. Available features: %s", feature, available.cpu_feature)
                        return False
        elif available.has_field('cpu_feature'):
            self.log.debug("Rejecting available flavor because cpu_feature not required but available")
            return False
        self.log.info("Successful match for Host EPA attributes")
        return True


    def _match_placement_group_inputs(self, required, available):
        self.log.info("Matching Host aggregate attributes")

        if not required and not available:
            # Host aggregate not required and not available => success
            self.log.info("Successful match for Host Aggregate attributes")
            return True
        if required and available:
            # Host aggregate requested and available => Do a match and decide
            xx = [ x.as_dict() for x in required ]
            yy = [ y.as_dict() for y in available ]
            for i in xx:
                if i not in yy:
                    self.log.debug("Rejecting available flavor because host Aggregate mismatch. Required: %s, Available: %s ", required, available)
                    return False
            self.log.info("Successful match for Host Aggregate attributes")
            return True
        else:
            # Either of following conditions => Failure
            #  - Host aggregate required but not available
            #  - Host aggregate not required but available
            self.log.debug("Rejecting available flavor because host Aggregate mismatch. Required: %s, Available: %s ", required, available)
            return False

    def match_epa_params(self, resource_info, request_params):
        result = self._match_vm_flavor(getattr(request_params, 'vm_flavor'),
                                       getattr(resource_info, 'vm_flavor'))
        if result == False:
            self.log.debug("VM Flavor mismatched")
            return False

        result = self._match_guest_epa(getattr(request_params, 'guest_epa'),
                                       getattr(resource_info, 'guest_epa'))
        if result == False:
            self.log.debug("Guest EPA mismatched")
            return False

        result = self._match_vswitch_epa(getattr(request_params, 'vswitch_epa'),
                                         getattr(resource_info, 'vswitch_epa'))
        if result == False:
            self.log.debug("Vswitch EPA mismatched")
            return False

        result = self._match_hypervisor_epa(getattr(request_params, 'hypervisor_epa'),
                                            getattr(resource_info, 'hypervisor_epa'))
        if result == False:
            self.log.debug("Hypervisor EPA mismatched")
            return False

        result = self._match_host_epa(getattr(request_params, 'host_epa'),
                                      getattr(resource_info, 'host_epa'))
        if result == False:
            self.log.debug("Host EPA mismatched")
            return False

        result = self._match_placement_group_inputs(getattr(request_params, 'host_aggregate'),
                                                    getattr(resource_info, 'host_aggregate'))

        if result == False:
            self.log.debug("Host Aggregate mismatched")
            return False

        return True

    def _select_resource_flavor(self, account, vdu_init):
        """
            Select a existing flavor if it matches the request or create new flavor
        """
        flavor = RwcalYang.FlavorInfoItem()
        flavor.name = str(uuid.uuid4())
        epa_types = ['vm_flavor', 'guest_epa', 'host_epa', 'host_aggregate', 'hypervisor_epa', 'vswitch_epa']
        epa_dict = {k: v for k, v in vdu_init.as_dict().items() if k in epa_types}
        flavor.from_dict(epa_dict)

        rc, response = self.do_get_flavor_list(account)
        if rc != RwTypes.RwStatus.SUCCESS:
            self.log.error("Get-flavor-info-list operation failed for cloud account: %s",
                        account.name)
            raise OpenstackCALOperationFailure("Get-flavor-info-list operation failed for cloud account: %s" %(account.name))

        flavor_id = None
        flavor_list = response.flavorinfo_list
        self.log.debug("Received %d flavor information from RW.CAL", len(flavor_list))
        for flv in flavor_list:
            self.log.info("Attempting to match compute requirement for VDU: %s with flavor %s",
                       vdu_init.name, flv)
            if self.match_epa_params(flv, vdu_init):
                self.log.info("Flavor match found for compute requirements for VDU: %s with flavor name: %s, flavor-id: %s",
                           vdu_init.name, flv.name, flv.id)
                return flv.id

        if account.openstack.dynamic_flavor_support is False:
            self.log.error("Unable to create flavor for compute requirement for VDU: %s. VDU instantiation failed", vdu_init.name)
            raise OpenstackCALOperationFailure("No resource available with matching EPA attributes")
        else:
            rc,flavor_id = self.do_create_flavor(account,flavor)
            if rc != RwTypes.RwStatus.SUCCESS:
                self.log.error("Create-flavor operation failed for cloud account: %s",
                        account.name)
                raise OpenstackCALOperationFailure("Create-flavor operation failed for cloud account: %s" %(account.name))
            return flavor_id

    def _create_vm(self, account, vduinfo, pci_assignement=None, server_group=None, port_list=None, network_list=None, imageinfo_list=None):
        """Create a new virtual machine.

        Arguments:
            account - a cloud account
            vminfo - information that defines the type of VM to create

        Returns:
            The image id
        """
        kwargs = {}
        kwargs['name']      = vduinfo.name
        kwargs['flavor_id'] = vduinfo.flavor_id
        if vduinfo.has_field('image_id'):
            kwargs['image_id']  = vduinfo.image_id
        else:
            kwargs['image_id']  = ""

        with self._use_driver(account) as drv:
            ### If floating_ip is required and we don't have one, better fail before any further allocation
            if vduinfo.has_field('allocate_public_address') and vduinfo.allocate_public_address:
                if account.openstack.has_field('floating_ip_pool'):
                    pool_name = account.openstack.floating_ip_pool
                else:
                    pool_name = None
                floating_ip = self._allocate_floating_ip(drv, pool_name)
            else:
                floating_ip = None

        if vduinfo.has_field('vdu_init') and vduinfo.vdu_init.has_field('userdata'):
            kwargs['userdata'] = vduinfo.vdu_init.userdata
        else:
            kwargs['userdata'] = ''

        if account.openstack.security_groups:
            kwargs['security_groups'] = account.openstack.security_groups

        kwargs['port_list'] = port_list
        kwargs['network_list'] = network_list

        metadata = {}
        # Add all metadata related fields
        if vduinfo.has_field('node_id'):
            metadata['node_id'] = vduinfo.node_id
        if pci_assignement is not None:
            metadata['pci_assignement'] = pci_assignement
        kwargs['metadata'] = metadata

        if vduinfo.has_field('availability_zone') and vduinfo.availability_zone.has_field('name'):
            kwargs['availability_zone']  = vduinfo.availability_zone
        else:
            kwargs['availability_zone'] = None

        if server_group is not None:
            kwargs['scheduler_hints'] = {'group': server_group}
        else:
            kwargs['scheduler_hints'] = None

        kwargs['block_device_mapping_v2'] = None
        if vduinfo.has_field('volumes') :
            kwargs['block_device_mapping_v2'] = []
            with self._use_driver(account) as drv:
            # Only support image->volume
                for volume in vduinfo.volumes:
                    block_map = dict()
                    block_map['boot_index'] = volume.boot_params.boot_priority
                    # Match retrived image info with volume based image name and checksum
                    if volume.image is not None:
                       matching_images = [img for img in imageinfo_list if img['name'] == volume.image]
                       if volume.image_checksum is not None:
                          matching_images = [img for img in matching_images if img['checksum'] == volume.image_checksum]
                       img_id = matching_images[0]['id']
                    if img_id is None:
                       raise OpenstackCALOperationFailure("Create-vdu operation failed. Volume image not found for name {} checksum {}".format(volume.name, volume.checksum))
                    block_map['uuid'] = img_id
                    block_map['device_name'] = volume.name
                    block_map['source_type'] = "image"
                    block_map['destination_type'] = "volume"
                    block_map['volume_size'] = volume.size
                    block_map['delete_on_termination'] = True
                    kwargs['block_device_mapping_v2'].append(block_map)
                
           
        with self._use_driver(account) as drv:
            vm_id = drv.nova_server_create(**kwargs)
            if floating_ip:
                self.prepare_vdu_on_boot(account, vm_id, floating_ip)

        return vm_id

    def get_openstack_image_info(self, account, image_name, image_checksum=None):
        self.log.debug("Looking up image id for image name %s and checksum %s on cloud account: %s",
                image_name, image_checksum, account.name
                )

        image_list = []
        with self._use_driver(account) as drv:
            image_list = drv.glance_image_list()
        matching_images = [img for img in image_list if img['name'] == image_name]
  
        # If the image checksum was filled in then further filter the images by the checksum
        if image_checksum is not None:
            matching_images = [img for img in matching_images if img['checksum'] == image_checksum]
        else:
            self.log.warning("Image checksum not provided.  Lookup using image name (%s) only.",
                                image_name) 
  
        if len(matching_images) == 0:
            raise ResMgrCALOperationFailure("Could not find image name {} (using checksum: {}) for cloud account: {}".format(
                  image_name, image_checksum, account.name
                  ))
  
        elif len(matching_images) > 1:
            unique_checksums = {i.checksum for i in matching_images}
            if len(unique_checksums) > 1:
                msg = ("Too many images with different checksums matched "
                         "image name of %s for cloud account: %s" % (image_name, account.name))
                raise ResMgrCALOperationFailure(msg)
  
        return matching_images[0]

    @rwcalstatus(ret_on_failure=[""])
    def do_create_vdu(self, account, vdu_init):
        """Create a new virtual deployment unit

        Arguments:
            account     - a cloud account
            vdu_init  - information about VDU to create (RwcalYang.VDUInitParams)

        Returns:
            The vdu_id
        """
        ### First create required number of ports aka connection points
        with self._use_driver(account) as drv:
            ### If floating_ip is required and we don't have one, better fail before any further allocation
            if vdu_init.has_field('allocate_public_address') and vdu_init.allocate_public_address:
                if account.openstack.has_field('floating_ip_pool'):
                    pool_name = account.openstack.floating_ip_pool
                else:
                    pool_name = None
                floating_ip = self._allocate_floating_ip(drv, pool_name)
            else:
                floating_ip = None

        port_list = []
        network_list = []
        imageinfo_list = []
        for c_point in vdu_init.connection_points:
            if c_point.virtual_link_id in network_list:
                assert False, "Only one port per network supported. Refer: http://specs.openstack.org/openstack/nova-specs/specs/juno/implemented/nfv-multiple-if-1-net.html"
            else:
                network_list.append(c_point.virtual_link_id)
            port_id = self._create_connection_point(account, c_point)
            port_list.append(port_id)

        if not vdu_init.has_field('flavor_id'):
            vdu_init.flavor_id = self._select_resource_flavor(account,vdu_init)

        ### Obtain all images for volumes and perform validations
        if vdu_init.has_field('volumes'):
            for volume in vdu_init.volumes:
                if "image" in volume:
                    image_checksum = volume.image_checksum if volume.has_field("image_checksum") else None
                    image_info = self.get_openstack_image_info(account, volume.image, image_checksum)
                    imageinfo_list.append(image_info)
        elif vdu_init.has_field('image_id'):
            with self._use_driver(account) as drv:
                image_info = drv.glance_image_get(vdu_init.image_id)
                imageinfo_list.append(image_info)

        if not imageinfo_list:
            err_str = ("VDU has no image information")
            self.log.error(err_str)
            raise OpenstackCALOperationFailure("Create-vdu operation failed. Error- %s" % err_str)

        ### Check VDU Virtual Interface type and make sure VM with property exists
        if vdu_init.connection_points:
                ### All virtual interfaces need to be of the same type for Openstack Accounts
                if not (all(cp.type_yang == 'E1000' for cp in vdu_init.connection_points) or all(cp.type_yang != 'E1000' for cp in vdu_init.connection_points)):
                    ### We have a mix of E1000 & VIRTIO/SR_IPOV virtual interface types in the VDU, abort instantiation.
                    assert False, "Only one type of Virtual Intefaces supported for Openstack accounts. Found a mix of VIRTIO/SR_IOV & E1000."

                ## It is not clear if all the images need to checked for HW properties. In the absence of model info describing each image's properties,
                ###   we shall assume that all images need to have similar properties
                for img_info in imageinfo_list:

                    virt_intf_type = vdu_init.connection_points[0].type_yang
                    if virt_intf_type == 'E1000':
                        if 'hw_vif_model' in img_info and img_info.hw_vif_model == 'e1000':
                            self.log.debug("VDU has Virtual Interface E1000, found matching image with property hw_vif_model=e1000")
                        else:
                            err_str = ("VDU has Virtual Interface E1000, but image '%s' does not have property hw_vif_model=e1000" % img_info.name)
                            self.log.error(err_str)
                            raise OpenstackCALOperationFailure("Create-vdu operation failed. Error- %s" % err_str)
                    elif virt_intf_type == 'VIRTIO' or virt_intf_type == 'SR_IOV':
                        if 'hw_vif_model' in img_info:
                            err_str = ("VDU has Virtual Interface %s, but image '%s' has hw_vif_model mismatch" % virt_intf_type,img_info.name)
                            self.log.error(err_str)
                            raise OpenstackCALOperationFailure("Create-vdu operation failed. Error- %s" % err_str)
                        else:
                            self.log.debug("VDU has Virtual Interface %s, found matching image" % virt_intf_type)
                    else:
                        err_str = ("VDU Virtual Interface '%s' not supported yet" % virt_intf_type)
                        self.log.error(err_str)
                        raise OpenstackCALOperationFailure("Create-vdu operation failed. Error- %s" % err_str)

        with self._use_driver(account) as drv:
            ### Now Create VM
            vm_network_list = []
            vm_network_list.append(drv._mgmt_network_id)

            if vdu_init.has_field('volumes'):
                # Only combination supported: Image->Volume
                for volume in vdu_init.volumes:
                    if "image" not in volume:
                        err_str = ("VDU Volume source not supported yet")
                        self.log.error(err_str)
                        raise OpenstackCALOperationFailure("Create-vdu operation failed. Error- %s" % err_str)
                    if "guest_params" not in volume:
                        err_str = ("VDU Volume destination parameters '%s' not defined")
                        self.log.error(err_str)
                        raise OpenstackCALOperationFailure("Create-vdu operation failed. Error- %s" % err_str)
                    if not volume.guest_params.has_field('device_type'):
                        err_str = ("VDU Volume destination type '%s' not defined")
                        self.log.error(err_str)
                        raise OpenstackCALOperationFailure("Create-vdu operation failed. Error- %s" % err_str)
                    if volume.guest_params.device_type != 'disk':
                        err_str = ("VDU Volume destination type '%s' not supported" % volume.guest_params.device_type)
                        self.log.error(err_str)
                        raise OpenstackCALOperationFailure("Create-vdu operation failed. Error- %s" % err_str)


            server_group = None
            if vdu_init.has_field('server_group'):
                ### Get list of server group in openstack for name->id mapping
                openstack_group_list = drv.nova_server_group_list()
                group_id = [ i['id'] for i in openstack_group_list if i['name'] == vdu_init.server_group.name]
                if len(group_id) != 1:
                    raise OpenstackServerGroupError("VM placement failed. Server Group %s not found in openstack. Available groups" %(vdu_init.server_group.name, [i['name'] for i in openstack_group_list]))
                server_group = group_id[0]

            pci_assignement = self.prepare_vpci_metadata(drv, vdu_init)
            if pci_assignement == '':
                pci_assignement = None

            vm_id = self._create_vm(account, vdu_init, pci_assignement=pci_assignement, server_group=server_group, port_list=port_list, network_list=vm_network_list, imageinfo_list = imageinfo_list)
            return vm_id

    def prepare_vpci_metadata(self, drv, vdu_init):
        pci_assignement = ''
        ### TEF specific metadata creation for
        virtio_vpci = []
        sriov_vpci = []
        virtio_meta = ''
        sriov_meta = ''
        ### For MGMT interface
        if vdu_init.has_field('mgmt_vpci'):
            xx = 'u\''+ drv._mgmt_network_id + '\' :[[u\'' + vdu_init.mgmt_vpci + '\', ' + '\'\']]'
            virtio_vpci.append(xx)

        for c_point in vdu_init.connection_points:
            if c_point.has_field('vpci'):
                if c_point.has_field('vpci') and c_point.type_yang == 'VIRTIO':
                    xx = 'u\''+c_point.virtual_link_id + '\' :[[u\'' + c_point.vpci + '\', ' + '\'\']]'
                    virtio_vpci.append(xx)
                elif c_point.has_field('vpci') and c_point.type_yang == 'SR_IOV':
                    xx = '[u\'' + c_point.vpci + '\', ' + '\'\']'
                    sriov_vpci.append(xx)

        if virtio_vpci:
            virtio_meta += ','.join(virtio_vpci)

        if sriov_vpci:
            sriov_meta = 'u\'VF\': ['
            sriov_meta += ','.join(sriov_vpci)
            sriov_meta += ']'

        if virtio_meta != '':
            pci_assignement +=  virtio_meta
            pci_assignement += ','

        if sriov_meta != '':
            pci_assignement +=  sriov_meta

        if pci_assignement != '':
            pci_assignement = '{' + pci_assignement + '}'

        return pci_assignement



    def prepare_vdu_on_boot(self, account, server_id, floating_ip):
        cmd = PREPARE_VM_CMD.format(auth_url     = account.openstack.auth_url,
                                    username     = account.openstack.key,
                                    password     = account.openstack.secret,
                                    tenant_name  = account.openstack.tenant,
                                    mgmt_network = account.openstack.mgmt_network,
                                    server_id    = server_id)

        if floating_ip is not None:
            cmd += (" --floating_ip "+ floating_ip.ip)

        exec_path = 'python3 ' + os.path.dirname(openstack_drv.__file__)
        exec_cmd = exec_path+'/'+cmd
        self.log.info("Running command: %s" %(exec_cmd))
        subprocess.call(exec_cmd, shell=True)

    @rwstatus
    def do_modify_vdu(self, account, vdu_modify):
        """Modify Properties of existing virtual deployment unit

        Arguments:
            account     -  a cloud account
            vdu_modify  -  Information about VDU Modification (RwcalYang.VDUModifyParams)
        """
        ### First create required number of ports aka connection points
        port_list = []
        network_list = []
        for c_point in vdu_modify.connection_points_add:
            if c_point.virtual_link_id in network_list:
                assert False, "Only one port per network supported. Refer: http://specs.openstack.org/openstack/nova-specs/specs/juno/implemented/nfv-multiple-if-1-net.html"
            else:
                network_list.append(c_point.virtual_link_id)
            port_id = self._create_connection_point(account, c_point)
            port_list.append(port_id)

        ### Now add the ports to VM
        for port_id in port_list:
            with self._use_driver(account) as drv:
                drv.nova_server_add_port(vdu_modify.vdu_id, port_id)

        ### Delete the requested connection_points
        for c_point in vdu_modify.connection_points_remove:
            self.do_delete_port(account, c_point.connection_point_id, no_rwstatus=True)

        if vdu_modify.has_field('image_id'):
            with self._use_driver(account) as drv:
                drv.nova_server_rebuild(vdu_modify.vdu_id, vdu_modify.image_id)


    @rwstatus
    def do_delete_vdu(self, account, vdu_id):
        """Delete a virtual deployment unit

        Arguments:
            account - a cloud account
            vdu_id  - id for the vdu to be deleted

        Returns:
            None
        """
        if not vdu_id:
            self.log.error("empty vdu_id during the vdu deletion")
            return

        with self._use_driver(account) as drv:
            ### Get list of floating_ips associated with this instance and delete them
            floating_ips = [ f for f in drv.nova_floating_ip_list() if f.instance_id == vdu_id ]
            for f in floating_ips:
                drv.nova_drv.floating_ip_delete(f)

            ### Get list of port on VM and delete them.
            port_list = drv.neutron_port_list(**{'device_id': vdu_id})

        for port in port_list:
            if ((port['device_owner'] == 'compute:None') or (port['device_owner'] == '')):
                self.do_delete_port(account, port['id'], no_rwstatus=True)

        self.do_delete_vm(account, vdu_id, no_rwstatus=True)


    @rwstatus(ret_on_failure=[None])
    def do_get_vdu(self, account, vdu_id):
        """Get information about a virtual deployment unit.

        Arguments:
            account - a cloud account
            vdu_id  - id for the vdu

        Returns:
            Object of type RwcalYang.VDUInfoParams
        """
        with self._use_driver(account) as drv:

            ### Get list of ports excluding the one for management network
            port_list = [p for p in drv.neutron_port_list(**{'device_id': vdu_id}) if p['network_id'] != drv.get_mgmt_network_id()]

            vm = drv.nova_server_get(vdu_id)

            flavor_info = None
            if ('flavor' in vm) and ('id' in vm['flavor']):
                try:
                    flavor_info = drv.nova_flavor_get(vm['flavor']['id'])
                except Exception as e:
                    self.log.critical("Exception encountered while attempting to get flavor info for flavor_id: %s. Exception: %s" %(vm['flavor']['id'], str(e)))

            openstack_group_list = drv.nova_server_group_list()
            server_group = [ i['name'] for i in openstack_group_list if vm['id'] in i['members']]
            openstack_srv_volume_list = drv.nova_volume_list(vm['id'])
            vdu_info = RwcalOpenstackPlugin._fill_vdu_info(vm,
                                                           flavor_info,
                                                           account.openstack.mgmt_network,
                                                           port_list,
                                                           server_group,
                                                           volume_list = openstack_srv_volume_list)
            if vdu_info.state == 'active':
                try:
                    console_info = drv.nova_server_console(vdu_info.vdu_id)
                except Exception as e:
                    pass
                else:
                    vdu_info.console_url = console_info['console']['url']
                    pass

            return vdu_info


    @rwstatus(ret_on_failure=[None])
    def do_get_vdu_list(self, account):
        """Get information about all the virtual deployment units

        Arguments:
            account     - a cloud account

        Returns:
            A list of objects of type RwcalYang.VDUInfoParams
        """
        vnf_resources = RwcalYang.VNFResources()
        with self._use_driver(account) as drv:
            vms = drv.nova_server_list()
            for vm in vms:
                ### Get list of ports excluding one for management network
                port_list = [p for p in drv.neutron_port_list(**{'device_id': vm['id']}) if p['network_id'] != drv.get_mgmt_network_id()]

                flavor_info = None

                if ('flavor' in vm) and ('id' in vm['flavor']):
                    try:
                        flavor_info = drv.nova_flavor_get(vm['flavor']['id'])
                    except Exception as e:
                        self.log.critical("Exception encountered while attempting to get flavor info for flavor_id: %s. Exception: %s" %(vm['flavor']['id'], str(e)))

                else:
                    flavor_info = None

                openstack_group_list = drv.nova_server_group_list()
                server_group = [ i['name'] for i in openstack_group_list if vm['id'] in i['members']]

                openstack_srv_volume_list = drv.nova_volume_list(vm['id'])
                vdu = RwcalOpenstackPlugin._fill_vdu_info(vm,
                                                          flavor_info,
                                                          account.openstack.mgmt_network,
                                                          port_list,
                                                          server_group,
                                                          volume_list = openstack_srv_volume_list)
                if vdu.state == 'active':
                    try:
                        console_info = drv.nova_server_console(vdu.vdu_id)
                    except Exception as e:
                        pass
                    else:
                        vdu.console_url = console_info['console']['url']
                        pass
                vnf_resources.vdu_info_list.append(vdu)
            return vnf_resources


