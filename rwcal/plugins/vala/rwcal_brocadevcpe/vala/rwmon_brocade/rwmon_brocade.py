
# STANDARD_RIFT_IO_COPYRIGHT
import time
import logging

from gi.repository import (
    GObject,
    RwMon,
    RwTypes,
    RwmonYang as rwmon,
    )

import rw_status
import rwlogger
import rift.rwcal.brocadevcpe.brocadevcpe_drv as brocadevcpe_drv

logger = logging.getLogger('rwmon.brocade')


rwstatus = rw_status.rwstatus_from_exc_map({
    IndexError: RwTypes.RwStatus.NOTFOUND,
    KeyError: RwTypes.RwStatus.NOTFOUND,
    })


class BrocadeImpl(object):

    def nfvi_vcpu_metrics(self, account, vm_id):
        return rwmon.NfviMetrics_Vcpu()

    def nfvi_memory_metrics(self, account, vm_id):
        return rwmon.NfviMetrics_Memory()

    def nfvi_storage_metrics(self, account, vm_id):
        return rwmon.NfviMetrics_Storage()

    def nfvi_metrics_available(self, account):
        return True

    def alarm_create(self, account, vim_id, alarm):
        pass

    def alarm_update(self, account, alarm):
        pass

    def alarm_delete(self, account, alarm_id):
        pass

    def alarm_list(self, account):
        return list()


class BrocadeMonitoringPlugin(GObject.Object, RwMon.Monitoring):
    def __init__(self):
        GObject.Object.__init__(self)
        # More like null implementation / defaults.
        self._impl = BrocadeImpl()
        self._driver_class = brocadevcpe_drv.BrocadeVcpeDriver
        self._driver = None


    def _get_driver(self, account):
        if not self._driver:
            self._driver = self._driver_class(
                    log = logger,
                    host = account.prop_cloud1.host,
                    username  = account.prop_cloud1.username,
                    password = account.prop_cloud1.password,
                    mgmt_network = account.prop_cloud1.mgmt_network
                  )

        return self._driver

    @rwstatus
    def do_init(self, rwlog_ctx):
        if not any(isinstance(h, rwlogger.RwLogger) for h in logger.handlers):
            logger.addHandler(
                rwlogger.RwLogger(
                    category="rw-monitor-log",
                    subcategory="brocade",
                    log_hdl=rwlog_ctx,
                )
            )

    @rwstatus(ret_on_failure=[None])
    def do_nfvi_metrics(self, account, vm_id):
        try:
            sample = self._get_driver(account).nfvi_metrics(vm_id)

            metrics = rwmon.NfviMetrics()
            if sample is None:
                return metrics

            vcpu = sample.cpu_time
            memory = int(sample.memory_current / 1024)  # convert to MB

#             metrics.vcpu.utilization = vcpu
            metrics.memory.used = memory
            metrics.timestamp = time.time()

            return metrics
        except Exception as e:
            logger.exception(e)

    @rwstatus
    def do_nfvi_vcpu_metrics(self, account, vm_id):
        return self._impl.nfvi_vcpu_metrics(account, vm_id)

    @rwstatus
    def do_nfvi_memory_metrics(self, account, vm_id):
        return self._impl.nfvi_memory_metrics(account, vm_id)

    @rwstatus
    def do_nfvi_storage_metrics(self, account, vm_id):
        return self._impl.nfvi_storage_metrics(account, vm_id)

    @rwstatus
    def do_nfvi_metrics_available(self, account):
        return True

    @rwstatus(ret_on_failure=[None])
    def do_alarm_create(self, account, vim_id, alarm):
        return self._impl.alarm_create(account, vim_id, alarm)

    @rwstatus(ret_on_failure=[None])
    def do_alarm_update(self, account, alarm):
        return self._impl.alarm_update(account, alarm)

    @rwstatus(ret_on_failure=[None])
    def do_alarm_delete(self, account, alarm_id):
        return self._impl.alarm_delete(account, alarm_id)

    @rwstatus(ret_on_failure=[None])
    def do_alarm_list(self, account):
        return self._impl.alarm_list(account)

    def set_impl(self, impl):
        self._impl = impl
