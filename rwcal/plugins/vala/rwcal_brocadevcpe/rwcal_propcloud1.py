
# STANDARD_RIFT_IO_COPYRIGHT

import os
import logging
import rw_status
import rift.cal.rwcal_status as rwcal_status
import rift.rwcal.brocadevcpe as brocadevcpe_drv
import contextlib
import rwlogger
import paramiko
import ipaddress
import uuid
import subprocess
import re
from gi import require_version
require_version('RwcalYang', '1.0')

from gi.repository import (
    GObject,
    RwCal,
    RwTypes,
    RwcalYang,
    VyattaServiceDhcpServerV1Yang)


class UnknownAccountError(Exception):
    pass


class MissingFileError(Exception):
    pass


class ImageLocationError(Exception):
    pass

class UninitializedPluginError(Exception):
    pass


rwstatus_exception_map = { IndexError: RwTypes.RwStatus.NOTFOUND,
                           KeyError: RwTypes.RwStatus.NOTFOUND,
                           NotImplementedError: RwTypes.RwStatus.NOT_IMPLEMENTED,}


rwstatus = rw_status.rwstatus_from_exc_map(rwstatus_exception_map)
rwcalstatus = rwcal_status.rwcalstatus_from_exc_map(rwstatus_exception_map)

PREPARE_VM_CMD = "prepare_vm.py --host {host} --username {username} --password {password} --mgmt_network {mgmt_network} --public_ip_pool {public_ip_pool} --wan_interface {wan_interface} --server_id {server_id} "

class RwcalBrocadeVcpe(GObject.Object, RwCal.Cloud):
    """Implementation for the CAL VALA methods required for Brocade vCPE. """

    instance_num = 1

    def _fill_reserved_flavor_attributes(self):
        flavor_dict = dict()
        flavor_dict['id'] = str(uuid.uuid1())
        flavor_dict['name'] = 'm1.reserved'
        flavor_dict['ram'] = 4096
        flavor_dict['disk'] = 40
        flavor_dict['vcpus'] = 2
        return flavor_dict

    def __init__(self):
        GObject.Object.__init__(self)
        self.log = logging.getLogger('rwcal.brocadevcpe.%s' % RwcalBrocadeVcpe.instance_num)
        self.log.setLevel(logging.DEBUG)
        self._driver_class = brocadevcpe_drv.BrocadeVcpeDriver
        self._rwlog_handler = None
        self._tenant_name = None
        self._flavor_list = []
        self._add_reserved_flavor = self._flavor_list.append(self._fill_reserved_flavor_attributes())
        RwcalBrocadeVcpe.instance_num += 1

    @contextlib.contextmanager
    def _use_driver(self, account):
        #if self._rwlog_handler is None:
        #    raise UninitializedPluginError("Must call init() in CAL plugin before use.")

        #with rwlogger.rwlog_root_handler(self._rwlog_handler):
            try:
                drv = self._driver_class(
                                  log = self.log,
                                  host = account.prop_cloud1.host,
                                  username  = account.prop_cloud1.username,
                                  password = account.prop_cloud1.password,
                                  mgmt_network = account.prop_cloud1.mgmt_network,
                                  )

            except Exception as e:
                self.log.error("RwcalBrocadeVcpe: Brocade vcpe init failed. Exception: %s" %(str(e)))
                raise

            yield drv


    @rwstatus
    def do_init(self, rwlog_ctx):
        self._rwlog_handler = rwlogger.RwLogger(
                category="rw-cal-log",
                subcategory="prop-cloud1",
                log_hdl=rwlog_ctx,
                )
        self.log.addHandler(self._rwlog_handler)
        self.log.propagate = True
        self.log.info("Initialized Brocade vcpe driver")

    @rwstatus(ret_on_failure=[None])
    def do_validate_cloud_creds(self, account):
        """
        Validates the cloud account credentials for the specified account.
        If creds are not valid, returns an error code & reason string
        Arguments:
            account - a cloud account to validate

        Returns:
            Validation Code and Details String
        """
        status = RwcalYang.CloudConnectionStatus(
                status="success",
                details=""
                )
        # VCPE driver cloud checks
        # 0. Netconf enablement is implicitly checked with netconf connection
        try:
            drv = self._driver_class(
                                  log = self.log,
                                  host = account.prop_cloud1.host,
                                  username  = account.prop_cloud1.username,
                                  password = account.prop_cloud1.password,
                                  mgmt_network = account.prop_cloud1.mgmt_network,
                                  )
        except:
            self.log.debug("Exception during driver instantiation")
            status = RwcalYang.CloudConnectionStatus(
                status="failure",
                details="Netconf connection to host was unsuccesful"
                )
            return status
        # 1. Check loopback interface for mgmt
        lolist = drv.get_lo_interfaces()
        if lolist is None or lolist.loopback is None:
            status = RwcalYang.CloudConnectionStatus(
                status="failure",
                details="Loopback interface for mgmt cannot be obtained from VCPE")
            return status
        mgmt_loopback_found = False
        for lo in lolist.loopback:
            if 'description' in lo:
                 wordlist = lo.description.split()
                 self.log.debug("wordlist for %s", lo.tagnode)
                 if len(wordlist) == 3:
                     if wordlist[0] != "RIFTLO":
                         continue
                     if wordlist[1] != account.prop_cloud1.mgmt_network:
                         continue
                     try:
                         mgmt_subn = ipaddress.IPv4Network(wordlist[2])
                         if mgmt_subn is not None:
                            mgmt_loopback_found = True
                     except:
                         continue
                    

        if mgmt_loopback_found is False:
            status = RwcalYang.CloudConnectionStatus(
                status="failure",
                details="RIFT loopback interface for mgmt cannot be obtained from VCPE"
                )
            return status
        # 2. Check presence of WAN interface
        dp = drv.get_dp_interface(account.prop_cloud1.wan_interface)
        if dp is None:
           status = RwcalYang.CloudConnectionStatus(
               status="failure",
               details="WAN interface not found"
               )
           return status
        # 3. Check for Brocade rest configuration
        http_service = drv.get_http_service()
        if http_service is None:
           status = RwcalYang.CloudConnectionStatus(
               status="failure",
               details="Brocade REST is not enabled"
               )
           return status
        self.log.debug("Validate success ")
  
        return status

    @rwstatus(ret_on_failure=[None])
    def do_get_management_network(self, account):
        """
        Returns the management network associated with the specified account.
        Arguments:
            account - a cloud account

        Returns:
            The management network
        """
        raise NotImplementedError()

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

        tpt = paramiko.Transport((account.prop_cloud1.host, 22)) 
        try:
           tpt.connect(username="vyatta",password="vyatta")
        except  Exception as e:
           self.log.warn('Could not connect to VCPE: %s: %s', e)
           return

        sftp = paramiko.SFTPClient.from_transport(tpt)
        destination = "/tmp/{}".format(image.name)
        try:
            # If the use passed in a file descriptor, use that to
            # upload the image.
            try:
                if image.has_field("fileno"):
                    self.log.debug("Image fileno ")
                    new_fileno = os.dup(image.fileno)
                    hdl = os.fdopen(new_fileno, 'rb')
                else:
                    self.log.debug("Image location ")
                    hdl = open(image.location, "rb")
            except Exception as e:
                self.log.error("Could not open file for upload. Exception received: %s", str(e))
                raise

            with hdl as fd:
                # SFTP image
                try:
                    sftp.putfo(fd,destination)
                except Exception as e: 
                    self.log.warn('*** Caught exception: %s: %s', e.__class__, e) 
                            
            with self._use_driver(account) as drv:
                drv.create_image(image.name)
                image_id = image.name
                self.log.info("Successfully uploaded image: %s", image.name)

        except Exception as e:
            self.log.error("Could not upload image. Exception received: %s", str(e))

        finally:
            sftp.remove(destination)
            sftp.close()
            tpt.close()
            self.log.info("Cleaning up vcpe /tmp directory")

        return image_id

    @rwstatus
    def do_delete_image(self, account, image_id):
        """Delete a vm image.

        Arguments:
            account - a cloud account
            image_id - id of the image to delete
        """
        with self._use_driver(account) as drv:
            drv.delete_image(image_id=image_id)


    @staticmethod
    def _fill_image_info(img_info):
        """Create a GI object from image info dictionary

        Converts image information dictionary object returned by vCPE
        driver into Protobuf Gi Object

        Arguments:
            img_info - YangOutput_VyattaVirtualizationV1_ListImages_Images

        VCPE specifics:
            Image is considered active if present
            No way to differentiate if image is qcow or ISO yet

        Returns:
            The ImageInfoItem
        """
        img = RwcalYang.ImageInfoItem()
        img.name = img_info.image
        img.id = img_info.image
        #img.checksum = img_info['checksum']
        img.disk_format = 'qcow2'
        img.container_format =  'bare'
        img.state = 'active'
        return img

    @rwstatus(ret_on_failure=[[]])
    def do_get_image_list(self, account):
        """Return a list of the names of all available images.

        Arguments:
            account - a cloud account

        Returns:
            The the list of images in VimResources object
        """
        self.log.debug("Getting image list")
        response = RwcalYang.VimResources()
        with self._use_driver(account) as drv:
            images = drv.get_image_list()
        for img_dict in images:
            response.imageinfo_list.append(RwcalBrocadeVcpe._fill_image_info(img_dict))
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
            image = drv.get_image(image_id)
        return RwcalBrocadeVcpe._fill_image_info(image) 

    @rwstatus
    def do_create_vm(self, account, vm):
        raise NotImplementedError()

    @rwstatus
    def do_start_vm(self, account, vm_id):
        raise NotImplementedError()

    @rwstatus
    def do_stop_vm(self, account, vm_id):
        raise NotImplementedError()

    @rwstatus
    def do_delete_vm(self, account, vm_id):
        raise NotImplementedError()

    @rwstatus
    def do_reboot_vm(self, account, vm_id):
        raise NotImplementedError()

    @rwstatus(ret_on_failure=[[]])
    def do_get_vm_list(self, account):
        return RwcalYang.VimResources()


    def _fill_flavor_create_attributes(flavor):
        flavor_dict = dict()
        flavor_dict['id'] = str(uuid.uuid1())
        flavor_dict['name'] = flavor.name
        flavor_dict['ram'] = flavor.vm_flavor.memory_mb
        flavor_dict['disk'] = flavor.vm_flavor.storage_gb
        flavor_dict['vcpus'] = flavor.vm_flavor.vcpu_count 
        return flavor_dict

    @rwstatus
    def do_create_flavor(self, account, flavor):
        '''
           Locally creating flavor as vCPE does not support explicit flavor APIs
        '''
        flavor_dict = RwcalBrocadeVcpe._fill_flavor_create_attributes(flavor) 
        self._flavor_list.append(flavor_dict)
        return flavor_dict['id']

    @rwstatus
    def do_delete_flavor(self, account, flavor_id):
         for flavor in self._flavor_list:
             if flavor_id == flavor['id']:
                 self._flavor_list.remove(flavor)

    @staticmethod
    def _fill_flavor_attributes(flavor, flavor_info):
        if 'ram' in flavor_info and flavor_info['ram']:
            getattr(flavor, 'vm_flavor').memory_mb   = flavor_info['ram']
        if 'disk' in flavor_info and flavor_info['disk']:
            getattr(flavor, 'vm_flavor').storage_gb  = flavor_info['disk']
        if 'vcpus' in flavor_info and flavor_info['vcpus']:
            getattr(flavor, 'vm_flavor').vcpu_count  = flavor_info['vcpus']

    @staticmethod
    def _fill_flavor_info(flavor_info):
        flavor = RwcalYang.FlavorInfoItem()
        flavor.name                       = flavor_info['name']
        flavor.id                         = flavor_info['id']
        RwcalBrocadeVcpe._fill_flavor_attributes(flavor, flavor_info)
        return flavor

    @rwstatus(ret_on_failure=[None])
    def do_get_flavor(self, account, flavor_id):
        for flavor_info in self._flavor_list:
             if flavor_id == flavor_info['id']:
                 return RwcalBrocadeVcpe._fill_flavor_info(flavor_info)


    @rwstatus(ret_on_failure=[[]])
    def do_get_flavor_list(self, account):
        response = RwcalYang.VimResources()
        for flavor_info in self._flavor_list:
            response.flavorinfo_list.append(RwcalBrocadeVcpe._fill_flavor_info(flavor_info))
        return response

    @rwstatus
    def do_add_host(self, account, host):
        raise NotImplementedError()

    @rwstatus
    def do_remove_host(self, account, host_id):
        raise NotImplementedError()

    @rwstatus(ret_on_failure=[None])
    def do_get_host(self, account, host_id):
        raise NotImplementedError()

    @rwstatus(ret_on_failure=[[]])
    def do_get_host_list(self, account):
        raise NotImplementedError()

    @rwstatus
    def do_create_port(self, account, port):
        raise NotImplementedError()

    @rwstatus
    def do_delete_port(self, account, port_id):
        raise NotImplementedError()

    @rwstatus(ret_on_failure=[None])
    def do_get_port(self, account, port_id):
        raise NotImplementedError()

    @rwstatus(ret_on_failure=[[]])
    def do_get_port_list(self, account):
        return RwcalYang.VimResources()

    @rwstatus
    def do_create_network(self, account, network):
        raise NotImplementedError()

    @rwstatus
    def do_delete_network(self, account, network_id):
        raise NotImplementedError()

    @rwstatus(ret_on_failure=[None])
    def do_get_network(self, account, network_id):
        raise NotImplementedError()

    @rwstatus(ret_on_failure=[[]])
    def do_get_network_list(self, account):
        raise NotImplementedError()

    @rwcalstatus(ret_on_failure=[""])
    def do_create_virtual_link(self, account, link_params):
        self.log.debug("Creating virtual link name %s subnet %s", link_params.name, link_params.subnet)
        #link params {\'provider_network\': {}, \'name\': \'TS2.Link1\', \'subnet\': \'11.0.0.0/24\', \'ip_profile_params\': {\'subnet_address\': \'11.1.0.0/16\', \'ip_version\': \'ipv4\', \'dhcp_params\': {\'enabled\': True}}}

        subnet = link_params.subnet
        if 'ip_profile_params' in link_params:
            # Assuming IPv4 for now
            if 'subnet_address' in link_params.ip_profile_params:
                subnet = link_params.ip_profile_params.subnet_address
                self.log.debug("Updating to subnet %s", subnet)

        with self._use_driver(account) as drv:
            #network_id = drv.create_l3_network(link_params.name, link_params.subnet)
            # we will use loopbacks to represent Nw id
            lo_intfname = self._find_next_lo_port(drv)
            if lo_intfname is not None:
               network_id = drv.create_lo_interface(lo_intfname, link_params.name, subnet)
            return network_id

    @rwstatus
    def do_delete_virtual_link(self, account, link_id):
        self.log.debug("Deleting virtual link %s", link_id)
        with self._use_driver(account) as drv:
            #drv.delete_l3_network(link_id)
            # Using loopbacks to represent Nw id
            lolist = drv.get_lo_interfaces()
            self.log.debug("Got loopback list %s", lolist)
            lointf_shortlist= [lointf.tagnode for lointf in lolist.loopback if link_id == lointf.tagnode]
            self.log.debug("lointf short list %s", lointf_shortlist)
            drv.delete_lo_intf(lointf_shortlist[0])
            return link_id

    @staticmethod
    def get_uuid(name):
        if name == None:
              raise ValueError("Name cannot be None")
        return str(uuid.uuid3(uuid.NAMESPACE_DNS, name))

    @staticmethod
    def _fill_connection_point_info(c_point, port_info, port_ip, vhost_intf):
        if ('description' in vhost_intf) and (len(vhost_intf.description.split()) == 6):
           c_point.name = vhost_intf.description.split()[5]
        else:
           c_point.name = port_info.name
        c_point.connection_point_id = vhost_intf.name
        if port_ip is not None:
            c_point.ip_address = port_ip
            c_point.state = 'active'
        else:
            c_point.state = 'inactive'
        if 'description' in vhost_intf:
            c_point.virtual_link_id = (vhost_intf.description.split())[1]
        if ('device_id' in port_info) and (port_info['device_id']):
            c_point.vdu_id = port_info['device_id']
        #print("Fill_VL_info Adding cp  ", c_point)

    def _fill_virtual_link_info(self, drv, network_info, vmcfglist=None):
        self.log.debug("Filling VL info for network_info %s", network_info)
        if 'description' not in network_info:
            return None
        link = RwcalYang.VirtualLinkInfoParams()
        link.state = 'active'
        link.name     = network_info.description.split()[1]
        link.virtual_link_id = network_info.tagnode
        if vmcfglist is None:
            return link

        parent_subn = ipaddress.IPv4Network((network_info.description.split())[2])
       
        #print("Fill_VL_info parent nw ", str(parent_subn))
        for vm_cfg in vmcfglist.guest:
            #print("Fill_VL_info ports for ", vm_cfg.name)
            for port in vm_cfg.devices.network:
                vhost_intf = drv.get_vhost_interface(port.name)
                #print("Fill_VL_info port name  ", port.name, vhost_intf)
                if vhost_intf is not None: 
                   if 'description' not in vhost_intf:
                       continue
                   if "RIFTVHOST" not in vhost_intf.description:
                       continue
                   port_ip = RwcalBrocadeVcpe._get_static_port_ip(vhost_intf)
                   #print("Fill_VL_info port name  ", port_ip)
                   if (port_ip is not None) and (ipaddress.IPv4Address(port_ip) in parent_subn):
                        #print("Fill_VL_info Adding cp  ")
                        c_point = link.connection_points.add()
                        RwcalBrocadeVcpe._fill_connection_point_info(c_point, port, port_ip, vhost_intf)
        return link

    @rwstatus(ret_on_failure=[None])
    def do_get_virtual_link(self, account, link_id):
        with self._use_driver(account) as drv:
            lointf = drv.get_lo_interface(link_id)
            if lointf is not None:
                vmcfglist, vmstatelist = drv.get_vm_list()
                return self._fill_virtual_link_info(drv, lointf, vmcfglist=vmcfglist)

    @rwstatus(ret_on_failure=[""])
    def do_get_virtual_link_list(self, account):
        response = RwcalYang.VNFResources()
        with self._use_driver(account) as drv:
            lolist = drv.get_lo_interfaces()
            vmcfglist, vmstatelist = drv.get_vm_list()
            for lointf in lolist.loopback:
               self.log.debug("VL network : %s", lointf)
               response.virtual_link_info_list.append(self._fill_virtual_link_info(drv, lointf, vmcfglist=vmcfglist))
        return response

    def _find_next_vhost_port(self, drv):
        vhostlist = drv.get_vhost_interfaces()
        if vhostlist is None:
           return "dp0vhost1"
        shortlist = [intf.name for intf in vhostlist.vhost]
        self.log.debug("shortlist %s", shortlist)
        for num in range(1,100): 
           vhost_intf = "dp0vhost" + str(num)
           if vhost_intf not in shortlist:
               return vhost_intf
    
    def _get_next_vl_child_nw(self, parent_nw, max_ctr):
        self.log.debug("_get_next_vl_child_nw: parent_nw %s max_ctr %s", parent_nw, max_ctr)
        parent_subn = ipaddress.IPv4Network(parent_nw)
        gen = parent_subn.subnets(new_prefix=24)
        ctr = 0
        try:
            for child_subn in gen:
                self.log.debug("child_subn %s", str(child_subn))
                ctr += 1
                if ctr <= int(max_ctr):
                    self.log.debug("Continuing..")
                    continue
                break
        except StopIteration:
                pass
                 
        return parent_subn, child_subn

    def _find_next_lo_port(self, drv):
        lolist = drv.get_lo_interfaces()
        shortlist = [intf.tagnode for intf in lolist.loopback]
        self.log.debug("shortlist %s", shortlist)
        for num in range(1,100): 
           loname = "lo" + str(num)
           if loname not in shortlist:
               return loname

    def _add_vm_port(self, drv, vdu_id, vlink_id, lointf, networks, dhcp_server, mgmt=False, cp_name=None):
        self.log.debug("Adding VM port for %s with lointf %s", vlink_id, lointf)
        # Networks received are really lo interfaces
        ctr_list = []
        max_ctr = 0
        nw_basename = lointf.description.split()[1]
        parent_nw = lointf.description.split()[2]
        for nw in networks:
            self.log.debug("add_vm_port: nw %s", nw)
            if nw_basename in nw.tagnode:
                # Splitting "mgmt0" into mgmt and "0" and append "0" to ctrlist
                xx = nw.tagnode.split(nw_basename)
                ctr_list.append(int(xx[1]))
                max_ctr = max(ctr_list) + 1

        vhost_intf = self._find_next_vhost_port(drv)
        if vhost_intf is not None:
            self.log.debug("Found free vhost port %s", vhost_intf)
            nw = dhcp_server.shared_network_name.add()
            nw.tagnode = nw_basename + str(max_ctr)
            # Create new network
            self.log.debug("Parent nw exists %s", parent_nw)
            # If parent NW exists, get new child subnet for this cp
            parent_subn, child_subn = self._get_next_vl_child_nw(parent_nw, max_ctr)
            self.log.debug("Got free subn %s", str(child_subn))
            nw.description = "RIFTVL" + " " + nw_basename + " " + str(child_subn)
                
            # Assign IP address for vhost
            # set interfaces vhost dp0vhost6 address 192.168.10.1/28
            hostlist = list(child_subn.hosts())
            ip_addr = str(hostlist[0]) + "/" + str(child_subn.prefixlen)
            if mgmt:
                metadata = "RIFTVHOST" + " " + nw_basename + " " + str(child_subn) + " " + nw.tagnode + " " + vdu_id
            else:
                metadata = "RIFTVHOST" + " " + nw_basename + " " + str(child_subn) + " " + nw.tagnode + " " + vdu_id + " " + cp_name
            drv.create_vhost_intf(vhost_intf, ip_addr=ip_addr, metadata=metadata)
            self.log.debug("Created vhost intf %s with IP addr %s", vhost_intf, ip_addr)
            # Add L3 NW pairs for each vhost
            # subnet 192.168.10.0/30 start 192.168.10.2 stop '192.168.10.2'
            s1 = nw.subnet.add()
            s1.tagnode = str(child_subn)
            range1 = s1.start.add()
            range1.tagnode = str(hostlist[0])
            range1.stop = str(hostlist[1])
            # If mgmt port: Add Default route
            if mgmt:
               # Get DNS info
               dns_server = drv.get_dns_server_info()
               #default-router '192.168.1.1'
               s1.default_router = str(hostlist[0])
               # Add DNS server
               if dns_server:
                   s1.dns_server.append(dns_server)
            else:
               # Static route for VM coming up
               # subnet 192.168.10.0/28 static-route destination-subnet '192.168.10.0/24'
               s1.static_route.destination_subnet = str(parent_subn)
               # subnet 192.168.10.0/28 static-route router '192.168.10.1'
               s1.static_route.router = str(hostlist[0])

            # Get Random MAC addr
            mac_addr = drv.get_mac_addr()
            assert(mac_addr)

            # Code to do Static mapping of MAC to IP
            #static_map = dhcp_server.static_mapping.add()
            #static_map.tagnode = "".join(mac_addr.split(":"))
            #static_map.mac_address = mac_addr
            #static_map.ip_address = str(hostlist[1])

            # Interface should be up before starting DHCP server
            # set service dhcp-server listento interface 'dp0vhost6'
            dhcp_server.listento.interface.append(vhost_intf)
           
            return vhost_intf, mac_addr
        else:
            raise

    def prepare_vdu_on_boot(self, account, server_id):
        cmd = PREPARE_VM_CMD.format(host = account.prop_cloud1.host,
                                    username     = account.prop_cloud1.username,
                                    password     = account.prop_cloud1.password,
                                    mgmt_network = account.prop_cloud1.mgmt_network,
                                    public_ip_pool = account.prop_cloud1.public_ip_pool,
                                    wan_interface = account.prop_cloud1.wan_interface,
                                    server_id    = server_id)

        exec_path = 'python3 ' + os.path.dirname(brocadevcpe_drv.__file__)
        exec_cmd = exec_path+'/'+cmd
        self.log.info("Running command: %s" %(exec_cmd))
        subprocess.call(exec_cmd, shell=True)
 
    @rwcalstatus(ret_on_failure=[""])
    def do_create_vdu(self, account, vdu_init):
        with self._use_driver(account) as drv:
            port_list = list()

            # Add connection points
            if len(vdu_init.connection_points) or account.prop_cloud1.mgmt_network:
                lolist = drv.get_lo_interfaces()
                networklist = drv.get_l3_network_list()
                dhcp_server = VyattaServiceDhcpServerV1Yang.YangData_VyattaServicesV1_Service_DhcpServer()

            if account.prop_cloud1.mgmt_network:
                self.log.debug("Adding mgmt ports for VDU")
                lointf = [lointf for lointf in lolist.loopback if account.prop_cloud1.mgmt_network in lointf.description]
                vhost_intf, mac_addr = self._add_vm_port(drv, vdu_init.name, account.prop_cloud1.mgmt_network, lointf[0], networklist, dhcp_server, mgmt=True)
                port_list.append((vhost_intf, mac_addr))
            
            self.log.debug("Adding connection points for VDU")
            for c_point in vdu_init.connection_points:
                self.log.debug("Adding c_point link_id %s, c_point name %s", c_point.virtual_link_id , c_point.name)
                lointf_shortlist= [lointf for lointf in lolist.loopback if c_point.virtual_link_id == lointf.tagnode]
                self.log.debug("lointf short list %s", lointf_shortlist)
                vhost_intf, mac_addr = self._add_vm_port(drv, vdu_init.name, c_point.virtual_link_id, lointf_shortlist[0], networklist, dhcp_server, cp_name = c_point.name)
                port_list.append((vhost_intf, mac_addr))

                
            disk_list = []
            if 'volumes' in vdu_init:
                for volume in vdu_init.volumes:
                    if "image" in volume:
                        disk = dict()
                        disk['type'] = volume.device_type
                        new_image = drv.copy_tmp_image(volume.image)
                        disk['image'] = new_image
                        disk['boot-order'] = volume.boot_priority
                        disk_list.append(disk)
                    else:
                        self.log.info("Volume source not supported")
            else:
                disk0 = dict()
                disk0['type'] = "disk"
                disk0['image'] = drv.copy_tmp_image(vdu_init.image_id)
                disk0['boot-order'] = 1
                disk_list.append(disk0)

            # Change name to remove allow only alpha-numerics
            restricted_name = re.sub('[^a-zA-Z0-9]', '', vdu_init.name)
            vm_id, portstate_list = drv.create_vm(restricted_name, vdu_init.vm_flavor.vcpu_count, vdu_init.vm_flavor.memory_mb, disk_list, port_list=port_list)

            if dhcp_server is not None:
               drv.merge_dhcp_server_config(dhcp_server)

            #self.prepare_vdu_on_boot(account, vm_id)

            return vm_id
            

    @rwstatus
    def do_modify_vdu(self, account, vdu_modify):
        pass

    @staticmethod
    def _get_vm_vhost_list( drv, vdu_id):
        vm_cfg, vm_state = drv.get_vm(vdu_id)

        if 'devices' in vm_cfg and 'network' in vm_cfg.devices:
           vhost_list = [(x.name, x.mac_address) for x in  vm_cfg.devices.network ]
           return vhost_list

    # Gets the second IP on the vhost intf
    @staticmethod
    def _get_static_port_ip(vhost_intf):
        child_subn_str = (vhost_intf.description.split())[2]
        child_subn = ipaddress.IPv4Network(child_subn_str)
        host_gen = child_subn.hosts()
        snip1 = host_gen.__next__()
        snip2 = host_gen.__next__()
        return str(snip2)

    @staticmethod
    def _fill_vdu_info( drv, account, vm_cfg, vm_state):
        vdu = RwcalYang.VDUInfoParams()
        vdu.name = vm_cfg.name
        vdu.vdu_id = vm_cfg.name

        if ('image' in vm_cfg) and ('id' in vm_cfg['image']):
            vdu.image_id = vm_cfg['image']['id']
        if ('flavor' in vm_state) and ('id' in vm_state['flavor']):
            vdu.flavor_id = vm_cfg['flavor']['id']
        #vdu.cloud_type  = 'prop_cloud1'

        for port in vm_cfg.devices.network:
            vhost_intf = drv.get_vhost_interface(port.name)
            if vhost_intf is not None: 
                if 'description' not in vhost_intf:
                    continue
                if "RIFTVHOST" not in vhost_intf.description:
                    continue
                port_ip = RwcalBrocadeVcpe._get_static_port_ip(vhost_intf)
                if port_ip is None:
                    continue
                if (vhost_intf.description.split())[1] == account.prop_cloud1.mgmt_network:
                    vdu.management_ip = port_ip
                    _, public_ip = drv.get_floating_ip_info(vdu.management_ip)
                    if public_ip is not None:
                       vdu.public_ip = public_ip
                    else:
                       vdu.public_ip = drv.assign_floating_ip(account.prop_cloud1.public_ip_pool, vdu.management_ip, account.prop_cloud1.wan_interface)
                else:
                    c_point = vdu.connection_points.add()
                    RwcalBrocadeVcpe._fill_connection_point_info(c_point, port, port_ip, vhost_intf)



        # Data from vcpe
        # {'memory_limit': 4194304, 'state': 'running', 'name': 'cal_vdu', 'uuid': 'd7d1bfca-55ac-11e6-8354-001b21b98a89', 'memory_current': 4194304, 'cpu_time': 132050000000, 'cpu_count': 2}

        if 'state' not in vm_state:
            vdu.state = 'inactive'
            return vdu
        if vm_state.state == 'running':
            vdu.state = 'active'
        elif vm_state.state in ['nostate', 'blocked', 'crashed']:
            vdu.state = 'failed'
        else:
            vdu.state = 'inactive'

        #if vdu.flavor_id:
        #   flavor = drv.get_flavor(vdu.flavor_id)
        #   RwcalBrocadeVcpe._fill_epa_attributes(vdu, flavor)
        return vdu

    @rwstatus
    def do_delete_vdu(self, account, vdu_id):
        self.log.info("Deleting VDU %s", vdu_id)
        if not vdu_id:
            self.log.error("empty vdu_id during the vdu deletion")
            return

        with self._use_driver(account) as drv:
            # Get mgmt IP 
            vm_cfg, vm_state = drv.get_vm(vdu_id)
            vdu_data = RwcalBrocadeVcpe._fill_vdu_info(drv, account, vm_cfg, vm_state)
            if (vdu_data.public_ip is not None) and (vdu_data.management_ip is not None):
                self.log.debug("Deleting floating ip %s", vdu_data.management_ip)
                drv.delete_floating_ip(vdu_data.management_ip)
            # Get temporary images for this VM
            image_list = [disk.source.file for disk in vm_cfg.devices.disk]
            # Get vhost names and VM-mac for this VM
            vm_vhost_list = RwcalBrocadeVcpe._get_vm_vhost_list(drv, vdu_id)
            vhostlist = drv.get_vhost_interfaces()
            self.log.debug("Delete vdu: vm_vhost_list %s", vm_vhost_list)

            for vhostintf in vhostlist.vhost:
               if 'description' not in vhostintf:
                   continue
               if ("RIFTVHOST" in vhostintf.description) and (vdu_id in vhostintf.description):
                   # Delete L3 subnet created for this vhost
                   shared_nw = (vhostintf.description.split())[3]
                   self.log.debug("Delete vdu: shared_nw %s ", shared_nw)
                   # Delete DHCP shared nw
                   self.log.debug("Deleting DHCP shared nw ")
                   drv.delete_l3_network(shared_nw)
                   # Delete DHCP listener
                   self.log.debug("Deleting DHCP listener %s", vhostintf.name)
                   drv.delete_dhcp_listener(vhostintf.name)

            self.log.debug("Delete vdu: Child subnet deletion done")
            try:
               # Delete VM (kills connection points as well)
               drv.delete_vm(vdu_id)
               # Delete attached vhost interfaces
               self.log.info("Deleting interfaces in %s", vm_vhost_list)
               for vhostintf in vm_vhost_list:
                  self.log.info("Deleting MAC lease %s", vhostintf[1])
                  drv.delete_dhcp_lease(vhostintf[1])
                  self.log.info("Deleting interface %s", vhostintf[0])
                  drv.delete_vhost_intf(vhostintf[0])

               self.log.debug("Deleting image_list %s", image_list)
               for image in image_list:
                  drv.delete_image(os.path.basename(image))
            except:
               pass
            self.log.debug("Delete vdu: Finished")

    @rwstatus(ret_on_failure=[None])
    def do_get_vdu(self, account, vdu_id):
        vdu_info = None
        with self._use_driver(account) as drv:
            vm_cfg, vm_state = drv.get_vm(vdu_id)
            if vm_cfg is None or vm_state is None:
                return None
            vdu_info = RwcalBrocadeVcpe._fill_vdu_info(drv, account, vm_cfg, vm_state)
            self.log.info("Returning VDU data %s", vdu_info)
            return vdu_info

    @rwstatus(ret_on_failure=[""])
    def do_get_vdu_list(self, account):
        vnf_resource = RwcalYang.VNFResources()
        vnf_resource.vdu_info_list = []
        with self._use_driver(account) as drv:
            vmcfglist, vmstatelist = drv.get_vm_list()
        if vmcfglist is None or vmstatelist is None:
            return vnf_resource
        for vm_cfg in vmcfglist.guest:
            vmstatetemplist = [vmstate for vmstate in vmstatelist.guest if vmstate.name == vm_cfg.name]
            vdu_data = RwcalBrocadeVcpe._fill_vdu_info(drv, account, vm_cfg, vmstatetemplist[0])
            assert(vdu_data)
            vnf_resource.vdu_info_list.append(vdu_data)
        return vnf_resource





    












