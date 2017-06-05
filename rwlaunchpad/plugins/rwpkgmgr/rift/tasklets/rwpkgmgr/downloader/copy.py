# 
#   Copyright 2017 RIFT.IO Inc
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
#   Author(s): Nandan Sinha
#

import os
import uuid
import shutil 
import enum

import gi
gi.require_version('RwVnfdYang', '1.0')
gi.require_version('RwNsdYang', '1.0')
from gi.repository import (
    RwYang, 
    NsdYang,
    VnfdYang,
    RwVnfdYang,
    RwNsdYang,
    RwPkgMgmtYang
)

class PackageCopyError(Exception): 
    pass

class CopyStatus(enum.Enum):
    UNINITIATED = 0
    STARTED = 1
    IN_PROGRESS = 2
    COMPLETED = 3
    FAILED = 4
    CANCELLED = 5

TaskStatus = RwPkgMgmtYang.TaskStatus

class CopyMeta:
    STATUS_MAP = {
        CopyStatus.STARTED: TaskStatus.QUEUED.value_nick.upper(),
        CopyStatus.UNINITIATED: TaskStatus.QUEUED.value_nick.upper(),
        CopyStatus.IN_PROGRESS: TaskStatus.IN_PROGRESS.value_nick.upper(),
        CopyStatus.COMPLETED: TaskStatus.COMPLETED.value_nick.upper(),
        CopyStatus.FAILED: TaskStatus.FAILED.value_nick.upper(),
        CopyStatus.CANCELLED: TaskStatus.CANCELLED.value_nick.upper()
        }

    def __init__(self, transaction_id):
        self.transaction_id = transaction_id
        self.state = CopyStatus.UNINITIATED

    def set_state(self, state):
        self.state = state

    def as_dict(self): 
        return self.__dict__

    def to_yang(self):
        job = RwPkgMgmtYang.CopyJob.from_dict({
            "transaction_id": self.transaction_id, 
            "status": CopyMeta.STATUS_MAP[self.state]
            })
        return job

class PackageFileCopier:
    DESCRIPTOR_MAP = {
            "vnfd": (RwVnfdYang.YangData_Vnfd_VnfdCatalog_Vnfd, 'vnfd rw-vnfd'), 
            "nsd" : (RwNsdYang.YangData_Nsd_NsdCatalog_Nsd, 'nsd rw-nsd') 
            }

    @classmethod
    def from_rpc_input(cls, rpc_input, proxy, log=None): 
        return cls(
                rpc_input.package_id,
                rpc_input.package_type, 
                rpc_input.package_name,
                proxy = proxy,
                log=log)

    def __init__(self, 
            pkg_id, 
            pkg_type, 
            pkg_name, 
            proxy, 
            log):
        self.src_package_id = pkg_id
        self.package_type = pkg_type.lower()
        self.dest_package_name = pkg_name
        self.dest_package_id = str(uuid.uuid4())
        self.transaction_id = str(uuid.uuid4())
        self.proxy = proxy
        self.log = log
        self.meta = CopyMeta(self.transaction_id)
        self.src_package = None
        self.dest_desc_msg = None

    # Start of delegate calls
    def call_delegate(self, event):
        if not self.delegate:
            return
        
        # Send out the descriptor message to be posted on success
        # Otherwise send out the CopyJob yang conversion from meta object.
        if event == "on_download_succeeded":
            getattr(self.delegate, event)(self.dest_desc_msg)
        else:
            getattr(self.delegate, event)(self.meta.to_yang())

    def _copy_tree(self):
        """
        Locate directory tree of the source descriptor folder. 
        Copy directory tree to destination descriptor folder.  

        """
        self.copy_progress()

        store = self.proxy._get_store(self.package_type)
        src_path = store._get_package_dir(self.src_package_id)
        self.src_package = store.get_package(self.src_package_id) 

        self.dest_copy_path = os.path.join(
                store.DEFAULT_ROOT_DIR, 
                self.dest_package_id) 
        self.log.debug("Copying contents from {src} to {dest}".
                format(src=src_path, dest=self.dest_copy_path))

        shutil.copytree(src_path, self.dest_copy_path)

    def _create_descriptor_file(self):
        """ Update descriptor file for the newly copied descriptor catalog.
        Use the existing descriptor file to create a descriptor proto gi object,
        change some identifiers, and create a new descriptor yaml file from it.

        """
        src_desc_file = self.src_package.descriptor_file
        src_desc_contents = self.src_package.descriptor_msg.as_dict()
        src_desc_contents.update(
                id =self.dest_package_id, 
                name = self.dest_package_name,
                short_name = self.dest_package_name
                )

        desc_cls, modules = PackageFileCopier.DESCRIPTOR_MAP[self.package_type]
        self.dest_desc_msg = desc_cls.from_dict(src_desc_contents)
        dest_desc_path = os.path.join(self.dest_copy_path, 
                "{pkg_name}_{pkg_type}.yaml".format(pkg_name=self.dest_package_name, pkg_type=self.package_type))
        model = RwYang.Model.create_libncx()
        for module in modules.split():
            model.load_module(module) 

        with open(dest_desc_path, "w") as fh:
            fh.write(self.dest_desc_msg.to_yaml(model))

        copied_desc_file = os.path.join(self.dest_copy_path, os.path.basename(src_desc_file))
        if os.path.exists(copied_desc_file):
            self.log.debug("Deleting copied yaml from old source %s" % (copied_desc_file))
            os.remove(copied_desc_file)

    def copy(self):
        try:
            if self.package_type not in PackageFileCopier.DESCRIPTOR_MAP: 
                raise PackageCopyError("Package type {} not currently supported for copy operations".format(self.package_type))

            self._copy_tree()
            self._create_descriptor_file()
            self.copy_succeeded()

        except Exception as e: 
            self.log.exception(str(e))
            self.copy_failed()

        self.copy_finished()

    def copy_failed(self):
        self.meta.set_state(CopyStatus.FAILED)
        self.call_delegate("on_download_failed")

    def copy_progress(self): 
        self.meta.set_state(CopyStatus.IN_PROGRESS)
        self.call_delegate("on_download_progress")

    def copy_succeeded(self):
        self.meta.set_state(CopyStatus.COMPLETED)
        self.call_delegate("on_download_succeeded")

    def copy_finished(self): 
        self.call_delegate("on_download_finished") 

