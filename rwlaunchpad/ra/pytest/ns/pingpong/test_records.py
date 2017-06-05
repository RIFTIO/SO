
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

import collections
import socket
import subprocess
import time
import json

import pytest

import gi
import re
import os
from scapy.all import rdpcap, UDP, TCP, IP
gi.require_version('RwNsrYang', '1.0')
from gi.repository import (
        NsdYang,
        RwBaseYang,
        RwConmanYang,
        RwNsrYang,
        RwNsdYang,
        RwVcsYang,
        RwVlrYang,
        RwVnfdYang,
        RwVnfrYang,
        VlrYang,
        VnfrYang,
        NsrYang,
        )
import rift.auto.mano
import rift.auto.session
import rift.mano.examples.ping_pong_nsd as ping_pong
from rift.auto.ssh import SshSession


@pytest.fixture(scope='module')
def proxy(request, mgmt_session):
    return mgmt_session.proxy

@pytest.fixture(scope='session')
def updated_ping_pong_records(ping_pong_factory):
    '''Fixture returns a newly created set of ping and pong descriptors
    for the create_update tests
    '''
    return ping_pong_factory.generate_descriptors()

def yield_vnfd_vnfr_pairs(proxy, nsr=None):
    """
    Yields tuples of vnfd & vnfr entries.

    Args:
        proxy (callable): Launchpad proxy
        nsr (optional): If specified, only the vnfr & vnfd records of the NSR
                are returned

    Yields:
        Tuple: VNFD and its corresponding VNFR entry
    """
    def get_vnfd(vnfd_id):
        xpath = "/vnfd-catalog/vnfd[id='{}']".format(vnfd_id)
        return proxy(RwVnfdYang).get(xpath)

    vnfr = "/vnfr-catalog/vnfr"
    vnfrs = proxy(RwVnfrYang).get(vnfr, list_obj=True)
    for vnfr in vnfrs.vnfr:

        if nsr:
            const_vnfr_ids = [const_vnfr.vnfr_id for const_vnfr in nsr.constituent_vnfr_ref]
            if vnfr.id not in const_vnfr_ids:
                continue

        vnfd = get_vnfd(vnfr.vnfd.id)
        yield vnfd, vnfr


def yield_nsd_nsr_pairs(proxy):
    """Yields tuples of NSD & NSR

    Args:
        proxy (callable): Launchpad proxy

    Yields:
        Tuple: NSD and its corresponding NSR record
    """

    for nsr_cfg, nsr in yield_nsrc_nsro_pairs(proxy):
        nsd_path = "/nsd-catalog/nsd[id='{}']".format(
                nsr_cfg.nsd.id)
        nsd = proxy(RwNsdYang).get_config(nsd_path)

        yield nsd, nsr

def yield_nsrc_nsro_pairs(proxy):
    """Yields tuples of NSR Config & NSR Opdata pairs

    Args:
        proxy (callable): Launchpad proxy

    Yields:
        Tuple: NSR config and its corresponding NSR op record
    """
    nsr = "/ns-instance-opdata/nsr"
    nsrs = proxy(RwNsrYang).get(nsr, list_obj=True)
    for nsr in nsrs.nsr:
        nsr_cfg_path = "/ns-instance-config/nsr[id='{}']".format(
                nsr.ns_instance_config_ref)
        nsr_cfg = proxy(RwNsrYang).get_config(nsr_cfg_path)

        yield nsr_cfg, nsr


def assert_records(proxy):
    """Verifies if the NSR & VNFR records are created
    """
    ns_tuple = list(yield_nsd_nsr_pairs(proxy))
    assert len(ns_tuple) == 1

    vnf_tuple = list(yield_vnfd_vnfr_pairs(proxy))
    assert len(vnf_tuple) == 2


@pytest.mark.depends('nsr')
@pytest.mark.setup('records')
@pytest.mark.usefixtures('recover_tasklet')
@pytest.mark.incremental
class TestRecordsData(object):
    def is_valid_ip(self, address):
        """Verifies if it is a valid IP and if its accessible

        Args:
            address (str): IP address

        Returns:
            boolean
        """
        try:
            socket.inet_pton(socket.AF_INET, address)
            return True
        except socket.error:
            try:
                socket.inet_pton(socket.AF_INET6, address)
                return True
            except socket.error:
                return False

    def is_ipv6(self, address):
        """Returns True if address is of type 'IPv6', else False."""
        try:
            socket.inet_pton(socket.AF_INET6, address)
            return True
        except socket.error:
            return False

    @pytest.mark.feature("recovery")
    def test_tasklets_recovery(self, mgmt_session, proxy, recover_tasklet):
        """Test the recovery feature of tasklets

        Triggers the vcrash and waits till the system is up
        """
        RECOVERY = "RESTART"

        def vcrash(comp):
            rpc_ip = RwVcsYang.VCrashInput.from_dict({"instance_name": comp})
            proxy(RwVcsYang).rpc(rpc_ip)

        tasklet_name = r'^{}-.*'.format(recover_tasklet)

        vcs_info = proxy(RwBaseYang).get("/vcs/info/components")
        for comp in vcs_info.component_info:
            if comp.recovery_action == RECOVERY and \
               re.match(tasklet_name, comp.instance_name):
                vcrash(comp.instance_name)

        time.sleep(60)

        rift.vcs.vcs.wait_until_system_started(mgmt_session)
        # NSM tasklet takes a couple of seconds to set up the python structure
        # so sleep and then continue with the tests.
        time.sleep(60)

    def test_records_present(self, proxy):
        assert_records(proxy)

    def test_nsd_ref_count(self, proxy):
        """
        Asserts
        1. The ref count data of the NSR with the actual number of NSRs
        """
        nsd_ref_xpath = "/ns-instance-opdata/nsd-ref-count"
        nsd_refs = proxy(RwNsrYang).get(nsd_ref_xpath, list_obj=True)

        expected_ref_count = collections.defaultdict(int)
        for nsd_ref in nsd_refs.nsd_ref_count:
            expected_ref_count[nsd_ref.nsd_id_ref] = nsd_ref.instance_ref_count

        actual_ref_count = collections.defaultdict(int)
        for nsd, nsr in yield_nsd_nsr_pairs(proxy):
            actual_ref_count[nsd.id] += 1

        assert expected_ref_count == actual_ref_count

    def test_vnfd_ref_count(self, proxy):
        """
        Asserts
        1. The ref count data of the VNFR with the actual number of VNFRs
        """
        vnfd_ref_xpath = "/vnfr-catalog/vnfd-ref-count"
        vnfd_refs = proxy(RwVnfrYang).get(vnfd_ref_xpath, list_obj=True)

        expected_ref_count = collections.defaultdict(int)
        for vnfd_ref in vnfd_refs.vnfd_ref_count:
            expected_ref_count[vnfd_ref.vnfd_id_ref] = vnfd_ref.instance_ref_count

        actual_ref_count = collections.defaultdict(int)
        for vnfd, vnfr in yield_vnfd_vnfr_pairs(proxy):
            actual_ref_count[vnfd.id] += 1

        assert expected_ref_count == actual_ref_count

    def test_nsr_nsd_records(self, proxy):
        """
        Verifies the correctness of the NSR record using its NSD counter-part

        Asserts:
        1. The count of vnfd and vnfr records
        2. Count of connection point descriptor and records
        """
        for nsd, nsr in yield_nsd_nsr_pairs(proxy):
            assert nsd.name == nsr.nsd_name_ref
            assert len(nsd.constituent_vnfd) == len(nsr.constituent_vnfr_ref)

            assert len(nsd.vld) == len(nsr.vlr)
            for vnfd_conn_pts, vnfr_conn_pts in zip(nsd.vld, nsr.vlr):
                assert len(vnfd_conn_pts.vnfd_connection_point_ref) == \
                       len(vnfr_conn_pts.vnfr_connection_point_ref)

    def test_vdu_record_params(self, proxy):
        """
        Asserts:
        1. If a valid floating IP has been assigned to the VM
        2. Count of VDUD and the VDUR
        3. Check if the VM flavor has been copied over the VDUR
        """
        for vnfd, vnfr in yield_vnfd_vnfr_pairs(proxy):
            assert vnfd.mgmt_interface.port == vnfr.mgmt_interface.port
            assert len(vnfd.vdu) == len(vnfr.vdur)

            for vdud, vdur in zip(vnfd.vdu, vnfr.vdur):
                assert vdud.vm_flavor == vdur.vm_flavor
                assert self.is_valid_ip(vdur.management_ip) is True
                assert vdud.external_interface[0].vnfd_connection_point_ref == \
                    vdur.external_interface[0].vnfd_connection_point_ref

    def test_external_vl(self, proxy):
        """
        Asserts:
        1. Valid IP for external connection point
        2. A valid external network fabric
        3. Connection point names are copied over
        4. Count of VLD and VLR
        5. Checks for a valid subnet ?
        6. Checks for the operational status to be running?
        """
        for vnfd, vnfr in yield_vnfd_vnfr_pairs(proxy):
            cp_des, cp_rec = vnfd.connection_point, vnfr.connection_point

            assert len(cp_des) == len(cp_rec)
            assert cp_des[0].name == cp_rec[0].name
            assert self.is_valid_ip(cp_rec[0].ip_address) is True

            xpath = "/vlr-catalog/vlr[id='{}']".format(cp_rec[0].vlr_ref)
            vlr = proxy(RwVlrYang).get(xpath)

            assert len(vlr.network_id) > 0
            assert len(vlr.assigned_subnet) > 0
            ip, _ = vlr.assigned_subnet.split("/")
            assert self.is_valid_ip(ip) is True
            assert vlr.operational_status == "running"


    def test_nsr_record(self, proxy):
        """
        Currently we only test for the components of NSR tests. Ignoring the
        operational-events records

        Asserts:
        1. The constituent components.
        2. Admin status of the corresponding NSD record.
        """
        for nsr_cfg, nsr in yield_nsrc_nsro_pairs(proxy):
            # 1 n/w and 2 connection points
            assert len(nsr.vlr) == 1
            assert len(nsr.vlr[0].vnfr_connection_point_ref) == 2

            assert len(nsr.constituent_vnfr_ref) == 2
            assert nsr_cfg.admin_status == 'ENABLED'

    def test_wait_for_ns_configured(self, proxy):
        nsr_opdata = proxy(RwNsrYang).get('/ns-instance-opdata')
        nsrs = nsr_opdata.nsr

        assert len(nsrs) == 1
        current_nsr = nsrs[0]

        xpath = "/ns-instance-opdata/nsr[ns-instance-config-ref='{}']/config-status".format(current_nsr.ns_instance_config_ref)
        proxy(RwNsrYang).wait_for(xpath, "configured", timeout=400)

    def test_wait_for_pingpong_vnf_configured(self, proxy):
        for vnfd, vnfr in yield_vnfd_vnfr_pairs(proxy):
            xpath = "/vnfr-catalog/vnfr[id='{}']/config-status".format(vnfr.id)
            proxy(VnfrYang).wait_for(xpath, "configured", timeout=400)
    
    def test_vnf_monitoring_params(self, proxy):
        """
        Asserts:
        1. The value counter ticks?
        2. If the meta fields are copied over
        """
        def mon_param_record(vnfr_id, mon_param_id):
             return '/vnfr-catalog/vnfr[id="{}"]/monitoring-param[id="{}"]'.format(
                    vnfr_id, mon_param_id)

        for vnfd, vnfr in yield_vnfd_vnfr_pairs(proxy):
            for mon_des in (vnfd.monitoring_param):
                mon_rec = mon_param_record(vnfr.id, mon_des.id)
                mon_rec = proxy(VnfrYang).get(mon_rec)

                # Meta data check
                fields = mon_des.as_dict().keys()
                for field in fields:
                    assert getattr(mon_des, field) == getattr(mon_rec, field)
                # Tick check
                #assert mon_rec.value_integer > 0

    def test_ns_monitoring_params(self, logger, proxy):
        """
        Asserts:
            1. monitoring-param match in nsd and ns-opdata
            2. The value counter ticks?
        """
        mon_param_path = '/ns-instance-opdata/nsr[ns-instance-config-ref="{}"]/monitoring-param[id="{}"]'
        def fetch_monparam_value(nsr_ref, mon_param_id):
            """Returns the monitoring parameter value"""
            mon_param = proxy(NsrYang).get(mon_param_path.format(nsr_ref, mon_param_id))
            return mon_param.value_integer

        def check_monparam_value(nsr_ref, mon_param_id):
            """Check if monitoring-param values are getting updated"""
            recent_mon_param_value = fetch_monparam_value(nsr_ref, mon_param_id)

            # Monitor the values over a period of 60 secs. Fail the test if there is no update in mon-param value.
            s_time = time.time()
            while (time.time() - s_time) < 60:
                if fetch_monparam_value(nsr_ref, mon_param_id) > recent_mon_param_value:
                    return
                time.sleep(5)
            assert False, 'mon-param values are not getting updated. Last value was {}'.format(recent_mon_param_value)

        for nsd, nsr in yield_nsd_nsr_pairs(proxy):
            assert len(nsd.monitoring_param) == len(nsr.monitoring_param)
            for mon_param in nsr.monitoring_param:
                logger.info('Verifying monitoring-param: {}'.format(mon_param.as_dict()))
                check_monparam_value(nsr.ns_instance_config_ref, mon_param.id)

    def test_cm_nsr(self, proxy):
        """
        Asserts:
            1. The ID of the NSR in cm-state
            2. Name of the cm-nsr
            3. The vnfr component's count
            4. State of the cm-nsr
        """
        for nsd, nsr in yield_nsd_nsr_pairs(proxy):
            con_nsr_xpath = "/cm-state/cm-nsr[id='{}']".format(nsr.ns_instance_config_ref)
            con_data = proxy(RwConmanYang).get(con_nsr_xpath)

            assert con_data.name == rift.auto.mano.resource_name(nsd.name)
            assert len(con_data.cm_vnfr) == 2

            state_path = con_nsr_xpath + "/state"
            proxy(RwConmanYang).wait_for(state_path, 'ready', timeout=120)

    def test_cm_vnfr(self, proxy):
        """
        Asserts:
            1. The ID of Vnfr in cm-state
            2. Name of the vnfr
            3. State of the VNFR
            4. Checks for a reachable IP in mgmt_interface
            5. Basic checks for connection point and cfg_location.
        """
        def is_reachable(ip, timeout=10):
            rc = subprocess.call(["ping", "-c1", "-w", str(timeout), ip])
            if rc == 0:
                return True
            return False

        nsr_cfg, _ = list(yield_nsrc_nsro_pairs(proxy))[0]
        con_nsr_xpath = "/cm-state/cm-nsr[id='{}']".format(nsr_cfg.id)

        for _, vnfr in yield_vnfd_vnfr_pairs(proxy):
            con_vnfr_path = con_nsr_xpath + "/cm-vnfr[id='{}']".format(vnfr.id)
            con_data = proxy(RwConmanYang).get(con_vnfr_path)

            assert con_data is not None

            state_path = con_vnfr_path + "/state"
            proxy(RwConmanYang).wait_for(state_path, 'ready', timeout=120)

            con_data = proxy(RwConmanYang).get(con_vnfr_path)
            assert is_reachable(con_data.mgmt_interface.ip_address) is True

            assert len(con_data.connection_point) == 1
            connection_point = con_data.connection_point[0]
            assert connection_point.name == vnfr.connection_point[0].name
            assert connection_point.ip_address == vnfr.connection_point[0].ip_address

            assert con_data.cfg_location is not None

    @pytest.mark.skipif(
        not (pytest.config.getoption("--static-ip") or pytest.config.getoption("--update-vnfd-instantiate")),
        reason="need --static-ip or --update-vnfd-instantiate option to run")
    def test_static_ip(self, proxy, logger, vim_clients, cloud_account_name):
        """
        Asserts:
            1. static-ip match in vnfd and vnfr
            2. static-ip match in cm-state
            3. Get the IP of openstack VM. Match the static-ip
            4. Check if the VMs are reachable from each other (Skip if type of static ip addresses is IPv6)
        """
        nsr_cfg, _ = list(yield_nsrc_nsro_pairs(proxy))[0]
        con_nsr_xpath = "/cm-state/cm-nsr[id='{}']".format(nsr_cfg.id)
        
        ips = {}
        static_ip_vnfd = False
        for vnfd, vnfr in yield_vnfd_vnfr_pairs(proxy):
            if vnfd.connection_point[0].static_ip_address:
                static_ip_vnfd = True
                assert vnfd.connection_point[0].static_ip_address == vnfr.connection_point[0].ip_address
                if 'ping' in vnfd.name:
                    ips['vm_mgmt_ip'] = vnfr.vdur[0].vm_management_ip
                else:
                    ips['static_ip'] = vnfd.connection_point[0].static_ip_address

                con_vnfr_path = con_nsr_xpath + "/cm-vnfr[id='{}']".format(vnfr.id)
                con_data = proxy(RwConmanYang).get(con_vnfr_path)

                assert con_data is not None
                assert con_data.connection_point[0].ip_address == vnfd.connection_point[0].static_ip_address

                xpath = "/vlr-catalog/vlr[id='{}']".format(vnfr.connection_point[0].vlr_ref)
                vlr = proxy(RwVlrYang).get(xpath)
                
                vim_client = vim_clients[cloud_account_name]
                vm_property = vim_client.nova_server_get(vnfr.vdur[0].vim_id)
                logger.info('VM properties for {}: {}'.format(vnfd.name, vm_property))

                addr_prop_list = vm_property['addresses'][vlr.name]
                logger.info('addresses attribute: {}'.format(addr_prop_list))

                addr_prop = [addr_prop for addr_prop in addr_prop_list if addr_prop['addr'] == vnfr.connection_point[0].ip_address]
                assert addr_prop

        assert static_ip_vnfd   # if False, then none of the VNF descriptors' connections points are carrying static-ip-address field.

        # Check if the VMs are reachable from each other
        username, password = ['fedora'] * 2
        ssh_session = SshSession(ips['vm_mgmt_ip'])
        assert ssh_session
        assert ssh_session.connect(username=username, password=password)
        if not self.is_ipv6(ips['static_ip']):
            assert ssh_session.run_command('ping -c 5 {}'.format(ips['static_ip']))[0] == 0

    @pytest.mark.skipif(not pytest.config.getoption("--vnf-dependencies"), reason="need --vnf-dependencies option to run")
    def test_vnf_dependencies(self, proxy):
        """
        Asserts:
            1. Match various config parameter sources with config primitive parameters
            Three types of sources are being verified for pong vnfd.
                Attribute: A runtime value like IP address of a connection point (../../../mgmt-interface, ip-address)
                Descriptor: a XPath to a leaf in the VNF descriptor/config (../../../mgmt-interface/port)
                Value: A pre-defined constant ('admin' as mentioned in pong descriptor)
            2. Match the config-parameter-map defined in NS descriptor
        There used to be a check to verify config parameter values in cm-state (cm-state/cm-nsr/cm-vnfr/config-parameter). 
        Recently that got removed due to confd issue. So, there is no such check currently for cm-state. 
        """
        nsr_cfg, _ = list(yield_nsrc_nsro_pairs(proxy))[0]
        con_nsr_xpath = "/cm-state/cm-nsr[id='{}']".format(nsr_cfg.id)

        pong_source_map, ping_request_map = None, None
        
        for vnfd, vnfr in yield_vnfd_vnfr_pairs(proxy):
            # Get cm-state for this vnfr
            con_vnfr_path = con_nsr_xpath + "/cm-vnfr[id='{}']".format(vnfr.id)
            con_data = proxy(RwConmanYang).get(con_vnfr_path)

            # Match various config parameter sources with config primitive parameters
            for config_primitive in vnfr.vnf_configuration.config_primitive:
                if config_primitive.name in ("config", "start-stop"):
                    for parameter in config_primitive.parameter:
                        if parameter.name == 'mgmt_ip':
                            assert parameter.default_value == vnfr.mgmt_interface.ip_address
                        if parameter.name == 'mgmt_port':
                            assert parameter.default_value == str(vnfd.mgmt_interface.port)
                        if parameter.name == 'username':
                            assert parameter.default_value == 'admin'

                # Fetch the source parameter values from pong vnf and request parameter values from ping vnf
                if config_primitive.name == "config":
                    if vnfd.name == "pong_vnfd":
                        pong_source_map = [parameter.default_value for parameter in config_primitive.parameter if
                                           parameter.name in ("service_ip", "service_port")]
                    if vnfd.name == "ping_vnfd":
                        ping_request_map = [parameter.default_value for parameter in config_primitive.parameter if
                                            parameter.name in ("pong_ip", "pong_port")]
        assert pong_source_map
        assert ping_request_map
        # Match the config-parameter-map defined in NS descriptor
        assert sorted(pong_source_map) == sorted(ping_request_map)

    @pytest.mark.skipif(not pytest.config.getoption("--port-security"), reason="need --port-security option to run")
    def test_port_security(self, proxy, vim_clients, cloud_account_name):
        """
        Asserts:
            1. port-security-enabled match in vnfd and vnfr
            2. Get port property from openstack. Match these attributes: 'port_security_enabled', 'security_groups'
        """
        for vnfd, vnfr in yield_vnfd_vnfr_pairs(proxy):
            assert vnfd.connection_point[0].port_security_enabled == vnfr.connection_point[0].port_security_enabled

            xpath = "/vlr-catalog/vlr[id='{}']".format(vnfr.connection_point[0].vlr_ref)
            vlr = proxy(RwVlrYang).get(xpath)

            vim_client = vim_clients[cloud_account_name]
            port = [port for port in vim_client.neutron_port_list() if port['network_id'] == vlr.network_id if
                    port['name'] == vnfr.connection_point[0].name]
            assert port

            port_openstack = port[0]
            assert vnfr.connection_point[0].port_security_enabled == port_openstack['port_security_enabled']

            if vnfr.connection_point[0].port_security_enabled:
                assert port_openstack['security_groups'] # It has to carry at least one security group if enabled
            else:
                assert not port_openstack['security_groups']

    @pytest.mark.skipif(
        not (pytest.config.getoption("--metadata-vdud") or pytest.config.getoption("--metadata-vdud-cfgfile")),
        reason="need --metadata-vdud or --metadata-vdud-cfgfile option to run")
    def test_metadata_vdud(self, logger, proxy, vim_clients, cloud_account_name, metadata_host):
        """
        Asserts:
            1. content of supplemental-boot-data match in vnfd and vnfr
            vnfr may carry extra custom-meta-data fields (e.g pci_assignement) which are by default enabled during VM creation by openstack.
            vnfr doesn't carry config_file details; so that will be skipped during matching.
            2. boot-data-drive match with openstack VM's config_drive attribute
            3. For each VDUD which have config-file fields mentioned, check if there exists a path in the VM which 
            matches with config-file's dest field. (Only applicable for cirros_cfgfile_vnfd VNF RIFT-15524)
            4. For each VDUD, match its custom-meta-data fields with openstack VM's properties field
        """
        for vnfd, vnfr in yield_vnfd_vnfr_pairs(proxy):
            if any(name in vnfd.name for name in ['ping', 'pong', 'fedora']):
                username, password = ['fedora'] * 2
            elif 'ubuntu' in vnfd.name:
                username, password = ['ubuntu'] * 2
            elif 'cirros' in vnfd.name:
                username, password = 'cirros', 'cubswin:)'
            else:
                assert False, 'Not expected to use this VNFD {} in this systemtest. VNFD might have changed. Exiting the test.'.format(
                    vnfd.name)

            # Wait till VNF's operational-status becomes 'running'
            # The below check is usually covered as part of test_wait_for_ns_configured
            # But, this is mostly needed when non- ping pong packages are used e.g cirrus cfgfile package
            xpath = "/vnfr-catalog/vnfr[id='{}']/operational-status".format(vnfr.id)
            proxy(VnfrYang).wait_for(xpath, "running", timeout=300)
            time.sleep(5)

            # Get the VDU details from openstack
            vim_client = vim_clients[cloud_account_name]
            vm_property = vim_client.nova_server_get(vnfr.vdur[0].vim_id)
            logger.info('VM property for {}: {}'.format(vnfd.name, vm_property))
            
            # Establish a ssh session to VDU
            ssh_session = SshSession(vnfr.vdur[0].management_ip)
            assert ssh_session
            assert ssh_session.connect(username=username, password=password)

            assert vnfd.vdu[0].supplemental_boot_data.boot_data_drive == vnfr.vdur[
                0].supplemental_boot_data.boot_data_drive == bool(vm_property['config_drive'])
            # Using bool() because vm_property['config_drive'] returns 'True' or '' whereas vnfr/vnfd returns True/False

            # Assert 3: only for cirros vnf
            if 'cirros' in vnfd.name:
                for config_file in vnfd.vdu[0].supplemental_boot_data.config_file:
                   assert ssh_session.run_command('test -e {}'.format(config_file.dest))[0] == 0

            vdur_metadata = {metadata.name: metadata.value for metadata in
                             vnfr.vdur[0].supplemental_boot_data.custom_meta_data}

            # Get the user-data/metadata from VM
            e_code, vm_metadata, _ = ssh_session.run_command(
                'curl http://{}/openstack/latest/meta_data.json'.format(metadata_host))
            assert e_code == 0
            vm_metadata = json.loads(vm_metadata)['meta']
            logger.debug('VM metadata for {}: {}'.format(vnfd.name, vm_metadata))

            for vdud_metadata in vnfd.vdu[0].supplemental_boot_data.custom_meta_data:
                assert vdud_metadata.value == vdur_metadata[vdud_metadata.name]
                assert vdud_metadata.value == vm_metadata[vdud_metadata.name]

    @pytest.mark.skipif(not pytest.config.getoption("--multidisk"), reason="need --multidisk option to run")
    def test_multidisk(self, logger, proxy, vim_clients, cloud_account_name, multidisk_testdata):
        """
        This feature is only supported in openstack, brocade vCPE.
        Asserts:
            1. volumes match in vnfd and vnfr
            2. volumes match in vnfr and openstack host
            Check no of volumes attached to the VNF VM. It should match no of volumes defined in VDUD.
            Match volume names. In 'openstack volume show <vol_uuid>', the device should be /dev/<volume_name_in_vdud>
            Match the volume source.
            Match the volume size.
            Match the Volume IDs mentioned in VNFR with openstack volume's ID.
        """
        ping_test_data, pong_test_data = multidisk_testdata
        vol_attr = ['device_type', None, 'size', 'image', 'boot_priority']
        # device_bus doesn't appear in vnfr/vdur

        for vnfd, vnfr in yield_vnfd_vnfr_pairs(proxy):
            logger.info('Verifying VNF {}'.format(vnfd.name))
            vnf_testdata = ping_test_data if 'ping' in vnfd.name else pong_test_data
            
            # Assert 1: Match volumes in vnfd, vnfr, test data
            assert len(vnfd.vdu[0].volumes) == len(vnfr.vdur[0].volumes)

            for vnfr_vol in vnfr.vdur[0].volumes:
                logger.info('Verifying vnfr volume: {}'.format(vnfr_vol.as_dict()))
                vnfd_vol = [vol for vol in vnfd.vdu[0].volumes if vol.name==vnfr_vol.name][0]

                vol_testdata = vnf_testdata[vnfr_vol.name]

                for i, attr in enumerate(vol_attr):
                    if attr == None:    # device_bus doesn't appear in vnfr/vdur
                        continue
                    if i == 3 and (vol_testdata[i]==None or getattr(vnfd_vol, 'ephemeral')):
                        # volume source of type ephemeral doesn't appear in vnfr/vdur
                        # If no image is defined for a volume, getattr(vnfr_vol, 'ephemeral') returns False. Strange. RIFT-15165
                        assert not getattr(vnfd_vol, 'image')
                        continue
                        
                    assert getattr(vnfd_vol, attr) == getattr(vnfr_vol, attr)
                    if vol_testdata[i] is not None:
                        assert getattr(vnfd_vol, attr) == vol_testdata[i]

            # Assert 2: Volumes match in vnfr and openstack host
            # Get VM properties from the VIM
            vim_client = vim_clients[cloud_account_name]
            vm_property = vim_client.nova_server_get(vnfr.vdur[0].vim_id)
            logger.info('VIM- VM properties: {}'.format(vm_property))
            
            # Get the volumes attached to this VNF VM
            vim_volumes = vm_property['os-extended-volumes:volumes_attached']
            logger.info('VIM- Volumes attached to this VNF VM: {}'.format(vim_volumes))
            
            assert vim_volumes
            assert len(vim_volumes) == len(vnfr.vdur[0].volumes)

            for vim_volume in vim_volumes:
                # Match the Volume IDs mentioned in VNFR with openstack volume's ID.
                logger.info('Verifying volume: {}'.format(vim_volume['id']))
                vnfr_vol_ = [vol for vol in vnfr.vdur[0].volumes if vol.volume_id==vim_volume['id']]
                assert vnfr_vol_
                vnfr_vol_ = vnfr_vol_[0]

                # Get volume details. Equivalent cli: openstack volume show <uuid>
                vim_vol_attrs = vim_client.cinder_volume_get(vim_volume['id'])

                # Match volume size
                assert vnfr_vol_.size == vim_vol_attrs.size

                # Match volume source
                if vnfr_vol_.image: # To make sure this is not ephemeral type
                    logger.info('VIM- Image details of the volume: {}'.format(vim_vol_attrs.volume_image_metadata))
                    assert vnfr_vol_.image == vim_vol_attrs.volume_image_metadata['image_name']
                else:
                    assert not hasattr(vim_vol_attrs, 'volume_image_metadata')

                # Match volume name e.g 'device': u'/dev/vdf'
                logger.info('VIM- Volume attachment details: {}'.format(vim_vol_attrs.attachments))
                assert [attachment for attachment in vim_vol_attrs.attachments if vnfr_vol_.name in attachment['device']]

    @pytest.mark.skipif(not pytest.config.getoption("--l2-port-chaining"), reason="need --l2-port-chaining option to run")
    def test_l2_port_chaining(self, proxy):
        """
        It uses existing NS, VNF packages: $RIFT_INSTALL/usr/rift/mano/nsds/vnffg_demo_nsd/vnffg_l2portchain_*.
        This test function is specific to these packages. Those VNFs use Ubuntu trusty image ubuntu_trusty_1404.qcow2.
        Asserts:
            1. Count of VNFFG in nsd and nsr
            2. Count of rsp, classifier in VNFFG descriptor and VNFFG record
            3.              Need details what other fields need to be matched in nsd and nsr
            4. Traffic flows through internal hops as per the classifier and rsp
            As per the classifiers in NS package, the following flows will be tested.
            - Tcp packets with dest port 80 starting from pgw VNF should go through Firewall VNF.
            - Udp packets with source port 80 starting from router VNF should go through nat->dpi
            - Udp packets with dest port 80 starting from pgw VNF should go through dpi->nat

        """
        UDP_PROTOCOL, TCP_PROTOCOL = 17, 6

        def pcap_analysis(pcap_file, src_add, dst_add, src_port=None, dst_port=None, protocol=6):
            """Analyse packets in a pcap file and return True if there is a packet match w.r.t src_addr, dst_addr, protocol.
            Args:
                pcap_file: pcap file that is generated by traffic analysis utility such as tcpdump
                src_add, dst_addr: Source & dest IP which need to be matched for a packet
                protocol: Protocol that needs to be matched for a packet which already matched src_addr, dst_addr (protocol accepts integer e.g TCP 6, UDP 17)
            
            Returns:
                timestamp of the packet which is matched (Needed to check packet flow order through VNFs)
                or
                False: if there is no packet match

            It uses scapy module to analyse pcap file. pip3 install scapy-python3
            Other options https://pypi.python.org/pypi/pypcapfile
            """
            assert os.path.exists(pcap_file)
            pkt_type = TCP if protocol==6 else UDP

            pcap_obj = rdpcap(pcap_file)
            for pkt in pcap_obj:
                if IP in pkt:
                    if not(pkt[IP].src==src_add and pkt[IP].dst==dst_add and pkt[IP].proto==protocol):
                        continue
                    if pkt_type in pkt:
                        if src_port:
                            if not (pkt[pkt_type].sport==src_port):
                                continue
                        if dst_port:
                            if not (pkt[pkt_type].dport==dst_port):
                                continue
                    return pkt[IP].time
            return False

        # Check the VNFFG in nsd and nsr
        for nsd, nsr in yield_nsd_nsr_pairs(proxy):
            vnffgds = nsd.vnffgd
            vnffgrs = nsr.vnffgr
            assert len(vnffgds) == len(vnffgrs)

        # Check the classifier, rsp in nsd and nsr
        for vnffgd in vnffgds:
            vnffgr = [vnffgr for vnffgr in vnffgrs if vnffgd.id == vnffgr.vnffgd_id_ref][0]
            assert len(vnffgd.rsp) == len(vnffgr.rsp)
            assert len(vnffgd.classifier) == len(vnffgr.classifier)

        vnfrs = proxy(RwVnfrYang).get('/vnfr-catalog/vnfr', list_obj=True)

        # Get the IP of VMs
        vm_names = ('router', 'firewall', 'dpi', 'nat', 'pgw')
        vm_ips = {vm_name: vnfr.vdur[0].vm_management_ip for vm_name in vm_names for vnfr in vnfrs.vnfr if
                  vm_name in vnfr.name}
        vm_cp_ips = {vm_name: vnfr.connection_point[0].ip_address for vm_name in vm_names for vnfr in vnfrs.vnfr if
                  vm_name in vnfr.name}

        # Establish Ssh sessions to the VMs
        ssh_sessions = {}
        for vm_name, vm_ip in vm_ips.items():
            ssh_session = SshSession(vm_ip)
            assert ssh_session
            assert ssh_session.connect(username='ubuntu', password='ubuntu')
            ssh_sessions[vm_name] = ssh_session

        # Start python's SimpleHTTPServer on port 80 in the router VM
        e_code, _, _ = ssh_sessions['router'].run_command('sudo python -m SimpleHTTPServer 80', max_wait=5)
        assert e_code is None   # Due to blocking call, it should timeout and return 'None' as exit code


        # Check: Tcp packets with dest port 80 starting from pgw VNF should go through Firewall VNF.
        pcap_file = 'l2test_firewall.pcap'
        # Start tcpdump in firewall vnf and start sending tcp packets from pgw vnf
        e_code, _, _ = ssh_sessions['firewall'].run_command(
            'sudo tcpdump -i eth1 -w {pcap} & sleep 10; sudo kill $!'.format(pcap=pcap_file), max_wait=4)
        e_code, _, _ = ssh_sessions['pgw'].run_command('sudo nc {router_ip} 80 -w 0'.format(router_ip=vm_cp_ips['router']))

        # Copy pcap file from firewall vnf for packet analysis
        time.sleep(10)
        assert ssh_sessions['firewall'].get(pcap_file, pcap_file)
        assert pcap_analysis(pcap_file, vm_cp_ips['pgw'], vm_cp_ips['router'], dst_port=80, protocol=TCP_PROTOCOL)


        # Check: Udp packets with source port 80 starting from router VNF should go through nat->dpi
        pcap_nat = 'l2test_nat1.pcap'
        pcap_dpi = 'l2test_dpi1.pcap'
        # Start tcpdump in nat, dpi vnf and start sending udp packets from router vnf
        e_code, _, _ = ssh_sessions['nat'].run_command(
            'sudo tcpdump -i eth1 -w {pcap} & sleep 15; sudo kill $!'.format(pcap=pcap_nat), max_wait=4)
        e_code, _, _ = ssh_sessions['dpi'].run_command(
            'sudo tcpdump -i eth1 -w {pcap} & sleep 10; sudo kill $!'.format(pcap=pcap_dpi), max_wait=4)
        e_code, _, _ = ssh_sessions['router'].run_command(
            'echo -n "hello" |  sudo nc -4u {pgw_ip} 1000 -s {router_ip} -p 80 -w 0'.format(pgw_ip=vm_cp_ips['pgw'],
                                                                                            router_ip=vm_cp_ips[
                                                                                                'router']))

        # Copy pcap file from nat, dpi vnf for packet analysis
        time.sleep(10)
        assert ssh_sessions['nat'].get(pcap_nat, pcap_nat)
        assert ssh_sessions['dpi'].get(pcap_dpi, pcap_dpi)
        packet_ts_nat = pcap_analysis(pcap_nat, vm_cp_ips['router'], vm_cp_ips['pgw'], src_port=80, protocol=UDP_PROTOCOL)
        packet_ts_dpi = pcap_analysis(pcap_dpi, vm_cp_ips['router'], vm_cp_ips['pgw'], src_port=80, protocol=UDP_PROTOCOL)
        assert packet_ts_nat
        assert packet_ts_dpi
        assert packet_ts_nat < packet_ts_dpi    # Packet flow must follow nat -> dpi


        # Check: Udp packets with dest port 80 starting from pgw VNF should go through dpi->nat
        pcap_nat = 'l2test_nat2.pcap'
        pcap_dpi = 'l2test_dpi2.pcap'
        # Start tcpdump in nat, dpi vnf and start sending udp packets from router vnf
        e_code, _, _ = ssh_sessions['nat'].run_command(
            'sudo tcpdump -i eth1 -w {pcap} & sleep 15; sudo kill $!'.format(pcap=pcap_nat), max_wait=4)
        e_code, _, _ = ssh_sessions['dpi'].run_command(
            'sudo tcpdump -i eth1 -w {pcap} & sleep 10; sudo kill $!'.format(pcap=pcap_dpi), max_wait=4)
        e_code, _, _ = ssh_sessions['pgw'].run_command(
            'echo -n "hello" | sudo nc -4u {router_ip} 80 -w 0'.format(router_ip=vm_cp_ips['router']))

        # Copy pcap file from nat, dpi vnf for packet analysis
        time.sleep(10)
        assert ssh_sessions['nat'].get(pcap_nat, pcap_nat)
        assert ssh_sessions['dpi'].get(pcap_dpi, pcap_dpi)
        packet_ts_nat = pcap_analysis(pcap_nat, vm_cp_ips['pgw'], vm_cp_ips['router'], dst_port=80, protocol=UDP_PROTOCOL)
        packet_ts_dpi = pcap_analysis(pcap_dpi, vm_cp_ips['pgw'], vm_cp_ips['router'], dst_port=80, protocol=UDP_PROTOCOL)
        assert packet_ts_nat
        assert packet_ts_dpi
        # The below assert used to fail while testing. ts_dpi is ahead of ts_nat in few microseconds
        # Need to confirm if thats expected
        assert packet_ts_dpi < packet_ts_nat    # Packet flow must follow dpi -> nat

@pytest.mark.depends('nsr')
@pytest.mark.setup('nfvi')
@pytest.mark.incremental
class TestNfviMetrics(object):

    def test_records_present(self, proxy):
        assert_records(proxy)

    @pytest.mark.skipif(True, reason='NFVI metrics collected from NSR are deprecated, test needs to be updated to collected metrics from VNFRs')
    def test_nfvi_metrics(self, proxy):
        """
        Verify the NFVI metrics

        Asserts:
            1. Computed metrics, such as memory, cpu, storage and ports, match
               with the metrics in NSR record. The metrics are computed from the
               descriptor records.
            2. Check if the 'utilization' field has a valid value (> 0) and matches
               with the 'used' field, if available.
        """
        for nsd, nsr in yield_nsd_nsr_pairs(proxy):
            nfvi_metrics = nsr.nfvi_metrics
            computed_metrics = collections.defaultdict(int)

            # Get the constituent VNF records.
            for vnfd, vnfr in yield_vnfd_vnfr_pairs(proxy, nsr):
                vdu = vnfd.vdu[0]
                vm_spec = vdu.vm_flavor
                computed_metrics['vm'] += 1
                computed_metrics['memory'] += vm_spec.memory_mb * (10**6)
                computed_metrics['storage'] += vm_spec.storage_gb * (10**9)
                computed_metrics['vcpu'] += vm_spec.vcpu_count
                computed_metrics['external_ports'] += len(vnfd.connection_point)
                computed_metrics['internal_ports'] += len(vdu.internal_connection_point)

            assert nfvi_metrics.vm.active_vm == computed_metrics['vm']

            # Availability checks
            for metric_name in computed_metrics:
                metric_data = getattr(nfvi_metrics, metric_name)
                total_available = getattr(metric_data, 'total', None)

                if total_available is not None:
                    assert computed_metrics[metric_name] == total_available

            # Utilization checks
            for metric_name in ['memory', 'storage', 'vcpu']:
                metric_data = getattr(nfvi_metrics, metric_name)

                utilization = metric_data.utilization
                # assert utilization > 0

                # If used field is available, check if it matches with utilization!
                total = metric_data.total
                used = getattr(metric_data, 'used', None)
                if used is not None:
                    assert total > 0
                    computed_utilization = round((used/total) * 100, 2)
                    assert abs(computed_utilization - utilization) <= 0.1



@pytest.mark.depends('nfvi')
@pytest.mark.incremental
class TestRecordsDescriptors:
    def test_create_update_vnfd(self, proxy, updated_ping_pong_records):
        """
        Verify VNFD related operations

        Asserts:
            If a VNFD record is created
        """
        ping_vnfd, pong_vnfd, _ = updated_ping_pong_records
        vnfdproxy = proxy(RwVnfdYang)

        for vnfd_record in [ping_vnfd, pong_vnfd]:
            xpath = "/vnfd-catalog/vnfd"
            vnfdproxy.create_config(xpath, vnfd_record.vnfd)

            xpath = "/vnfd-catalog/vnfd[id='{}']".format(vnfd_record.id)
            vnfd = vnfdproxy.get(xpath)
            assert vnfd.id == vnfd_record.id

            vnfdproxy.replace_config(xpath, vnfd_record.vnfd)

    def test_create_update_nsd(self, proxy, updated_ping_pong_records):
        """
        Verify NSD related operations

        Asserts:
            If NSD record was created
        """
        _, _, ping_pong_nsd = updated_ping_pong_records
        nsdproxy = proxy(NsdYang)

        xpath = "/nsd-catalog/nsd"
        nsdproxy.create_config(xpath, ping_pong_nsd.descriptor)

        xpath = "/nsd-catalog/nsd[id='{}']".format(ping_pong_nsd.id)
        nsd = nsdproxy.get(xpath)
        assert nsd.id == ping_pong_nsd.id

        nsdproxy.replace_config(xpath, ping_pong_nsd.descriptor)

