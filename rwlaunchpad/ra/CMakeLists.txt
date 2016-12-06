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
# Author(s): Paul Laidler
# Creation Date: 09/16/2015
# 

cmake_minimum_required(VERSION 2.8)

install(
  PROGRAMS
    pingpong_longevity_systest
    pingpong_vnf_systest
    pingpong_records_systest
    pingpong_vnf_reload_systest
    pingpong_lp_ha_systest
    pingpong_recovery_systest
    pingpong_scaling_systest
    scaling_systest
  DESTINATION usr/rift/systemtest/pingpong_vnf
  COMPONENT ${PKG_LONG_NAME})

install(
  PROGRAMS
    multi_vm_vnf_slb_systest.sh
    multi_vm_vnf_trafgen_systest.sh
  DESTINATION usr/rift/systemtest/multi_vm_vnf
  COMPONENT ${PKG_LONG_NAME})

install(
  FILES
    pytest/multivm_vnf/conftest.py
    pytest/multivm_vnf/test_multi_vm_vnf_slb.py
    pytest/multivm_vnf/test_multi_vm_vnf_trafgen.py
    pytest/multivm_vnf/test_trafgen_data.py
  DESTINATION usr/rift/systemtest/pytest/multi_vm_vnf
  COMPONENT ${PKG_LONG_NAME})

install(
  PROGRAMS
    launchpad_longevity_systest
    launchpad_systest
  DESTINATION usr/rift/systemtest/launchpad
  COMPONENT ${PKG_LONG_NAME})

install(
  FILES
    racfg/multi_tenant_systest_openstack.racfg
  DESTINATION usr/rift/systemtest/launchpad
  COMPONENT ${PKG_LONG_NAME})

install(
  FILES
    pytest/conftest.py
    pytest/test_launchpad.py
    pytest/test_launchpad_longevity.py
    pytest/test_start_standby.py
    pytest/test_failover.py
  DESTINATION usr/rift/systemtest/pytest/system
  COMPONENT ${PKG_LONG_NAME})

install(
  FILES
    pytest/ns/conftest.py
    pytest/ns/test_onboard.py
  DESTINATION usr/rift/systemtest/pytest/system/ns
  COMPONENT ${PKG_LONG_NAME})

install(
  FILES
    pytest/ns/pingpong/test_pingpong.py
    pytest/ns/pingpong/test_pingpong_longevity.py
    pytest/ns/pingpong/test_records.py
    pytest/ns/pingpong/test_scaling.py
  DESTINATION usr/rift/systemtest/pytest/system/ns/pingpong
  COMPONENT ${PKG_LONG_NAME})

install(
  FILES
    pytest/ns/haproxy/test_scaling.py
  DESTINATION usr/rift/systemtest/pytest/system/ns/haproxy
  COMPONENT ${PKG_LONG_NAME})

install(
  FILES
    racfg/pingpong_vnf_systest_cloudsim.racfg
    racfg/pingpong_vnf_systest_openstack.racfg
    racfg/pingpong_scaling_systest_openstack.racfg
    racfg/pingpong_records_systest_cloudsim.racfg
    racfg/pingpong_records_systest_openstack.racfg
    racfg/pingpong_records_systest_openstack_xml.racfg
    racfg/pingpong_vnf_reload_systest_openstack.racfg
    racfg/pingpong_vnf_reload_systest_openstack_xml.racfg
    racfg/scaling_systest.racfg
    racfg/recovery_systest.racfg
    racfg/pingpong_lp_ha_systest_openstack.racfg
  DESTINATION usr/rift/systemtest/pingpong_vnf
  COMPONENT ${PKG_LONG_NAME})

install(
  FILES
    racfg/multivm_vnf_slb_systest.racfg
    racfg/multivm_vnf_trafgen_systest.racfg
  DESTINATION usr/rift/systemtest/multi_vm_vnf
  COMPONENT ${PKG_LONG_NAME})
