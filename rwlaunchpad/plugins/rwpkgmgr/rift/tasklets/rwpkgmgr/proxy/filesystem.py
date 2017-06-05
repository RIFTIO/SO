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

import asyncio
import os

import rift.package.store as store
import rift.package.package

from .base import AbstractPackageManagerProxy


class UnknownPackageType(Exception):
    pass


class FileSystemProxy(AbstractPackageManagerProxy):
    """Proxy for Filesystem based store.
    """
    PACKAGE_TYPE_MAP = {"vnfd": store.VnfdPackageFilesystemStore,
                        "nsd": store.NsdPackageFilesystemStore}

    # Refer: https://confluence.riftio.com/display/ATG/Launchpad+package+formats
    SCHEMA = {
        "nsd": ["icons", "ns_config", "scripts", "vnf_config"],
        "vnfd": ["charms", "cloud_init", "icons", "images", "scripts"]
    }

    SCHEMA_TO_PERMS = {'scripts': 0o777}

    def __init__(self, loop, log):
        self.loop = loop
        self.log = log
        self.store_cache = {}

    def _get_store(self, package_type):
        store_cls = self.PACKAGE_TYPE_MAP[package_type]
        store = self.store_cache.setdefault(package_type, store_cls(self.log))

        return store

    @asyncio.coroutine
    def endpoint(self, package_type, package_id):
        package_type = package_type.lower()
        if package_type not in self.PACKAGE_TYPE_MAP:
            raise UnknownPackageType()

        store = self._get_store(package_type)

        package = store._get_package_dir(package_id)
        rel_path = os.path.relpath(package, start=store.root_dir)

        url = "https://127.0.0.1:4567/api/package/{}/{}".format(package_type, rel_path)

        return url

    @asyncio.coroutine
    def schema(self, package_type):
        package_type = package_type.lower()
        if package_type not in self.PACKAGE_TYPE_MAP:
            raise UnknownPackageType()

        return self.SCHEMA[package_type]

    def package_file_add(self, new_file, package_type, package_id, package_path, package_file_type):
        # Get the schema from thr package path
        # the first part will always be the vnfd/nsd name
        mode = 0o664

        # for files other than README, create the package path from the asset type, e.g. icons/icon1.png
        # for README files, strip off any leading '/' 
        package_path = package_file_type + "/" + package_path \
            if package_file_type != "readme" else package_path.strip('/')
        components = package_path.split("/")
        if len(components) > 2:
            schema = components[1]
            mode = self.SCHEMA_TO_PERMS.get(schema, mode)

        # Fetch the package object
        package_type = package_type.lower()
        store = self._get_store(package_type)
        package = store.get_package(package_id)

        # Construct abs path of the destination obj
        path = store._get_package_dir(package_id)
        dest_file = os.path.join(path, package.prefix, package_path)

        try:
            package.insert_file(new_file, dest_file, package_path, mode=mode)
        except rift.package.package.PackageAppendError as e:
            self.log.exception(e)
            return False

        self.log.debug("File insertion complete at {}".format(dest_file))
        return True

    def package_file_delete(self, package_type, package_id, package_path, package_file_type):
        package_type = package_type.lower()
        store = self._get_store(package_type)
        package = store.get_package(package_id)

        # for files other than README, create the package path from the asset type
        package_path = package_file_type + "/" + package_path \
            if package_file_type != "readme" else package_path

        # package_path has to be relative, so strip off the starting slash if
        # provided incorrectly.
        if package_path[0] == "/":
            package_path = package_path[1:]

        # Construct abs path of the destination obj
        path = store._get_package_dir(package_id)
        dest_file = os.path.join(path, package.prefix, package_path)

        try:
            package.delete_file(dest_file, package_path)
        except rift.package.package.PackageAppendError as e:
            self.log.exception(e)
            return False

        return True

