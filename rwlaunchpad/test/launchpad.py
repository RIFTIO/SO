#!/usr/bin/env python3

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


import logging
import os
import resource
import socket
import sys
import subprocess
import shlex
import shutil
import netifaces

from rift.rwlib.util import certs
import rift.rwcal.cloudsim
import rift.rwcal.cloudsim.net
import rift.vcs
import rift.vcs.core as core
import rift.vcs.demo
import rift.vcs.vms

import rift.rwcal.cloudsim
import rift.rwcal.cloudsim.net

from rift.vcs.ext import ClassProperty

logger = logging.getLogger(__name__)


class NsmTasklet(rift.vcs.core.Tasklet):
    """
    This class represents a network services manager tasklet.
    """

    def __init__(self, name='network-services-manager', uid=None,
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        """
        Creates a NsmTasklet object.

        Arguments:
            name  - the name of the tasklet
            uid   - a unique identifier
        """
        super(NsmTasklet, self).__init__(name=name, uid=uid,
                                         config_ready=config_ready,
                                         recovery_action=recovery_action,
                                         data_storetype=data_storetype,
                                        )

    plugin_directory = ClassProperty('./usr/lib/rift/plugins/rwnsmtasklet')
    plugin_name = ClassProperty('rwnsmtasklet')


class VnsTasklet(rift.vcs.core.Tasklet):
    """
    This class represents a network services manager tasklet.
    """

    def __init__(self, name='virtual-network-service', uid=None,
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        """
        Creates a VnsTasklet object.

        Arguments:
            name  - the name of the tasklet
            uid   - a unique identifier
        """
        super(VnsTasklet, self).__init__(name=name, uid=uid,
                                         config_ready=config_ready,
                                         recovery_action=recovery_action,
                                         data_storetype=data_storetype,
                                        )

    plugin_directory = ClassProperty('./usr/lib/rift/plugins/rwvnstasklet')
    plugin_name = ClassProperty('rwvnstasklet')


class VnfmTasklet(rift.vcs.core.Tasklet):
    """
    This class represents a virtual network function manager tasklet.
    """

    def __init__(self, name='virtual-network-function-manager', uid=None,
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        """
        Creates a VnfmTasklet object.

        Arguments:
            name  - the name of the tasklet
            uid   - a unique identifier
        """
        super(VnfmTasklet, self).__init__(name=name, uid=uid,
                                          config_ready=config_ready,
                                          recovery_action=recovery_action,
                                          data_storetype=data_storetype,
                                         )

    plugin_directory = ClassProperty('./usr/lib/rift/plugins/rwvnfmtasklet')
    plugin_name = ClassProperty('rwvnfmtasklet')


class ResMgrTasklet(rift.vcs.core.Tasklet):
    """
    This class represents a Resource Manager tasklet.
    """

    def __init__(self, name='Resource-Manager', uid=None,
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        """
        Creates a ResMgrTasklet object.

        Arguments:
            name  - the name of the tasklet
            uid   - a unique identifier
        """
        super(ResMgrTasklet, self).__init__(name=name, uid=uid,
                                            config_ready=config_ready,
                                            recovery_action=recovery_action,
                                            data_storetype=data_storetype,
                                           )

    plugin_directory = ClassProperty('./usr/lib/rift/plugins/rwresmgrtasklet')
    plugin_name = ClassProperty('rwresmgrtasklet')


class ImageMgrTasklet(rift.vcs.core.Tasklet):
    """
    This class represents a Image Manager tasklet.
    """

    def __init__(self, name='Image-Manager', uid=None,
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        """
        Creates a Image Manager Tasklet object.

        Arguments:
            name  - the name of the tasklet
            uid   - a unique identifier
        """
        super(ImageMgrTasklet, self).__init__(
                name=name, uid=uid,
                config_ready=config_ready,
                recovery_action=recovery_action,
                data_storetype=data_storetype,
                )

    plugin_directory = ClassProperty('./usr/lib/rift/plugins/rwimagemgrtasklet')
    plugin_name = ClassProperty('rwimagemgrtasklet')


class MonitorTasklet(rift.vcs.core.Tasklet):
    """
    This class represents a tasklet that is used to monitor NFVI metrics.
    """

    def __init__(self, name='nfvi-metrics-monitor', uid=None,
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        """
        Creates a MonitorTasklet object.

        Arguments:
            name  - the name of the tasklet
            uid   - a unique identifier

        """
        super(MonitorTasklet, self).__init__(name=name, uid=uid,
                                             config_ready=config_ready,
                                             recovery_action=recovery_action,
                                             data_storetype=data_storetype,
                                            )

    plugin_directory = ClassProperty('./usr/lib/rift/plugins/rwmonitor')
    plugin_name = ClassProperty('rwmonitor')

class RedisServer(rift.vcs.NativeProcess):
    def __init__(self, name="RW.Redis.Server",
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        super(RedisServer, self).__init__(
                name=name,
                exe="/usr/bin/redis-server",
                config_ready=config_ready,
                recovery_action=recovery_action,
                data_storetype=data_storetype,
                )

    @property
    def args(self):
        return "./usr/bin/active_redis.conf --port 9999"


class MonitoringParameterTasklet(rift.vcs.core.Tasklet):
    """
    This class represents a tasklet that is used to generate monitoring
    parameters.
    """

    def __init__(self, name='Monitoring-Parameter', uid=None,
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        """
        Creates a MonitoringParameterTasklet object.

        Arguments:
            name  - the name of the tasklet
            uid   - a unique identifier

        """
        super(MonitoringParameterTasklet, self).__init__(name=name, uid=uid,
                                             config_ready=config_ready,
                                             recovery_action=recovery_action,
                                             data_storetype=data_storetype,
                                            )

    plugin_directory = ClassProperty('./usr/lib/rift/plugins/rwmonparam')
    plugin_name = ClassProperty('rwmonparam')


class AutoscalerTasklet(rift.vcs.core.Tasklet):
    """
    This class represents a tasklet that is used to generate monitoring
    parameters.
    """

    def __init__(self, name='Autoscaler', uid=None,
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        """
        Creates a MonitoringParameterTasklet object.

        Arguments:
            name  - the name of the tasklet
            uid   - a unique identifier

        """
        super(AutoscalerTasklet, self).__init__(name=name, uid=uid,
                                             config_ready=config_ready,
                                             recovery_action=recovery_action,
                                             data_storetype=data_storetype,
                                            )

    plugin_directory = ClassProperty('./usr/lib/rift/plugins/rwautoscaler')
    plugin_name = ClassProperty('rwautoscaler')

class StagingManagerTasklet(rift.vcs.core.Tasklet):
    """
    A class that provide a simple staging area for all tasklets
    """

    def __init__(self, name='StagingManager', uid=None,
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        """
        Creates a StagingMangerTasklet object.

        Arguments:
            name  - the name of the tasklet
            uid   - a unique identifier

        """
        super(StagingManagerTasklet, self).__init__(name=name, uid=uid,
                                             config_ready=config_ready,
                                             recovery_action=recovery_action,
                                             data_storetype=data_storetype,
                                            )

    plugin_directory = ClassProperty('./usr/lib/rift/plugins/rwstagingmgr')
    plugin_name = ClassProperty('rwstagingmgr')

def get_ui_ssl_args():
    """Returns the SSL parameter string for launchpad UI processes"""

    try:
        use_ssl, certfile_path, keyfile_path = certs.get_bootstrap_cert_and_key()
    except certs.BootstrapSslMissingException:
        logger.error('No bootstrap certificates found.  Disabling UI SSL')
        use_ssl = False

    # If we're not using SSL, no SSL arguments are necessary
    if not use_ssl:
        return ""

    return "--enable-https --keyfile-path=%s --certfile-path=%s" % (keyfile_path, certfile_path)


class UIServer(rift.vcs.NativeProcess):
    def __init__(self, name="RW.MC.UI",
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        super(UIServer, self).__init__(
                name=name,
                exe="./usr/share/rw.ui/skyquake/scripts/launch_ui.sh",
                config_ready=config_ready,
                recovery_action=recovery_action,
                data_storetype=data_storetype,
                )

    @property
    def args(self):
        return get_ui_ssl_args()

class ConfigManagerTasklet(rift.vcs.core.Tasklet):
    """
    This class represents a Resource Manager tasklet.
    """

    def __init__(self, name='Configuration-Manager', uid=None,
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        """
        Creates a ConfigManagerTasklet object.

        Arguments:
            name  - the name of the tasklet
            uid   - a unique identifier
        """
        super(ConfigManagerTasklet, self).__init__(name=name, uid=uid,
                                                   config_ready=config_ready,
                                                   recovery_action=recovery_action,
                                                   data_storetype=data_storetype,
                                                  )

    plugin_directory = ClassProperty('./usr/lib/rift/plugins/rwconmantasklet')
    plugin_name = ClassProperty('rwconmantasklet')

class PackageManagerTasklet(rift.vcs.core.Tasklet):
    """
    This class represents a Resource Manager tasklet.
    """

    def __init__(self, name='Package-Manager', uid=None,
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        """
        Creates a PackageManager object.

        Arguments:
            name  - the name of the tasklet
            uid   - a unique identifier
        """
        super(PackageManagerTasklet, self).__init__(name=name, uid=uid,
                                                   config_ready=config_ready,
                                                   recovery_action=recovery_action,
                                                   data_storetype=data_storetype,
                                                  )

    plugin_directory = ClassProperty('./usr/lib/rift/plugins/rwpkgmgr')
    plugin_name = ClassProperty('rwpkgmgr')

class GlanceServer(rift.vcs.NativeProcess):
    def __init__(self, name="glance-image-catalog",
                 config_ready=True,
                 recovery_action=core.RecoveryType.FAILCRITICAL.value,
                 data_storetype=core.DataStore.NOSTORE.value,
                 ):
        super(GlanceServer, self).__init__(
                name=name,
                exe="./usr/bin/glance_start_wrapper",
                config_ready=config_ready,
                recovery_action=recovery_action,
                data_storetype=data_storetype,
                )

    @property
    def args(self):
        return "./etc/glance"


class Demo(rift.vcs.demo.Demo):
    def __init__(self, no_ui=False, ha_mode=None, mgmt_ip_list=[], test_name=None):
        procs = [
            ConfigManagerTasklet(),
            GlanceServer(),
            rift.vcs.DtsRouterTasklet(),
            rift.vcs.MsgBrokerTasklet(),
            rift.vcs.RestPortForwardTasklet(),
            rift.vcs.RestconfTasklet(),
            rift.vcs.RiftCli(),
            rift.vcs.uAgentTasklet(),
            rift.vcs.Launchpad(),
            ]

        standby_procs = [
            RedisServer(),
            rift.vcs.DtsRouterTasklet(),
            rift.vcs.MsgBrokerTasklet(),
            ]

        datastore = core.DataStore.BDB.value
        if ha_mode:
            procs.append(RedisServer())
            datastore = core.DataStore.REDIS.value

        if not no_ui:
            procs.append(UIServer())

        restart_procs = [
              VnfmTasklet(recovery_action=core.RecoveryType.RESTART.value, data_storetype=datastore),
              VnsTasklet(recovery_action=core.RecoveryType.RESTART.value, data_storetype=datastore),
              # MonitorTasklet(recovery_action=core.RecoveryType.RESTART.value, data_storetype=datastore),
              MonitoringParameterTasklet(recovery_action=core.RecoveryType.RESTART.value, data_storetype=datastore),
              NsmTasklet(recovery_action=core.RecoveryType.RESTART.value, data_storetype=datastore),
              ResMgrTasklet(recovery_action=core.RecoveryType.RESTART.value, data_storetype=datastore),
              ImageMgrTasklet(recovery_action=core.RecoveryType.RESTART.value, data_storetype=datastore),
              AutoscalerTasklet(recovery_action=core.RecoveryType.RESTART.value, data_storetype=datastore),
              PackageManagerTasklet(recovery_action=core.RecoveryType.RESTART.value, data_storetype=datastore),
              StagingManagerTasklet(recovery_action=core.RecoveryType.RESTART.value, data_storetype=datastore),
            ]

        if not mgmt_ip_list or len(mgmt_ip_list) == 0:
            mgmt_ip_list.append("127.0.0.1")

        colony = rift.vcs.core.Colony(name='top', uid=1)

        lead_lp_vm = rift.vcs.VirtualMachine(
              name='vm-launchpad-1',
              ip=mgmt_ip_list[0],
              procs=procs,
              restart_procs=restart_procs,
            )
        lead_lp_vm.leader = True
        colony.append(lead_lp_vm)

        if ha_mode:
            stby_lp_vm = rift.vcs.VirtualMachine(
                  name='launchpad-vm-2',
                  ip=mgmt_ip_list[1],
                  procs=standby_procs,
                  start=False,
                )
            # WA to Agent mode_active flag reset
            stby_lp_vm.add_tasklet(rift.vcs.uAgentTasklet(), mode_active=False)
            colony.append(stby_lp_vm)

        if ha_mode == "LSS":
            stby_lp_vm_2 = rift.vcs.VirtualMachine(
                  name='launchpad-vm-3',
                  ip=mgmt_ip_list[2],
                  procs=standby_procs,
                  start=False,
                )
            stby_lp_vm_2.add_tasklet(rift.vcs.uAgentTasklet(), mode_active=False)
            colony.append(stby_lp_vm_2)

        sysinfo = rift.vcs.SystemInfo(
                    mode='ethsim',
                    zookeeper=rift.vcs.manifest.RaZookeeper(master_ip=mgmt_ip_list[0]),
                    colonies=[colony],
                    multi_broker=True,
                    multi_dtsrouter=True,
                    mgmt_ip_list=mgmt_ip_list,
                    test_name=test_name,
                  )

        super(Demo, self).__init__(
            # Construct the system. This system consists of 1 cluster in 1
            # colony. The master cluster houses CLI and management VMs
            sysinfo = sysinfo,

            # Define the generic portmap.
            port_map = {},

            # Define a mapping from the placeholder logical names to the real
            # port names for each of the different modes supported by this demo.
            port_names = {
                'ethsim': {
                },
                'pci': {
                }
            },

            # Define the connectivity between logical port names.
            port_groups = {},
        )


def main(argv=sys.argv[1:]):
    logging.basicConfig(format='%(asctime)-15s %(levelname)s %(message)s')

    # Create a parser which includes all generic demo arguments
    parser = rift.vcs.demo.DemoArgParser()
    parser.add_argument("--no-ui", action='store_true')
    args = parser.parse_args(argv)

    # Disable loading any kernel modules for the launchpad VM
    # since it doesn't need it and it will fail within containers
    os.environ["NO_KERNEL_MODS"] = "1"

    cleanup_dir_name = None
    if os.environ["INSTALLDIR"] in ["/usr/rift",
        "/usr/rift/build/ub16_debug/install/usr/rift",
        "/usr/rift/build/fc20_debug/install/usr/rift"]:
        cleanup_dir_name = os.environ["INSTALLDIR"] + "/var/rift/"
    
    if args.test_name and not cleanup_dir_name:
        cleanup_dir_name = "find {rift_install}/var/rift -name '*{pattern}*' -type d".format( \
            rift_install=os.environ['RIFT_INSTALL'],
            pattern = args.test_name)
        try:
            cleanup_dir_name = subprocess.check_output(cleanup_dir_name, shell=True)
            cleanup_dir_name = cleanup_dir_name[:-1].decode("utf-8") + "/"
        except Exception as e:
            print ("Directory not found exception occurred. Probably running for first time")
            print ("Zookeper cleanup cmd = {}".format(cleanup_dir_name))
    else:
        if not cleanup_dir_name:
          cleanup_dir_name = os.environ["INSTALLDIR"] + "/"

    # Remove the persistent Redis data
    try:
        for f in os.listdir(cleanup_dir_name):
            if f.endswith(".aof") or f.endswith(".rdb"):
                os.remove(os.path.join(cleanup_dir_name, f))
    
        # Remove the persistant DTS recovery files 
        for f in os.listdir(cleanup_dir_name):
            if f.endswith(".db"):
                os.remove(os.path.join(cleanup_dir_name, f))

        shutil.rmtree(os.path.join(cleanup_dir_name, "zk/server-1"))
        shutil.rmtree(os.path.join(os.environ["INSTALLDIR"], "var/rift/tmp*"))
    except FileNotFoundError as e:
        pass
    except Exception as e:
        print ("Error while cleanup: {}".format(str(e)))

    ha_mode = args.ha_mode
    mgmt_ip_list = [] if not args.mgmt_ip_list else args.mgmt_ip_list

    #load demo info and create Demo object
    demo = Demo(args.no_ui, ha_mode, mgmt_ip_list, args.test_name)

    # Create the prepared system from the demo
    system = rift.vcs.demo.prepared_system_from_demo_and_args(demo, args,
              northbound_listing="cli_launchpad_schema_listing.txt",
              netconf_trace_override=True)

    # Search for externally accessible IP address with netifaces
    gateways = netifaces.gateways()
    # Check for default route facing interface and then get its ip address
    if 'default' in gateways:
        interface = gateways['default'][netifaces.AF_INET][1]
        confd_ip = netifaces.ifaddresses(interface)[netifaces.AF_INET][0]['addr']
    else:
        # no default gateway.  Revert to 127.0.0.1
        confd_ip = "127.0.0.1"
    # TODO: This need to be changed when launchpad starts running on multiple VMs
    rift.vcs.logger.configure_sink(config_file=None, confd_ip=confd_ip)

    # Start the prepared system
    system.start()


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CORE, (resource.RLIM_INFINITY, resource.RLIM_INFINITY) )
    os.system('/usr/rift/bin/UpdateHostsFile')
    try:
        main()
    except rift.vcs.demo.ReservationError:
        print("ERROR: unable to retrieve a list of IP addresses from the reservation system")
        sys.exit(1)
    except rift.vcs.demo.MissingModeError:
        print("ERROR: you need to provide a mode to run the script")
        sys.exit(1)
    finally:
        os.system("stty sane")
