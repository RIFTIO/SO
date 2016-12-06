# RIFT_IO_STANDARD_CMAKE_COPYRIGHT_HEADER(BEGIN)
# Author(s): Tim Mortsolf
# Creation Date: 2014/03/13
# RIFT_IO_STANDARD_CMAKE_COPYRIGHT_HEADER(END)

include(rift_yang)

##
# Set various yang files
##
set(vcpe_yang_files
     configd-v1.yang
     vyatta-types-v1.yang
     vyatta-dscp-v1.yang
     vyatta-services-v1.yang
     vyatta-service-dhcp-server-v1.yang
     vyatta-xconnect-v1.yang
     vyatta-interfaces-vif-v2.yang
     vyatta-interfaces-v1.yang 
     vyatta-interfaces-tunnel-v1.yang
     vyatta-interfaces-bonding-v1.yang
     vyatta-interfaces-l2tpeth-v1.yang
     vyatta-interfaces-dataplane-v1.yang
     vyatta-interfaces-dataplane-unnumbered-v1.yang
     vyatta-interfaces-bridge-v1.yang
     vyatta-interfaces-vhost-v1.yang
     vyatta-interfaces-vhost-vif-v1.yang
     vyatta-interfaces-vhost-bridge-v1.yang
     vyatta-virtualization-v1.yang
     vyatta-service-nat-v1.yang
     vyatta-fw-types-v1.yang
     vyatta-npf-v1.yang
     vyatta-interfaces-policy-v1.yang
     vyatta-policy-v1.yang
     vyatta-policy-route-v1.yang
     vyatta-policy-pbr-v1.yang
     vyatta-interfaces-vhost-policy-v1.yang
     vyatta-interfaces-vhost-pbr-v1.yang
     vyatta-interfaces-vti-v1.yang
     vyatta-interfaces-openvpn-v1.yang
     vyatta-interfaces-loopback-v1.yang
     vyatta-security-v1.yang
     vyatta-security-firewall-v1.yang
     vyatta-ipv6-rtradv-v1.yang
     vyatta-service-https-v1.yang
     vyatta-dhcp-client-v1.yang
     vyatta-service-dns-v1.yang
     rift-vyatta-composite.yang
  )

##
# function to add targets for .yang->.xsd->.proto
##
rift_add_yang_target(
  TARGET vcpe_yang
  YANG_FILES ${vcpe_yang_files}
  COMPONENT ${PKG_LONG_NAME}
  LIBRARIES
    rwschema_yang_gen
    rwyang
)

