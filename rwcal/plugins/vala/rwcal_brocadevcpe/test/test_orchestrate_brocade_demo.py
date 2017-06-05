#!/usr/bin/env python
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

import requests
import logging
import sys
import os
import json
import shlex
import argparse
import subprocess
import time
import uuid
from requests.auth import HTTPBasicAuth
from requests import Request, Session

requests.packages.urllib3.disable_warnings()
logging.basicConfig(level=logging.DEBUG)

VCPE_ACCOUNT_TEMPLATE = '''{{  
      "account":[  
         {{  
            "name":"VCPE{cloud_ip}",
            "account-type":"prop_cloud1",
            "prop_cloud1":{{  
               "host":"{cloud_ip}",
               "dynamic-flavor-support":"true",
               "plugin-name":"rwcal_propcloud1",
               "username":"vyatta",
               "password":"vyatta",
               "mgmt-network": "mgmt",
               "wan-interface": "dp0s2f1",
               "public-ip-pool": "10.66.26.0/24"
            }}
         }}
      ]
}}
'''

LAUNCHPAD_URL = "https://{lp_ip}"
LAUNCHPAD_CONFIG_URL = LAUNCHPAD_URL + ":8008"
LAUNCHPAD_CLOUD_CONFIG_URL = LAUNCHPAD_CONFIG_URL + "/api/config/cloud/account/{cloud_key}"
LAUNCHPAD_NSD_URL = LAUNCHPAD_CONFIG_URL + "/api/config/nsd-catalog/nsd/{nsd_id}"
LAUNCHPAD_VNFD_URL = LAUNCHPAD_CONFIG_URL + "/api/config/vnfd-catalog/vnfd/{vnfd_id}"
LAUNCHPAD_NSINST_URL = LAUNCHPAD_CONFIG_URL + "/api/config/ns-instance-config"
LAUNCHPAD_NSR_URL = LAUNCHPAD_CONFIG_URL + "/api/config/ns-instance-config/nsr/{nsr_id}"
LAUNCHPAD_VNFD_CATALOG_URL = LAUNCHPAD_CONFIG_URL + "/api/config/vnfd-catalog?deep"
LAUNCHPAD_NSD_CATALOG_URL = LAUNCHPAD_CONFIG_URL + "/api/config/nsd-catalog?deep"

RIFT_TG_VNFD_PKG = "/net/gluon/localdisk/rchamart/vcpebug/.build/modules/core/enablement/src/core_enablement-build/vnf/descriptors/scripts/multivm_vnfd/vcpe_demo_trafgen_vnfd.tar.gz"
RIVERBED_STEELHEAD_VNFD_PKG = "/net/gluon/localdisk/rchamart/vcpebug/.build/modules/core/enablement/src/core_enablement-build/vnf/descriptors/scripts/multivm_vnfd/vcpe_demo_wan_optimizer_vnfd.tar.gz"
RIFT_DEMO_NS_PKG = "/net/gluon/localdisk/rchamart/vcpebug/.build/modules/core/enablement/src/core_enablement-build/vnf/descriptors/scripts/multivm_nsd/vcpe_demo_multivm_nsd.tar.gz"


NSR_TEMPLATE = '''
{{
  "nsr": [
    {{
      "id": "{nsr_uuid}",
      "name": "Test1",
      "short-name": "Test",
      "description": "A demo for VCPE",
      "admin-status": "ENABLED",
      "cloud-account": "VCPE{cloud_ip}",
      "nsd": {nsd_data}
    }}
  ]
}}
'''

logger = logging.getLogger('rift.rest')
      
class RiftCloudResources(object):
    """
      A base class to manage multiple clouds
    """
    def __init__(self, sitetype, controller, tenant, lp_sess):
        self.lp_sess = lp_sess
        self.sitetype = sitetype
        self.controller = controller
        self.tenant = tenant
        self.tenant_id = None

    def configure_cloud_account(self, name):
        raise NotImplementedError

    def delete_cloud_account(self, launchpad_ip):
        logger.info("Deleting cloud account for cloud IP %s", self.controller)
        key = "VCPE" + self.controller
        lp_config_url = LAUNCHPAD_CLOUD_CONFIG_URL.format(lp_ip=launchpad_ip, cloud_key=key)
        logger.debug("lp_config_url %s", lp_config_url)
        try:
           resp = self.lp_sess.delete(lp_config_url, verify=False)
           resp.raise_for_status()
        except requests.exceptions.RequestException as e:
           msg = "Got HTTP error delete to url {}: {}".format(
                      lp_config_url,
                      str(e),
                      )
           logger.error(msg)
           return "success"
       
        return "success"

    def get_tenant_id(self, name):
        raise NotImplementedError

class RiftVcpeCloud(RiftCloudResources):
    """
      An inherited class to manage Brocade VCPE
    """
    def __init__(self, controller, tenant, lp_sess):
        super().__init__("vcpe", controller, tenant, lp_sess)

    def configure_cloud_account(self, launchpad_ip):
        logger.info("Configuring cloud account for cloud IP %s", self.controller)
        key = "VCPE" + self.controller
        lp_config_url = LAUNCHPAD_CLOUD_CONFIG_URL.format(lp_ip=launchpad_ip, cloud_key=key)
        logger.info("lp_config_url %s", lp_config_url)
        try:
           cloud_account = VCPE_ACCOUNT_TEMPLATE.format(cloud_ip = self.controller)
           logger.debug("Cloud details %s", cloud_account)
           resp = self.lp_sess.post(lp_config_url, verify=False, data=cloud_account)
           resp.raise_for_status()
        except requests.exceptions.RequestException as e:
           msg = "Got HTTP error post to url {}: {}".format(
                      lp_config_url,
                      str(e),
                      )
           logger.error(msg)
           return "failure"
       
        return "success"



class PackageOnboardError(Exception):
    pass
          
class RiftCatalog(object):
    def __init__(self, launchpad_ip, lp_sess):
        self._lp_ip = launchpad_ip
        self._lp_sess = lp_sess
        self.upload_sess = requests.Session()
        self.upload_sess.auth = requests.auth.HTTPBasicAuth( 'admin', 'admin')

    def upload_package(self, package_file):
        logger.info("Uploading package file %s", package_file)
        files = {'descriptor': open(package_file, 'rb')}
        url = 'https://{host}:4567/api/upload'.format(host=self._lp_ip)
        logger.debug("Upload URL %s", url)
        r = self.upload_sess.post(url, files=files, verify=False)
        print(r.text)
        json_out = r.json()
        transaction_id = json_out["transaction_id"]
      
        return transaction_id
          
    def wait_onboard_transaction_finished(self, transaction_id, timeout_secs=600):
        logger.info("Waiting for onboard transaction id  %s to complete",
                  transaction_id)
        start_time = time.time()
        while (time.time() - start_time) < timeout_secs:
          r = self._lp_sess.get(
                  'https://{host}:4567/api/upload/{t_id}/state'.format(
                      host=self._lp_ip, t_id=transaction_id
                      ),
                   verify=False
                  )
          state = r.json()
          if state["status"] == "pending":
              time.sleep(1)
              continue
  
          elif state["status"] == "success":
              logger.info("Descriptor onboard was successful")
              return "success"
  
          else:
              raise PackageOnboardError(state)
  
        if state["status"] != "success":
          raise PackageOnboardError(state) 

    def delete_vnfd(self, key):
       logger.info("Deleting VNFD..")
       vnfd_url = LAUNCHPAD_VNFD_URL.format(lp_ip = self._lp_ip, vnfd_id=key)
       logger.debug("vnfd_url %s", vnfd_url)
       try:
          resp = self._lp_sess.delete(vnfd_url, verify=False)
          resp.raise_for_status()
       except requests.exceptions.RequestException as e:
          msg = "Got HTTP error delete to url {}: {}".format(
                        vnfd_url,
                        str(e),
                        )
          logger.error(msg)
          return "failure"
  
       return "success"

    def delete_all_vnfds(self):
       logger.info("Deleting all VNFDs ..")
       try: 
          url = LAUNCHPAD_VNFD_CATALOG_URL.format(lp_ip=self._lp_ip)
          resp = self._lp_sess.get( url, verify=False)
          resp.raise_for_status()
       except requests.exceptions.RequestException as e:
          msg = "Got HTTP error for url {} when request {}".format(url, str(e))
          logger.error(msg)
    
       if resp.status_code == 204:
          return "success"
       data = resp.json()
       logger.debug("VNFD catalog : %s", data)
       if "vnfd" not in data["vnfd:vnfd-catalog"]:
          return "success"
  
       for vnfd in data["vnfd:vnfd-catalog"]["vnfd"]:
          self.delete_vnfd(vnfd["id"])
       return "success"
  
    def delete_nsd(self, key):
       logger.info("Deleting NSD..")
       nsd_url = LAUNCHPAD_NSD_URL.format(lp_ip = self._lp_ip, nsd_id=key)
       logger.debug("nsd_url %s", nsd_url)
       try:
          resp = self._lp_sess.delete(nsd_url, verify=False)
          resp.raise_for_status()
       except requests.exceptions.RequestException as e:
          msg = "Got HTTP error delete to url {}: {}".format(
                        nsd_url,
                        str(e),
                        )
          logger.error(msg)
          return "failure"
  
       return "success"

    def get_nsd_data(self, name):
       logger.info("Getting NSD data..")
       try: 
          url = LAUNCHPAD_NSD_CATALOG_URL.format(lp_ip=self._lp_ip)
          resp = self._lp_sess.get( url, verify=False)
          resp.raise_for_status()
       except requests.exceptions.RequestException as e:
          msg = "Got HTTP error for url {} when request {}".format(url, str(e))
          logger.error(msg)
    
       if resp.status_code == 204:
          return None
       data = resp.json()
       logger.debug("NSD catalog : %s", data)
       if "nsd" not in data["nsd:nsd-catalog"]:
          return None
  
       for nsd in data["nsd:nsd-catalog"]["nsd"]:
          if name in nsd["name"]:
             return nsd
       return None

    def delete_all_nsds(self):
       logger.info("Deleting all NSDs..")
       try: 
          url = LAUNCHPAD_NSD_CATALOG_URL.format(lp_ip=self._lp_ip)
          resp = self._lp_sess.get( url, verify=False)
          resp.raise_for_status()
       except requests.exceptions.RequestException as e:
          msg = "Got HTTP error for url {} when request {}".format(url, str(e))
          logger.error(msg)
    
       if resp.status_code == 204:
          return "success"
       data = resp.json()
       logger.debug("NSD catalog : %s", data)
       if "nsd" not in data["nsd:nsd-catalog"]:
          return "success"
  
       for nsd in data["nsd:nsd-catalog"]["nsd"]:
          self.delete_nsd(nsd["id"])
       return "success"


class RiftLaunchpad(object):
    def __init__(self, lp_ip):
       self._lp_ip = lp_ip
       self.cloud_list = []
       self.lp_sess = requests.Session()
       self.lp_sess.headers.update({'Content-type': 'application/vnd.yang.data+json'})
       self.lp_sess.headers.update({'Accept': 'json'})
       self.lp_sess.auth = requests.auth.HTTPBasicAuth( 'admin', 'admin')
       self.catalog = RiftCatalog(lp_ip, self.lp_sess)

    def add_cloud(self, sitetype, cloud_ip):
       vcpecloud = RiftVcpeCloud(cloud_ip, "demo", self.lp_sess)
       return vcpecloud

    def instantiate_nsr(self, vcpecloud):
       logger.info("Instantiating NSR for NSD vCPE_DEMO_nsd..")
       nsd_data = self.catalog.get_nsd_data("vCPE_DEMO_nsd")
       if nsd_data is None:
          return "failure"
       nsd_id = nsd_data["id"]
       nsr_uuid = str(uuid.uuid1())
       nsr_url = LAUNCHPAD_NSR_URL.format(lp_ip = self._lp_ip, nsr_id=nsr_uuid)
       logger.debug("nsr_url %s", nsr_url)
       nsr_data = NSR_TEMPLATE.format(nsd_id=nsd_id, nsr_uuid=nsr_uuid, cloud_ip=vcpecloud.controller, nsd_data=json.dumps(nsd_data))
       logger.debug("NSR details for instantiation %s", nsr_data)
       try:
          resp = self.lp_sess.post(nsr_url, verify=False, data=nsr_data) 
          resp.raise_for_status()
       except requests.exceptions.RequestException as e:
          msg = "Got HTTP error post to url {}: {}".format(
                      nsr_url,
                      str(e),
                      )
          logger.error(msg)
          return "failure"
       
       return "success"

    def get_nsr_data(self, nsd_name):
       logger.info("Get NSR data..")
  
       try: 
          url = LAUNCHPAD_NSINST_URL.format(lp_ip=self._lp_ip)
          resp = self.lp_sess.get(url, verify=False) 
          resp.raise_for_status()
       except requests.exceptions.RequestException as e:
          msg = "Got HTTP error for url {} when request {}".format(url, str(e))
          logger.error(msg)
  
       data = resp.json()
       logger.debug("NSR config : %s", data)
       if "nsr" not in data["nsr:ns-instance-config"]:
           return None

       for nsr in data["nsr:ns-instance-config"]["nsr"]:
           if (nsr["nsd"]["name"].endswith(nsd_name)):
               return nsr["id"]

    def delete_nsr(self, cloud_ip):
       logger.info("Getting NSR ID for Test1")
       nsr_uuid = self.get_nsr_data("vCPE_DEMO_nsd")
       if nsr_uuid is None:
           return "success"
       logger.info("Deleting NSR for Test1")
       nsr_url = LAUNCHPAD_NSR_URL.format(lp_ip = self._lp_ip, nsr_id=nsr_uuid)
       logger.debug("nsr_url %s", nsr_url)
       try:
          resp = self.lp_sess.delete(nsr_url, verify=False) 
          resp.raise_for_status()
       except requests.exceptions.RequestException as e:
          msg = "Got HTTP error delete to url {}: {}".format(
                      nsr_url,
                      str(e),
                      )
          logger.error(msg)
          return "failure"
       
       logger.info("Waiting for 60 secs for NSR to be cleaned up")
       time.sleep(60)
       logger.info("Waiting another 60 secs for NSR to be cleaned up")
       time.sleep(60)
       return "success"

def main(argv=sys.argv[1:]):
    parser = argparse.ArgumentParser("Perform resource orchestration for Brocade VCPE demo using Rift.IO orchestrator")
    parser.add_argument('-l', '--launchpad', help="IP address of Riftware launchpad" )
    parser.add_argument('-c', '--cloud_ip', help="IP address of cloud platform")
    parser.add_argument('--cleanup', action='store_true', help="Cleanup all resources for this NSR")
  
    args = parser.parse_args()
    launchpad_ip = args.launchpad
    cloud_ip = args.cloud_ip
    cleanup = args.cleanup
    lpad = RiftLaunchpad(launchpad_ip)
    vcpecloud = lpad.add_cloud("vcpe", cloud_ip)

    if cleanup is True:
       status = lpad.delete_nsr(cloud_ip)
       assert(status == "success")
       status = lpad.catalog.delete_all_nsds()
       assert(status == "success")
       status = lpad.catalog.delete_all_vnfds()
       assert(status == "success")
       status = vcpecloud.delete_cloud_account(launchpad_ip)
       assert(status == "success")
       return

    status = vcpecloud.configure_cloud_account(launchpad_ip)
    assert(status == "success")
    tid = lpad.catalog.upload_package(RIFT_TG_VNFD_PKG)
    status = lpad.catalog.wait_onboard_transaction_finished(tid)
    assert(status == "success")
    tid = lpad.catalog.upload_package(RIVERBED_STEELHEAD_VNFD_PKG)
    status = lpad.catalog.wait_onboard_transaction_finished(tid)
    assert(status == "success")
    tid = lpad.catalog.upload_package(RIFT_DEMO_NS_PKG)
    status = lpad.catalog.wait_onboard_transaction_finished(tid)
    assert(status == "success")
    status = lpad.instantiate_nsr(vcpecloud)
    assert(status == "success")
  
if __name__ == "__main__":
    main()



