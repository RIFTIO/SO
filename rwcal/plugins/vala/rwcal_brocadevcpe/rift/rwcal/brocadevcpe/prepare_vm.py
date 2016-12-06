#!/usr/bin/env python3

# STANDARD_RIFT_IO_COPYRIGHT

import rift.rwcal.brocadevcpe as brocadevcpe_drv
import logging
import argparse
import sys, os, time
import rwlogger

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

rwlog_handler = rwlogger.RwLogger(category="rw-cal-log",
                                  subcategory="prop-cloud1",)
logger.addHandler(rwlog_handler)
#logger.setLevel(logging.DEBUG)

def get_mgmt_ip( drv, host, mgmt_network, vm_cfg, vm_state):
    if vm_cfg is None:
        return

    for port in vm_cfg.devices.network:
        vhost_intf = drv.get_vhost_interface(port.name)
        if vhost_intf is not None: 
             # Need to optimize this later. We can do one GET
             port_ip = drv.get_port_ip(port.mac_address, host)
             if port_ip is None:
                 continue
             if  'description' in vhost_intf and ((vhost_intf.description.split())[1] == mgmt_network):
                 return port_ip


def assign_floating_ip_address(drv, argument):
    if not argument.public_ip_pool:
        return

    logger.info("Assigning the public ip to VM: %s" %(argument.server_id))
    
    for i in range(60):
        vm_cfg, vm_state = drv.get_vm(argument.server_id)
        if vm_cfg is None or vm_state is None:
            logger.info("Waiting for get_vm %s" %(argument.server_id))
            time.sleep(5)
            continue

        mgmt_ip = get_mgmt_ip( drv, argument.host, argument.mgmt_network, vm_cfg, vm_state)
        if mgmt_ip is None:
            logger.info("Waiting for management_ip to be assigned to server: %s" %(argument.server_id))
            time.sleep(5)
            continue
        floating_ip = drv.assign_floating_ip(argument.public_ip_pool, mgmt_ip, argument.wan_interface)
        logger.info("Assigned floating_ip %s to management_ip: %s" %(floating_ip, mgmt_ip))
        return
    else:
        logger.info("No management_ip IP available to associate floating_ip for server: %s" %(argument.server_id))
    return


def prepare_vm_after_boot(drv,argument):
    logger.info("Prepare VM operation: %s" %(argument))
    assign_floating_ip_address(drv, argument)
    

def main():
    """
    Main routine
    """
    parser = argparse.ArgumentParser(description='Script to create VCPE resources')
    parser.add_argument('--host',
                        action = "store",
                        dest = "host",
                        type = str,
                        help='VCPE Host IP')

    parser.add_argument('--username',
                        action = "store",
                        dest = "username",
                        type = str,
                        help = "Username for VCPE installation")

    parser.add_argument('--password',
                        action = "store",
                        dest = "password",
                        type = str,
                        help = "Password for VCPE installation")

    parser.add_argument('--mgmt_network',
                        action = "store",
                        dest = "mgmt_network",
                        type = str,
                        help = "Mgmt network for VCPE installation")

    parser.add_argument('--public_ip_pool',
                        action = "store",
                        dest = "public_ip_pool",
                        type = str,
                        help = "Public IP pool for VCPE installation")

    parser.add_argument('--wan_interface',
                        action = "store",
                        dest = "wan_interface",
                        type = str,
                        help = "WAN interface for VCPE installation")

    parser.add_argument('--server_id',
                        action = "store",
                        dest = "server_id",
                        type = str,
                        help = "Server ID on which boot operations needs to be performed")

    argument = parser.parse_args()

    if not argument.host:
        logger.error("ERROR: Host is not configured")
        sys.exit(1)
    else:
        logger.info("Using Host: %s" %(argument.host))

    if not argument.username:
        logger.error("ERROR: Username is not configured")
        sys.exit(1)
    else:
        logger.info("Using Username: %s" %(argument.username))

    if not argument.password:
        logger.error("ERROR: Password is not configured")
        sys.exit(1)
    else:
        logger.info("Using Password: %s" %(argument.password))

    if not argument.mgmt_network:
        logger.error("ERROR: Mgmt network is not configured")
        sys.exit(1)
    else:
        logger.info("Using mgmt network: %s" %(argument.mgmt_network))

    if not argument.public_ip_pool:
        logger.error("ERROR: Public IP pool is not configured")
        sys.exit(1)
    else:
        logger.info("Using public pool network: %s" %(argument.public_ip_pool))

    if not argument.wan_interface:
        logger.error("ERROR: WAN interface is not configured")
        sys.exit(1)
    else:
        logger.info("Using WAN interface %s" %(argument.wan_interface))

    if not argument.server_id:
        logger.error("ERROR: Server ID is not configured")
        sys.exit(1)
    else:
        logger.info("Using Server ID : %s" %(argument.server_id))
        
        
    try:
        pid = os.fork()
        if pid > 0:
            # exit for parent
            sys.exit(0)
    except OSError as e:
        logger.error("fork failed: %d (%s)\n" % (e.errno, e.strerror))
        sys.exit(2)
        
    drv = brocadevcpe_drv.BrocadeVcpeDriver(host = argument.host,
                                        username = argument.username,
                                        password = argument.password,
                                        mgmt_network = argument.mgmt_network,
                                        public_ip_pool=argument.public_ip_pool)
    prepare_vm_after_boot(drv, argument)
    sys.exit(0)
    
if __name__ == "__main__":
    main()
        

