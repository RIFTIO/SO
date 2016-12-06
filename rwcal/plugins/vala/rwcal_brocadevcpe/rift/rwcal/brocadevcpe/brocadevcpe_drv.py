#!/usr/bin/python

# STANDARD_RIFT_IO_COPYRIGHT

import logging
import uuid
import re
import ipaddress
import subprocess
import tempfile

from .mgmt_session import (
              NetconfSession,
              ProxyRequestTimeout,
              ProxyRequestError,
              ProxyConnectionError
              )
from .brocade_rest import BrocadeRestSession

from gi import require_version
require_version('RwcalYang', '1.0')
require_version('VyattaVirtualizationV1Yang', '1.0')
require_version('VyattaInterfacesVhostBridgeV1Yang', '1.0')
require_version('VyattaInterfacesVhostV1Yang', '1.0')
require_version('VyattaInterfacesVhostVifV1Yang', '1.0')
require_version('VyattaInterfacesVhostPbrV1Yang', '1.0')
require_version('VyattaServiceDhcpServerV1Yang', '1.0')
require_version('VyattaServiceNatV1Yang', '1.0')
require_version('VyattaInterfacesLoopbackV1Yang', '1.0')
require_version('VyattaIpv6RtradvV1Yang', '1.0')
require_version('VyattaServiceHttpsV1Yang', '1.0')
require_version('RiftVyattaCompositeYang', '1.0')
from gi.repository import (
    RwYang,
    VyattaVirtualizationV1Yang,
    VyattaInterfacesVhostBridgeV1Yang,
    VyattaInterfacesVhostV1Yang,
    VyattaInterfacesVhostVifV1Yang,
    VyattaInterfacesVhostPbrV1Yang,
    VyattaServiceDhcpServerV1Yang,
    VyattaServiceNatV1Yang,
    VyattaInterfacesLoopbackV1Yang,
    VyattaIpv6RtradvV1Yang,
    VyattaServiceHttpsV1Yang,
    RiftVyattaCompositeYang
    )

IPV4_REGEX = "[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}" 
logger = logging.getLogger('rwcal.brocadecpe.drv')
logger.setLevel(logging.DEBUG)

class BrocadeVcpeDriver(object):
    """
      Driver for Brocade vCPE servicest
    """
    def __init__(self, log, host, username, password, mgmt_network = None, public_ip_pool=None):
        """
          Brocade vCPE Driver constructor
          Arguments:
            username (string)                   : Username for vCPE access
            password (string)                   : Password
            mgmt_network(string, optional)      : Management network name. Each VM created with this cloud-account will
                                                have a default interface into management network.

        """
        self.log = log
        self.username = username
        self.password = password
        self.host = host
        self.netconf_session = NetconfSession(host=host, username=username, password=password)
        try:
            self.netconf_session.connect()
        except ProxyConnectionError as err:
            self.log.warning("BrocadevCPEDriver: Connection to netconf server failed %s", str(err))
            raise
        self.log.debug("Connected to netconf server ")
        self.virtproxy = self.netconf_session.proxy(VyattaVirtualizationV1Yang)
        self.intfproxy = self.netconf_session.proxy(VyattaInterfacesVhostPbrV1Yang)
        self.dhcpproxy = self.netconf_session.proxy(VyattaServiceDhcpServerV1Yang)
        self.natproxy = self.netconf_session.proxy(VyattaServiceNatV1Yang)
        self.loproxy = self.netconf_session.proxy(VyattaInterfacesLoopbackV1Yang)
        self.dpproxy = self.netconf_session.proxy(RiftVyattaCompositeYang)
        self.httpproxy = self.netconf_session.proxy(VyattaServiceHttpsV1Yang)
        self.brocadevcpe_rest_session = BrocadeRestSession(host=host, port=80, username=username, password=password)
       
        self.log.info("Brocade CPE driver initialized")

    def get_http_service(self):
        xpath = "/service/https"
        http_service = self.httpproxy.get(xpath)
        self.log.debug("HTTP Service %s", http_service)
        return http_service

    def create_image(self, image_name):
        """
          Creates an image in vCPE
          Since launchpad does not have password access and Brocade does not support key based download we use the following workaround
             1. Scp image to /tmp directory in vCPE
             2. Use brocade download-image API to get image from localhost
             3. Delete image in /tmp directory in vCPE
          Arguments:
            image_name
          Returns:
            image id as image name

        """
        download_image = VyattaVirtualizationV1Yang.YangInput_VyattaVirtualizationV1_DownloadImage()
        download_image.remote.location="scp://localhost/tmp/" + image_name
        download_image.local.location = image_name
        download_image.authentication.username = self.username
        download_image.authentication.password = self.password

        dl_image_output = VyattaVirtualizationV1Yang.YangOutput_VyattaVirtualizationV1_DownloadImage()

        try:
            self.virtproxy.rpc(download_image, rpc_name="download-image", output_obj=dl_image_output)
        except ProxyRequestTimeout as e:
            self.log.warning("Exception raised %s ", str(e))


    def delete_image(self, image_id):
        """
          Deletes an image in vCPE
          Arguments:
            image_id

        """
        del_image = VyattaVirtualizationV1Yang.YangInput_VyattaVirtualizationV1_DeleteImage()
        del_image.image.location = image_id

        self.virtproxy.rpc(del_image)

    def get_image_list(self):
        """
        Returns list of dictionaries. Each dictionary contains attributes associated with image

        Arguments: None

        Returns: List of dictionaries.
        """
        images = []
        try:
           input_image_list = VyattaVirtualizationV1Yang.YangInput_VyattaVirtualizationV1_ListImages()
           output_image_list = VyattaVirtualizationV1Yang.YangOutput_VyattaVirtualizationV1_ListImages()

           self.virtproxy.rpc(input_image_list, rpc_name="list-images", output_obj=output_image_list)

        except Exception as e:
            self.log.error("BrocadevCPEDriver: List Image operation failed. Exception: %s" %(str(e)))
            raise
        return output_image_list.images

    def get_image(self, image_id):
        """
        Returns image

        Arguments: None

        Returns: List of dictionaries.
        """
        images = []
        try:
           input_image_list = VyattaVirtualizationV1Yang.YangInput_VyattaVirtualizationV1_ListImages()
           output_image_list = VyattaVirtualizationV1Yang.YangOutput_VyattaVirtualizationV1_ListImages()

           self.virtproxy.rpc(input_image_list, rpc_name="list-images", output_obj=output_image_list)

        except Exception as e:
            self.log.error("BrocadevCPEDriver: Get Image operation failed. Exception: %s" %(str(e)))
            raise

        for img_dict in output_image_list.images:
            if img_dict.image == image_id:
               return img_dict

    def copy_tmp_image(self, image_name):
        """
          Copy base VM image to a new image 
             1. Create image_name-rift-0.qcow2
          Arguments:
            image_name
          Returns:
            image id as image name

        """
        copy_image = VyattaVirtualizationV1Yang.YangInput_VyattaVirtualizationV1_CopyImage()
        cpimage = dict()
        src_location = dict()
        dest_location = dict()
        src_location['location'] = image_name
        dest_location['location'] = image_name + "-rift-0"
        cpimage['from_'] = src_location
        cpimage['to'] = dest_location
        copy_image.from_dict(cpimage)

        try:
            self.virtproxy.rpc(copy_image, rpc_name="copy-image")
        except ProxyRequestTimeout as e:
            self.log.warning("Exception raised %s ", str(e))
        return dest_location['location']


    def get_mac_addr(self):
        mac_req = VyattaVirtualizationV1Yang.YangInput_VyattaVirtualizationV1_GenerateMac()
        mac = VyattaVirtualizationV1Yang.YangOutput_VyattaVirtualizationV1_GenerateMac()

        try:
            self.virtproxy.rpc(mac_req, rpc_name="generate-mac", output_obj=mac)
        except ProxyRequestTimeout as e:
            self.log.warning("Exception raised %s ", str(e))

        return mac.address


    def create_vm(self, name, cpus, memory, disk_list, port_list=None):
        vm = VyattaVirtualizationV1Yang.YangData_VyattaVirtualizationV1_Virtualization_Guest()
        vm.name = name
        vm.uuid = str(uuid.uuid1())
        vm.cpus = cpus
        vm.memory = memory
        ctr = 0
        for disk_info in disk_list:
            disk = vm.devices.disk.add()
            disk.id = ctr
            disk.device_type = disk_info['type']
            disk.boot_order = disk_info['boot-order']
            disk.source.file = "/var/lib/libvirt/images/" + disk_info['image']
            ctr += 1


        port_state_list = []
        if port_list:
            # Add vhost interfaces to VM
            for port_info in port_list:
                port = vm.devices.network.add()
                port.name = port_info[0]
                port.mac_address = port_info[1]

                # Fill some needed info
                port_state = dict()
                port_state['name'] = port.name
                port_state['mac-addr'] = port_info[1]
                port_state_list.append(port_state)

        xpath = "/virtualization/guest"
        self.virtproxy.merge_config(xpath, vm, target='candidate')
        self.log.info("BrocadevCPEDriver: Create VM operation succeeded. ")
        return vm.name, port_state_list

    def kill_vcpe_qemu_pid(self, vdu_id):
        kill_str = r'''
#!/usr/bin/expect -f

set login {login}
set vcpe_addr {vcpe_addr}
set vdu_id {vdu_id}
set pw {pw}

spawn ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $login@$vcpe_addr
set spid $spawn_id
set timeout 60
set success 0

expect -i $spid \
                    "*?assword:"      {{
                                  exp_send -i $spid "$pw\r"
                                  if {{ $success == 0 }} {{
                                          incr success -1
                                          exp_continue
                                  }}
                  }} ":~$ "  {{
                          set success 1
                  }} "yes/no"      {{
                          exp_send -i $spid "yes\r"
                          exp_continue
                  }} timeout       {{
                          set success -1
                  }}


# Set some variables
set success 0
exp_send -i $spid "sudo su \r"
expect -i $spid \
                      "*?assword for $login: "      {{
                                    exp_send -i $spid "$pw\r"
                                    if {{ $success == 0 }} {{
                                            incr success -1
                                            exp_continue
                                    }}
                    }} "$login# "  {{
                            set success 1
                    }} "yes/no"     {{
                            exp_send -i $spid "yes\r"
                            exp_continue
                    }} timeout      {{
                            set success -1
                    }}
exp_send -i $spid "virsh list | grep $vdu_id\r"
expect -re {{(\s+)(\d+)(\s+)(\S+)(\s+)}}
set vdu_domain_num $expect_out(2,string)
puts "QEMU VDU domain name $vdu_domain_num"
expect "$login# "
exp_send -i $spid "virsh destroy $vdu_domain_num\r"
expect "$login# "
exp_send -i $spid "virsh list\r"
expect "$login# "
        '''
        kill_str = kill_str.format(login=self.username, vcpe_addr=self.host, vdu_id=vdu_id, pw=self.password)
        try:
            # Now write this string into file
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as fp:
                fp.write(kill_str)

            script_cmd = 'expect {}'.format(fp.name)
            self.log.debug("VM destroy script command (%s)", script_cmd)
            response = subprocess.check_output(script_cmd, shell=True).decode('utf-8')
            self.log.debug("VM destroy output (%s)", response)
        except Exception as e:
            self.log.error("Destroy VM script failed : %s", str(e))
        finally:
            fp.close()

    def delete_vm(self, name):
        vm = VyattaVirtualizationV1Yang.YangData_VyattaVirtualizationV1_Virtualization_Guest()
        vm.name = name

        self.kill_vcpe_qemu_pid(name)
        xpath = "/virtualization/guest[name='{}']".format(name)
        self.virtproxy.delete_config(xpath, target='candidate')
        #self.brocadevcpe_rest_session.delete_vm_info(name)
        self.log.info("BrocadevCPEDriver: Delete VM operation succeeded. ")
        return vm.name

    def get_vm(self, name):
        # Not working with specific xpath
        xpath = "/virtualization/guest"
        try:
            vmlist = self.virtproxy.get(xpath, list_obj=True)
        except ProxyRequestError as err:
            self.log.warning("BrocadevCPEDriver: Get VM failed, Error %s", str(err))
            return None, None
        assert(vmlist.guest)
        for vmconfig in vmlist.guest:
            if vmconfig.name == name:
                self.log.debug("BrocadevCPEDriver: Get VM operation succeeded, name %s", vmconfig.name)
                break
        if vmconfig is None:
            return None, None
        # Not working with specific xpath
        xpath = "/virtualization/guest-state/guest"
        try:
            vmlist = self.virtproxy.get(xpath, list_obj=True)
        except ProxyRequestError as err:
            self.log.warning("BrocadevCPEDriver: Get VM-state failed, Error %s", str(err))
        for vmstate in vmlist.guest:
            if vmstate.name == name:
                self.log.debug("BrocadevCPEDriver: Get VM state operation succeeded, name %s", vmstate.name)
                return vmconfig, vmstate

    def get_vm_list(self):
        xpath = "/virtualization/guest"
        try:
            vmcfglist = self.virtproxy.get(xpath, list_obj=True)
        except ProxyRequestError as err:
            self.log.warning("BrocadevCPEDriver: Get VM list failed, Error %s", str(err))
            return None, None
        xpath = "/virtualization/guest-state/guest"
        try:
            vmstatelist = self.virtproxy.get(xpath, list_obj=True)
        except ProxyRequestError as err:
            self.log.warning("BrocadevCPEDriver: Get VM list failed, Error %s", str(err))
            return None, None
        return vmcfglist, vmstatelist

    def nfvi_metrics(self, name):
        xpath = "/virtualization/guest-state/guest"

        try:
            guests = self.virtproxy.get(xpath, list_obj=True)
        except ProxyRequestError as err:
            logger.warning("BrocadevCPEDriver: Get Guest list failed, Error %s", str(err))
            return None

        for guest in guests.guest:
            if guest.name == name:
                return guest

    def get_vhost_interfaces(self):
        xpath = "/vyatta-if-v1:interfaces/vyatta-interfaces-vhost-v1:vhost"
        vhostlist = self.intfproxy.get(xpath, list_obj=True)
        return vhostlist

    def get_vhost_interface(self, name):
        xpath = "/vyatta-if-v1:interfaces/vyatta-interfaces-vhost-v1:vhost"
        try:
            vhostlist = self.intfproxy.get(xpath, list_obj=True)
        except ProxyRequestError as err:
            self.log.debug("BrocadevCPEDriver: Get VHost interface failed, Error %s", str(err))
            return

        if vhostlist is None:
            return None
        if vhostlist.vhost is None:
            return None
        for vhost in vhostlist.vhost:
            if vhost.name == name:
                 return vhost

    def get_operational_port_ip(self, mac_addr, dhcp_server):
        self.log.debug("BrocadevCPEDriver: Get IP info from DHCP server %s", dhcp_server)
        if dhcp_server == self.host:
            response = self.brocadevcpe_rest_session.request_dhcp_server_info()
        else:
            response = self.brocadevrouter_rest_session.request_dhcp_server_info()
        self.log.debug("BrocadevCPEDriver: DHCP lease response %s", response)
        
        pattern = "({})({})({})".format(IPV4_REGEX,"\s+",mac_addr)
        match = re.search(pattern, response)
        if match:
            self.log.debug("Found match for MAC address %s", mac_addr)
            mgmt_port_ip = match.group(1)
            return mgmt_port_ip
        else:
            self.log.debug("No match for MAC address %s", mac_addr)

    def create_vhost_intf(self, vhost_port, metadata=None, ip_addr=None):
        vhost = VyattaInterfacesVhostBridgeV1Yang.YangData_VyattaInterfacesV1_Interfaces_Vhost()
        vhost.name = vhost_port
        if ip_addr is not None:
           vhost.address.append(ip_addr)
        if metadata is not None:
           vhost.description = metadata

        xpath = "/interfaces/vhost"
        self.intfproxy.merge_config(xpath, vhost, target='candidate')
        self.log.info("BrocadevCPEDriver: Create vhost operation succeeded for %s ", vhost_port)
        return vhost.name

    def delete_vhost_intf(self, vhost_port):
        self.log.info("BrocadevCPEDriver: Delete vhost operation for %s", vhost_port)

        xpath = "/vyatta-interfaces-v1:interfaces/vyatta-interfaces-vhost-v1:vhost[name='{}']".format(vhost_port)
        #self.intfproxy.delete_config(xpath, target='candidate')
        self.brocadevcpe_rest_session.delete_vhost_intf(vhost_port)
        self.log.info("BrocadevCPEDriver: Delete vhost operation succeeded for %s", vhost_port)

    def add_vhost_to_bridge(self, vhost_port, bridge):
        vhost = VyattaInterfacesVhostBridgeV1Yang.YangData_VyattaInterfacesV1_Interfaces_Vhost()
        vhost.name = vhost_port
        vhost.bridge_group.bridge = bridge

        xpath = "/interfaces/vhost"
        self.intfproxy.merge_config(xpath, vhost, target='candidate')
        self.log.info("BrocadevCPEDriver: Add vhost to bridge operation succeeded for %s", vhost_port)
        return vhost.name

    def delete_vhost_intf_from_bridge(self, vhost_port, rbridge):
        vhost = VyattaInterfacesVhostBridgeV1Yang.YangData_VyattaInterfacesV1_Interfaces_Vhost()
        vhost.name = vhost_port

        xpath = "/interfaces/vhost[name='{}']".format(vhost_port)
        self.intfproxy.delete_config(xpath, target='candidate')
        self.log.info("BrocadevCPEDriver: Delete vhost from bridge operation succeeded for %s ", vhost_port)
        return vhost.name

    def get_dp_interface(self, name):
        xpath = "/interfaces/dataplane"
        dplist = self.dpproxy.get(xpath, list_obj=True)
        self.log.debug("Dataplane list %s", dplist)
        if dplist is None or dplist.dataplane is None:
            return None
        for dp in dplist.dataplane:
            if dp.tagnode == name:
                return dp

    def get_lo_interfaces(self):
        xpath = "/interfaces/loopback"
        lolist = self.loproxy.get(xpath, list_obj=True)
        self.log.debug("Loopback list %s", lolist)
        if lolist is None or lolist.loopback is None:
            return None
        for lo in lolist.loopback:
            if 'description' not in lo:
                lolist.loopback.remove(lo)
                continue
            if "RIFTLO" not in lo.description:
                lolist.loopback.remove(lo)
        return lolist

    def get_lo_interface(self, name):
        xpath = "/interfaces/loopback"
        try:
            lolist = self.loproxy.get(xpath, list_obj=True)
        except ProxyRequestError as err:
            self.log.debug("BrocadevCPEDriver: Get loopback interface failed, Error %s", str(err))
            return

        if lolist is None or lolist.loopback is None:
            return None
        for lo in lolist.loopback:
            if lo.tagnode == name:
                 return lo

    def create_lo_interface(self, loname, vlname, subnet):
        intf = VyattaInterfacesLoopbackV1Yang.YangData_VyattaInterfacesV1_Interfaces_Loopback()
        intf.tagnode = loname
        intf.description = "RIFTLO" + " " + vlname + " " + subnet

        xpath = "/interfaces/loopback"
        self.loproxy.merge_config(xpath, intf, target='candidate')
        self.log.info("BrocadevCPEDriver: Add loopback intf for %s", vlname)
        return intf.tagnode

    def delete_lo_intf(self, name):
        self.log.info("BrocadevCPEDriver: Delete loopback operation for %s", name)

        xpath = "/vyatta-interfaces-v1:interfaces/vyatta-interfaces-loopback-v1:vhost[name='{}']".format(name)
        #self.loproxy.delete_config(xpath, target='candidate')
        self.brocadevcpe_rest_session.delete_lo_intf(name)
        self.log.info("BrocadevCPEDriver: Delete loopback operation succeeded for %s", name)

    def create_l3_network(self, name, subnet):
        self.log.info("BrocadevCPEDriver: Creating a new L3 network %s with subnet %s ", name, subnet)
        server = VyattaServiceDhcpServerV1Yang.YangData_VyattaServicesV1_Service_DhcpServer()
        nw = server.shared_network_name.add()
        nw.tagnode = name
        nw.description = "RIFTVL" + " " + name + " " + subnet
        # Atleast one subnet is needed to configure this
        s1 = nw.subnet.add()
        parent_ipnw = ipaddress.IPv4Network(subnet)
        child_subs = list(parent_ipnw.subnets(new_prefix=24))
        # First child subnet should be available
        s1.tagnode = str(child_subs[0])
        range1 = s1.start.add()
        hostlist = list(child_subs[0].hosts())
        range1.tagnode = str(hostlist[0])
        range1.stop = str(hostlist[1])
        xpath = "/service"
        self.dhcpproxy.merge_config(xpath, server, target='candidate')
        self.log.info("BrocadevCPEDriver: Create L3 network operation succeeded. ")
        return name

    def get_l3_network(self, name):
        self.log.info("BrocadevCPEDriver: Getting L3 network %s ", name)
        server = VyattaServiceDhcpServerV1Yang.YangData_VyattaServicesV1_Service_DhcpServer()
        #xpath = "/vyatta-services-v1:service/dhcp-server/shared-network-name"
        xpath = "/vyatta-services-v1:service/dhcp-server"
        server = self.dhcpproxy.get(xpath, list_obj=False)
        if server is None:
            return None
        if server.shared_network_name is None:
            return None
        for nw in server.shared_network_name:
            if nw.tagnode == name:
                 self.log.debug("BrocadevCPEDriver: Done getting L3 network %s ", name)
                 return nw
        self.log.info("BrocadevCPEDriver: Done getting L3 network %s ", name)

    def get_l3_network_list(self):
        self.log.info("BrocadevCPEDriver: Getting L3 network list ")
        server = VyattaServiceDhcpServerV1Yang.YangData_VyattaServicesV1_Service_DhcpServer()
        nw_list = []
        #xpath = "/vyatta-services-v1:service/dhcp-server/shared-network-name"
        xpath = "/vyatta-services-v1:service/dhcp-server"
        server = self.dhcpproxy.get(xpath, list_obj=False)
        if server is None:
            return nw_list
        if server.shared_network_name is None:
            return nw_list
        self.log.info("BrocadevCPEDriver: Done getting L3 network list ")
        for nw in server.shared_network_name:
            if "RIFTVL" not in nw.description:
                 server.shared_network_name.remove(nw)
        return server.shared_network_name

    def delete_l3_network(self, name):
        self.log.info("BrocadevCPEDriver: Deleting a new L3 network %s ", name)
        xpath = "/vyatta-services-v1:service/dhcp-server/shared-network-name[tagnode='{}']".format(name)
        #self.dhcpproxy.delete_config(xpath, target='candidate')
        self.brocadevcpe_rest_session.delete_vlink(name)
        self.log.info("BrocadevCPEDriver: Delete L3 network operation succeeded. ")
        return name

    def merge_dhcp_server_config(self, server):
        self.log.info("BrocadevCPEDriver: Merging DHCP config ")
        xpath = "/vyatta-services-v1:service/dhcp-server"
        self.dhcpproxy.merge_config(xpath, server, target='candidate')
        self.log.info("BrocadevCPEDriver: Merging DHCP succeeded. ")

    def get_dhcp_server_config(self):
        self.log.info("BrocadevCPEDriver: Getting DHCP config ")
        xpath = "/vyatta-services-v1:service/dhcp-server"
        server = self.dhcpproxy.get(xpath)
        self.log.info("BrocadevCPEDriver: Getting DHCP succeeded. ")
        return server

    def delete_dhcp_subnet(self, shared_nw, subnet):
        self.log.info("BrocadevCPEDriver: Deleting DHCP subnet %s for VM", subnet)
        xpath = "/vyatta-services-v1:service/dhcp-server/shared-network-name[tagnode='{}']/subnet[tagnode='{}']".format(shared_nw, subnet)
        self.log.debug("BrocadevCPEDriver: xpath %s", xpath)
        self.dhcpproxy.delete_config(xpath, target='candidate')
        self.log.info("BrocadevCPEDriver: Deleting DHCP succeeded for VM ")

    def delete_dhcp_listener(self, interface):
        self.log.info("BrocadevCPEDriver: Deleting DHCP listener for VM")
        xpath = "/vyatta-services-v1:service/dhcp-server/listento/interface[. = '{}']".format(interface)
        self.log.debug("BrocadevCPEDriver: xpath %s", xpath)
        #self.dhcpproxy.delete_config(xpath, target='candidate')
        self.brocadevcpe_rest_session.delete_dhcp_listener(interface)

    def _get_next_rule(self, nat, public_pool):
        wan_sn = ipaddress.IPv4Network(public_pool)
        host_gen = wan_sn.hosts()
        public_ip = None
        if nat is None or nat.source is None:
           ruletag = 10
           public_ip = host_gen.__next__()
           return ruletag, str(public_ip)

        iplist = [ rule.translation.address for rule in nat.source.rule ]
        try:
            for host in host_gen:
               if str(host) in iplist:
                  continue
               public_ip = host
               break
        except StopIteration:
            pass


        rulelist = [ rule.tagnode for rule in nat.source.rule ]
        if rulelist == []:
           ruletag = 10
        else:
           ruletag = max(rulelist) + 10

        return ruletag, str(public_ip)

    def assign_floating_ip(self, public_ip_pool, mgmt_ip, wan_interface):
        xpath = "/service/nat"
        nat = self.natproxy.get(xpath, list_obj=False)
        self.log.debug("NAT rules : %s", nat)

        ruletag, public_ip = self._get_next_rule(nat, public_ip_pool)
        self.log.debug("Source rule to be set: ruletag %s, public_ip %s, wan interface %s", ruletag, public_ip, wan_interface)

        new_src_rule = VyattaServiceNatV1Yang.YangData_VyattaServicesV1_Service_Nat_Source_Rule()
        # set service nat source rule 10 outbound-interface 'dp0s2f0'
        # set service nat source rule 10 source address '192.168.1.6'
        # set service nat source rule 10 translation address '10.66.26.1'
        new_src_rule.description = "RIFT NAT Rule"
        new_src_rule.tagnode = ruletag
        new_src_rule.source.address = mgmt_ip
        new_src_rule.translation.address = public_ip
        new_src_rule.outbound_interface = wan_interface
        xpath = "/service/nat/source"
        self.natproxy.merge_config(xpath, new_src_rule, target='candidate')

        new_dst_rule = VyattaServiceNatV1Yang.YangData_VyattaServicesV1_Service_Nat_Destination_Rule()
        # set service nat destination rule 10 destination address '10.66.26.1'
        # set service nat destination rule 10 inbound-interface 'dp0s2f0'
        # set service nat destination rule 10 translation address '192.168.1.6'
        new_dst_rule.description = "RIFT NAT Rule"
        new_dst_rule.tagnode = ruletag
        new_dst_rule.translation.address = mgmt_ip
        new_dst_rule.destination.address = public_ip
        new_dst_rule.inbound_interface = wan_interface
        xpath = "/service/nat/destination"
        self.natproxy.merge_config(xpath, new_dst_rule, target='candidate')
        return public_ip

    def get_floating_ip_info(self, mgmt_ip):
        self.log.debug("Getting floating ip for %s", mgmt_ip)
        xpath = "/service/nat"
        nat = self.natproxy.get(xpath, list_obj=False)
        if nat is None or nat.source is None:
            return None, None
        for rule in nat.source.rule:
            if rule.source.address == mgmt_ip:
                self.log.debug("Returning floating ip %s for %s", rule.translation.address, mgmt_ip)
                return rule.tagnode, rule.translation.address
        return None, None

    def delete_floating_ip(self, mgmt_ip):
        self.log.debug("Deleting floating ip for : %s", mgmt_ip)
        xpath = "/service/nat"
        nat = self.natproxy.get(xpath, list_obj=False)
        self.log.debug("Source NAT rules : %s", nat)

        ruletag, public_ip = self.get_floating_ip_info(mgmt_ip)
        if ruletag is not None:
           xpath = "/vyatta-services-v1:service/nat/source/rule[tagnode={}]".format(ruletag)
           self.natproxy.delete_config(xpath, target='candidate')
           xpath = "/vyatta-services-v1:service/nat/destination/rule[tagnode={}]".format(ruletag)
           self.natproxy.delete_config(xpath, target='candidate')
        self.log.debug("DeletED floating ip for : %s", mgmt_ip)

    def delete_dhcp_lease(self, mac_addr):
        self.log.info("BrocadevCPEDriver: Delete mac operation for %s", mac_addr)
        self.brocadevcpe_rest_session.reset_dhcp_lease(mac_addr)
        self.log.info("BrocadevCPEDriver: Delete mac operation succeeded for %s", mac_addr)

    def get_dns_server_info(self):
        self.log.debug("BrocadevCPEDriver: Get DNS server info")
        # Get DNS nameserver info
        dns_info = self.brocadevcpe_rest_session.request_dns_nameserver_info()
        pattern = "({})(\s+)available via 'system'".format(IPV4_REGEX)
        match = re.search(pattern, dns_info)
        if match:
            self.log.debug("Found match for name server")
            dns_server = match.group(1)
            return dns_server


