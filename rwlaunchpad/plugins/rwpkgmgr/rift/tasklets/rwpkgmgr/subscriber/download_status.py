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
# Author(s): Varun Prasad
# Creation Date: 09/25/2016
# 

import os
import io
import shutil

import rift.mano.dts as mano_dts
import rift.package.package as package 
import rift.package.store as store 
import rift.package.convert as convert

from gi.repository import (
    RwYang,
    NsdYang,
    RwNsdYang,
    VnfdYang,
    RwVnfdYang,
    RwDts
)

class DownloadStatusSubscriber(mano_dts.AbstractOpdataSubscriber):

    def __init__(self, log, dts, loop, callback):
        super().__init__(log, dts, loop, callback)
    
    def get_xpath(self): 
        return ("D,/rw-pkg-mgmt:download-jobs/rw-pkg-mgmt:job")

class VnfdStatusSubscriber(DownloadStatusSubscriber): 
    DOWNLOAD_DIR = store.VnfdPackageFilesystemStore.DEFAULT_ROOT_DIR
    MODULE_DESC = 'vnfd rw-vnfd'.split()
    DESC_TYPE = 'vnfd'
    
    def __init__(self, log, dts, loop):
        super().__init__(log, dts, loop, self.on_change)
        self.subscriber = mano_dts.VnfdCatalogSubscriber(log, dts, loop)

    def on_change(self, msg, action): 
        log_msg = "1. Vnfd called w/ msg attributes: {} id {} name {} action: {}".format(repr(msg), msg.id, msg.name, repr(action))
        self.log.debug(log_msg)
        if action == RwDts.QueryAction.UPDATE:
            actionCreate(self, msg)
        else:
            self.log.debug("VnfdStatusSubscriber: No action for {}".format(repr(action)))
            pass

    def get_xpath(self): 
        return self.subscriber.get_xpath() 


class NsdStatusSubscriber(DownloadStatusSubscriber): 
    DOWNLOAD_DIR = store.NsdPackageFilesystemStore.DEFAULT_ROOT_DIR
    MODULE_DESC = 'nsd rw-nsd'.split()
    DESC_TYPE = 'nsd'
    
    def __init__(self, log, dts, loop):
        super().__init__(log, dts, loop, self.on_change)
        self.subscriber = mano_dts.NsdCatalogSubscriber(log, dts, loop)

    def on_change(self, msg, action): 
        log_msg = "1. Nsd called w/ msg attributes: {} id {} name {} action: {}".format(repr(msg), msg.id, msg.name, repr(action))
        self.log.debug(log_msg)
        if action == RwDts.QueryAction.UPDATE:
            actionCreate(self, msg)
        else:
            self.log.debug("NsdStatusSubscriber: No action for {}".format(repr(action)))
            pass

    def get_xpath(self): 
        return self.subscriber.get_xpath() 


def actionCreate(descriptor, msg): 
    ''' Create folder structure if it doesn't exist: id/vnf name OR id/nsd name  
    Serialize the Vnfd/Nsd object to yaml and store yaml file in the created folder.
    '''

    desc_name = msg.name if msg.name else ""
    download_dir = os.path.join(descriptor.DOWNLOAD_DIR, msg.id)

    # If a download dir is present with contents, then we know it has been created in the 
    # upload path. 
    if os.path.exists(download_dir) and os.listdir(download_dir):
        descriptor.log.debug("Skpping folder creation, {} already present".format(download_dir))
        return
    else: 
        # Folder structure is based on top-level package-id directory
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
            descriptor.log.debug("Created directory {}".format(download_dir))

            model = RwYang.Model.create_libncx()
            for module in descriptor.MODULE_DESC: model.load_module(module)

            yaml_path = "{base}/{name}_{type}.yaml".format(base=download_dir, name=msg.name, type=descriptor.DESC_TYPE) 
            with open(yaml_path,"w") as fh:
                fh.write(msg.to_yaml(model))

