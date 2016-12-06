
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

import collections
import os
import threading
import uuid
import zlib

import tornado
import tornado.escape
import tornado.ioloop
import tornado.web
import tornado.httputil
import tornadostreamform.multipart_streamer as multipart_streamer

import requests

# disable unsigned certificate warning
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

import gi
gi.require_version('RwLaunchpadYang', '1.0')
gi.require_version('NsdYang', '1.0')
gi.require_version('VnfdYang', '1.0')

from gi.repository import (
        NsdYang,
        VnfdYang,
        )
import rift.mano.cloud

import rift.package.charm
import rift.package.checksums
import rift.package.config
import rift.package.convert
import rift.package.icon
import rift.package.package
import rift.package.script
import rift.package.store

from . import (
        export,
        extract,
        image,
        message,
        onboard,
        state,
        )

from .message import (
        MessageException,

        # Onboard Error Messages
        OnboardChecksumMismatch,
        OnboardDescriptorError,
        OnboardDescriptorExistsError,
        OnboardDescriptorFormatError,
        OnboardError,
        OnboardExtractionError,
        OnboardImageUploadError,
        OnboardMissingContentBoundary,
        OnboardMissingContentType,
        OnboardMissingTerminalBoundary,
        OnboardUnreadableHeaders,
        OnboardUnreadablePackage,
        OnboardUnsupportedMediaType,

        # Onboard Status Messages
        OnboardDescriptorOnboard,
        OnboardFailure,
        OnboardImageUpload,
        OnboardPackageUpload,
        OnboardPackageValidation,
        OnboardStart,
        OnboardSuccess,


        # Update Error Messages
        UpdateChecksumMismatch,
        UpdateDescriptorError,
        UpdateDescriptorFormatError,
        UpdateError,
        UpdateExtractionError,
        UpdateImageUploadError,
        UpdateMissingContentBoundary,
        UpdateMissingContentType,
        UpdatePackageNotFoundError,
        UpdateUnreadableHeaders,
        UpdateUnreadablePackage,
        UpdateUnsupportedMediaType,

        # Update Status Messages
        UpdateDescriptorUpdate,
        UpdateDescriptorUpdated,
        UpdatePackageUpload,
        UpdateStart,
        UpdateSuccess,
        UpdateFailure,
        )

from .tosca import ExportTosca

MB = 1024 * 1024
GB = 1024 * MB

MAX_STREAMED_SIZE = 5 * GB


class HttpMessageError(Exception):
    def __init__(self, code, msg):
        self.code = code
        self.msg = msg


class GzipTemporaryFileStreamedPart(multipart_streamer.TemporaryFileStreamedPart):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Create a decompressor for gzip data to decompress on the fly during upload
        # http://stackoverflow.com/questions/2423866/python-decompressing-gzip-chunk-by-chunk
        self._decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)

    def feed(self, data):
        decompressed_data = self._decompressor.decompress(data)
        if decompressed_data:
            super().feed(decompressed_data)

    def finalize(self):
        # All data has arrived, flush the decompressor to get any last decompressed data
        decompressed_data = self._decompressor.flush()
        super().feed(decompressed_data)
        super().finalize()


class GzipMultiPartStreamer(multipart_streamer.MultiPartStreamer):
    """ This Multipart Streamer decompresses gzip files on the fly during multipart upload """

    @staticmethod
    def _get_descriptor_name_from_headers(headers):
        descriptor_filename = None

        for entry in headers:
            if entry["value"] != "form-data":
                continue

            form_data_params = entry["params"]
            if "name" in form_data_params:
                if form_data_params["name"] != "descriptor":
                    continue

                if "filename" not in form_data_params:
                    continue

                descriptor_filename = form_data_params["filename"]

        return descriptor_filename

    def create_part(self, headers):
        """ Create the StreamedPart subclass depending on the descriptor filename

        For gzipped descriptor packages, create a GzipTemporaryFileStreamedPart which
        can decompress the gzip while it's being streamed into the launchpad directely
        into a file.

        Returns:
            The descriptor filename
        """
        filename = GzipMultiPartStreamer._get_descriptor_name_from_headers(headers)
        if filename is None or not filename.endswith(".gz"):
            return multipart_streamer.TemporaryFileStreamedPart(self, headers)

        return GzipTemporaryFileStreamedPart(self, headers)


class RequestHandler(tornado.web.RequestHandler):
    def options(self, *args, **kargs):
        pass

    def set_default_headers(self):
        self.set_header('Access-Control-Allow-Origin', '*')
        self.set_header('Access-Control-Allow-Headers',
                        'Content-Type, Cache-Control, Accept, X-Requested-With, Authorization')
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, PUT, DELETE')


@tornado.web.stream_request_body
class StreamingUploadHandler(RequestHandler):
    def initialize(self, log, loop):
        """Initialize the handler

        Arguments:
            log  - the logger that this handler should use
            loop - the tasklets ioloop

        """
        self.transaction_id = str(uuid.uuid4())

        self.loop = loop
        self.log = self.application.get_logger(self.transaction_id)

        self.part_streamer = None

        self.log.debug('created handler (transaction_id = {})'.format(self.transaction_id))

    def msg_missing_content_type(self):
        raise NotImplementedError()

    def msg_unsupported_media_type(self):
        raise NotImplementedError()

    def msg_missing_content_boundary(self):
        raise NotImplementedError()

    def msg_start(self):
        raise NotImplementedError()

    def msg_success(self):
        raise NotImplementedError()

    def msg_failure(self):
        raise NotImplementedError()

    def msg_package_upload(self):
        raise NotImplementedError()

    @tornado.gen.coroutine
    def prepare(self):
        """Prepare the handler for a request

        The prepare function is the first part of a request transaction. It
        creates a temporary file that uploaded data can be written to.

        """
        if self.request.method != "POST":
            return

        self.request.connection.set_max_body_size(MAX_STREAMED_SIZE)

        self.log.message(self.msg_start())

        try:
            # Retrieve the content type and parameters from the request
            content_type = self.request.headers.get('content-type', None)
            if content_type is None:
                raise HttpMessageError(400, self.msg_missing_content_type())

            content_type, params = tornado.httputil._parse_header(content_type)

            if "multipart/form-data" != content_type.lower():
                raise HttpMessageError(415, self.msg_unsupported_media_type())

            if "boundary" not in params:
                raise HttpMessageError(400, self.msg_missing_content_boundary())

            # You can get the total request size from the headers.
            try:
                total = int(self.request.headers.get("Content-Length", "0"))
            except KeyError:
                self.log.warning("Content length header not found")
                # For any well formed browser request, Content-Length should have a value.
                total = 0

            # And here you create a streamer that will accept incoming data
            self.part_streamer = GzipMultiPartStreamer(total)

        except HttpMessageError as e:
            self.log.message(e.msg)
            self.log.message(self.msg_failure())

            raise tornado.web.HTTPError(e.code, e.msg.name)

        except Exception as e:
            self.log.exception(e)
            self.log.message(self.msg_failure())

    @tornado.gen.coroutine
    def data_received(self, chunk):
        """Write data to the current file

        Arguments:
            data - a chunk of data to write to file

        """

        """When a chunk of data is received, we forward it to the multipart streamer."""
        self.part_streamer.data_received(chunk)

    def post(self):
        """Handle a post request

        The function is called after any data associated with the body of the
        request has been received.

        """
        # You MUST call this to close the incoming stream.
        self.part_streamer.data_complete()

        desc_parts = self.part_streamer.get_parts_by_name("descriptor")
        if len(desc_parts) != 1:
            raise HttpMessageError(400, OnboardError("Descriptor option not found"))

        self.log.message(self.msg_package_upload())


class UploadHandler(StreamingUploadHandler):
    """
    This handler is used to upload archives that contain VNFDs, NSDs, and PNFDs
    to the launchpad. This is a streaming handler that writes uploaded archives
    to disk without loading them all into memory.
    """

    def msg_missing_content_type(self):
        return OnboardMissingContentType()

    def msg_unsupported_media_type(self):
        return OnboardUnsupportedMediaType()

    def msg_missing_content_boundary(self):
        return OnboardMissingContentBoundary()

    def msg_start(self):
        return OnboardStart()

    def msg_success(self):
        return OnboardSuccess()

    def msg_failure(self):
        return OnboardFailure()

    def msg_package_upload(self):
        return OnboardPackageUpload()

    def post(self):
        """Handle a post request

        The function is called after any data associated with the body of the
        request has been received.

        """
        try:
            super().post()
            self.application.onboard(
                    self.part_streamer,
                    self.transaction_id,
                    auth=self.request.headers.get('authorization', None),
                    )

            self.set_status(200)
            self.write(tornado.escape.json_encode({
                "transaction_id": self.transaction_id,
                    }))

        except Exception:
            self.log.exception("Upload POST failed")
            self.part_streamer.release_parts()
            raise


class UpdateHandler(StreamingUploadHandler):
    def msg_missing_content_type(self):
        return UpdateMissingContentType()

    def msg_unsupported_media_type(self):
        return UpdateUnsupportedMediaType()

    def msg_missing_content_boundary(self):
        return UpdateMissingContentBoundary()

    def msg_start(self):
        return UpdateStart()

    def msg_success(self):
        return UpdateSuccess()

    def msg_failure(self):
        return UpdateFailure()

    def msg_package_upload(self):
        return UpdatePackageUpload()

    def post(self):
        """Handle a post request

        The function is called after any data associated with the body of the
        request has been received.

        """
        try:
            super().post()

            self.application.update(
                    self.part_streamer,
                    self.transaction_id,
                    auth=self.request.headers.get('authorization', None),
                    )

            self.set_status(200)
            self.write(tornado.escape.json_encode({
                "transaction_id": self.transaction_id,
                    }))
        except Exception:
            self.log.exception("Upload POST failed")
            self.part_streamer.release_parts()
            raise


class UploadStateHandler(state.StateHandler):
    STARTED = OnboardStart
    SUCCESS = OnboardSuccess
    FAILURE = OnboardFailure


class UpdateStateHandler(state.StateHandler):
    STARTED = UpdateStart
    SUCCESS = UpdateSuccess
    FAILURE = UpdateFailure


class UpdatePackage(threading.Thread):
    def __init__(self, log, loop, part_streamer, auth,
                 onboarder, uploader, package_store_map):
        super().__init__()
        self.log = log
        self.loop = loop
        self.part_streamer = part_streamer
        self.auth = auth
        self.onboarder = onboarder
        self.uploader = uploader
        self.package_store_map = package_store_map

        self.io_loop = tornado.ioloop.IOLoop.current()

    def _update_package(self):
        # Extract package could return multiple packages if
        # the package is converted
        for pkg in self.extract_package():
            with pkg as temp_package:
                package_checksums = self.validate_package(temp_package)
                stored_package = self.update_package(temp_package)

                try:
                    self.extract_charms(temp_package)
                    self.extract_scripts(temp_package)
                    self.extract_configs(temp_package)
                    self.extract_icons(temp_package)

                    self.update_descriptors(temp_package)

                except Exception:
                    self.delete_stored_package(stored_package)
                    raise

                else:
                    self.upload_images(temp_package, package_checksums)

    def run(self):
        try:
            self._update_package()
            self.log.message(UpdateSuccess())

        except MessageException as e:
            self.log.message(e.msg)
            self.log.message(UpdateFailure())

        except Exception as e:
            self.log.exception(e)
            if str(e):
                self.log.message(UpdateError(str(e)))
            self.log.message(UpdateFailure())

    def extract_package(self):
        """Extract multipart message from tarball"""
        desc_part = self.part_streamer.get_parts_by_name("descriptor")[0]

        # Invoke the move API to prevent the part streamer from attempting
        # to clean up (the file backed package will do that itself)
        desc_part.move(desc_part.f_out.name)

        package_name = desc_part.get_filename()
        package_path = desc_part.f_out.name

        extractor = extract.UploadPackageExtractor(self.log)
        file_backed_packages = extractor.create_packages_from_upload(
                package_name, package_path
                )

        return file_backed_packages

    def get_package_store(self, package):
        return self.package_store_map[package.descriptor_type]

    def update_package(self, package):
        store = self.get_package_store(package)

        try:
            store.update_package(package)
        except rift.package.store.PackageNotFoundError as e:
            # If the package doesn't exist, then it is possible the descriptor was onboarded
            # out of band.  In that case, just store the package as is
            self.log.warning("Package not found, storing new package instead.")
            store.store_package(package)

        stored_package = store.get_package(package.descriptor_id)

        return stored_package

    def delete_stored_package(self, package):
        self.log.info("Deleting stored package: %s", package)
        store = self.get_package_store(package)
        try:
            store.delete_package(package.descriptor_id)
        except Exception as e:
            self.log.warning("Failed to delete package from store: %s", str(e))

    def upload_images(self, package, package_checksums):
        image_file_map = rift.package.image.get_package_image_files(package)
        name_hdl_map = {name: package.open(image_file_map[name]) for name in image_file_map}
        if not image_file_map:
            return

        try:
            for image_name, image_hdl in name_hdl_map.items():
                image_file = image_file_map[image_name]
                if image_file in package_checksums:
                    image_checksum = package_checksums[image_file]
                else:
                    self.log.warning("checksum not provided for image %s.  Calculating checksum",
                                     image_file)
                    image_checksum = rift.package.checksums.checksum(
                            package.open(image_file_map[image_name])
                            )
                try:
                    self.uploader.upload_image(image_name, image_checksum, image_hdl)
                    self.uploader.upload_image_to_cloud_accounts(image_name, image_checksum)

                except image.ImageUploadError as e:
                    self.log.exception("Failed to upload image: %s", image_name)
                    raise MessageException(OnboardImageUploadError(str(e))) from e

        finally:
            _ = [image_hdl.close() for image_hdl in name_hdl_map.values()]


    def extract_charms(self, package):
        try:
            charm_extractor = rift.package.charm.PackageCharmExtractor(self.log)
            charm_extractor.extract_charms(package)
        except rift.package.charm.CharmExtractionError as e:
            raise MessageException(UpdateExtractionError()) from e

    def extract_scripts(self, package):
        try:
            script_extractor = rift.package.script.PackageScriptExtractor(self.log)
            script_extractor.extract_scripts(package)
        except rift.package.script.ScriptExtractionError as e:
            raise MessageException(UpdateExtractionError()) from e

    def extract_configs(self, package):
        try:
            config_extractor = rift.package.config.PackageConfigExtractor(self.log)
            config_extractor.extract_configs(package)
        except rift.package.config.ConfigExtractionError as e:
            raise MessageException(UpdateExtractionError()) from e

    def extract_icons(self, package):
        try:
            icon_extractor = rift.package.icon.PackageIconExtractor(self.log)
            icon_extractor.extract_icons(package)
        except rift.package.icon.IconExtractionError as e:
            raise MessageException(UpdateExtractionError()) from e

    def validate_package(self, package):
        checksum_validator = rift.package.package.PackageChecksumValidator(self.log)

        try:
            file_checksums = checksum_validator.validate(package)
        except rift.package.package.PackageFileChecksumError as e:
            raise MessageException(UpdateChecksumMismatch(e.filename)) from e
        except rift.package.package.PackageValidationError as e:
            raise MessageException(UpdateUnreadablePackage()) from e

        return file_checksums

    def update_descriptors(self, package):
        descriptor_msg = package.descriptor_msg

        self.log.message(UpdateDescriptorUpdate())

        try:
            self.onboarder.update(descriptor_msg)
        except onboard.UpdateError as e:
            raise MessageException(UpdateDescriptorError(package.descriptor_file)) from e


class OnboardPackage(threading.Thread):
    def __init__(self, log, loop, part_streamer, auth,
                 onboarder, uploader, package_store_map):
        super().__init__()
        self.log = log
        self.loop = loop
        self.part_streamer = part_streamer
        self.auth = auth
        self.onboarder = onboarder
        self.uploader = uploader
        self.package_store_map = package_store_map

        self.io_loop = tornado.ioloop.IOLoop.current()

        self._is_vdu_if_type_e1000 = False

    def _onboard_package(self):
        # Extract package could return multiple packages if
        # the package is converted
        for pkg in self.extract_package():
            with pkg as temp_package:
                package_checksums = self.validate_package(temp_package)
                stored_package = self.store_package(temp_package)

                try:
                    self.extract_charms(temp_package)
                    self.extract_scripts(temp_package)
                    self.extract_configs(temp_package)
                    self.extract_icons(temp_package)

                    self.onboard_descriptors(temp_package)

                except Exception:
                    self.delete_stored_package(stored_package)
                    raise

                else:
                    self.upload_images(temp_package, package_checksums)

    def run(self):
        try:
            self._onboard_package()
            self.log.message(OnboardSuccess())

        except MessageException as e:
            self.log.message(e.msg)
            self.log.message(OnboardFailure())

        except Exception as e:
            self.log.exception(e)
            if str(e):
                self.log.message(OnboardError(str(e)))
            self.log.message(OnboardFailure())

        finally:
            self.part_streamer.release_parts()

    def extract_package(self):
        """Extract multipart message from tarball"""
        desc_part = self.part_streamer.get_parts_by_name("descriptor")[0]

        # Invoke the move API to prevent the part streamer from attempting
        # to clean up (the file backed package will do that itself)
        desc_part.move(desc_part.f_out.name)

        package_name = desc_part.get_filename()
        package_path = desc_part.f_out.name

        extractor = extract.UploadPackageExtractor(self.log)
        file_backed_packages = extractor.create_packages_from_upload(
                package_name, package_path
                )

        return file_backed_packages

    def get_package_store(self, package):
        return self.package_store_map[package.descriptor_type]

    def store_package(self, package):
        store = self.get_package_store(package)

        try:
            store.store_package(package)
        except rift.package.store.PackageExistsError as e:
            store.update_package(package)

        stored_package = store.get_package(package.descriptor_id)

        return stored_package

    def delete_stored_package(self, package):
        self.log.info("Deleting stored package: %s", package)
        store = self.get_package_store(package)
        try:
            store.delete_package(package.descriptor_id)
        except Exception as e:
            self.log.warning("Failed to delete package from store: %s", str(e))

    def upload_images(self, package, package_checksums):
        image_file_map = rift.package.image.get_package_image_files(package)
        if not image_file_map:
            return

        name_hdl_map = {name: package.open(image_file_map[name]) for name in image_file_map}
        try:
            for image_name, image_hdl in name_hdl_map.items():
                image_file = image_file_map[image_name]
                if image_file in package_checksums:
                    image_checksum = package_checksums[image_file]
                else:
                    self.log.warning("checksum not provided for image %s.  Calculating checksum",
                                     image_file)
                    image_checksum = rift.package.checksums.checksum(
                            package.open(image_file_map[image_name])
                            )
                try:
                    set_image_property = {}
                    if self._is_vdu_if_type_e1000:
                        set_image_property['hw_vif_model'] = 'e1000'

                    self.uploader.upload_image(image_name, image_checksum, image_hdl, set_image_property)
                    self.uploader.upload_image_to_cloud_accounts(image_name, image_checksum)

                except image.ImageUploadError as e:
                    raise MessageException(OnboardImageUploadError(str(e))) from e

        finally:
            _ = [image_hdl.close() for image_hdl in name_hdl_map.values()]

    def extract_charms(self, package):
        try:
            charm_extractor = rift.package.charm.PackageCharmExtractor(self.log)
            charm_extractor.extract_charms(package)
        except rift.package.charm.CharmExtractionError as e:
            raise MessageException(OnboardExtractionError()) from e

    def extract_scripts(self, package):
        try:
            script_extractor = rift.package.script.PackageScriptExtractor(self.log)
            script_extractor.extract_scripts(package)
        except rift.package.script.ScriptExtractionError as e:
            raise MessageException(OnboardExtractionError()) from e

    def extract_configs(self, package):
        try:
            config_extractor = rift.package.config.PackageConfigExtractor(self.log)
            config_extractor.extract_configs(package)
        except rift.package.config.ConfigExtractionError as e:
            raise MessageException(OnboardExtractionError()) from e

    def extract_icons(self, package):
        try:
            icon_extractor = rift.package.icon.PackageIconExtractor(self.log)
            icon_extractor.extract_icons(package)
        except rift.package.icon.IconExtractionError as e:
            raise MessageException(OnboardExtractionError()) from e

    def validate_package(self, package):
        checksum_validator = rift.package.package.PackageChecksumValidator(self.log)

        try:
            file_checksums = checksum_validator.validate(package)
        except rift.package.package.PackageFileChecksumError as e:
            raise MessageException(OnboardChecksumMismatch(e.filename)) from e
        except rift.package.package.PackageValidationError as e:
            raise MessageException(OnboardUnreadablePackage()) from e

        return file_checksums

    def onboard_descriptors(self, package):
        descriptor_msg = package.descriptor_msg

        if descriptor_msg.has_field('vdu'):
            for vdu in descriptor_msg.vdu:
                if not all(cp.virtual_interface.type_yang == vdu.external_interface[0].virtual_interface.type_yang for cp in vdu.external_interface):
                    ### We have a mix of E1000 & VIRTIO virtual interface types in the VDU, abort instantiation.
                    err_str = "%s - VDU Virtual Interfaces need to be of the same type. Found a mix of VIRTIO & E1000." % package.descriptor_file
                    raise MessageException(OnboardDescriptorError(err_str))
                if (len(vdu.external_interface)):
                    virt_intf_type = vdu.external_interface[0].virtual_interface.type_yang
                    if virt_intf_type == "E1000":
                        self.log.info("Found E1000 type virtual interface in VDU while onboarding VNF")
                        self._is_vdu_if_type_e1000 = True

        self.log.message(OnboardDescriptorOnboard())

        try:
            self.onboarder.onboard(descriptor_msg)
        except onboard.OnboardError as e:
            raise MessageException(OnboardDescriptorError(package.descriptor_file)) from e


class UploaderApplication(tornado.web.Application):
    def __init__(self, tasklet):
        self.tasklet = tasklet
        self.accounts = []
        self.messages = collections.defaultdict(list)
        self.export_dir = os.path.join(os.environ['RIFT_ARTIFACTS'], 'launchpad/exports')

        manifest = tasklet.tasklet_info.get_pb_manifest()
        self.use_ssl = manifest.bootstrap_phase.rwsecurity.use_ssl
        self.ssl_cert = manifest.bootstrap_phase.rwsecurity.cert
        self.ssl_key = manifest.bootstrap_phase.rwsecurity.key

        self.uploader = image.ImageUploader(self.log, self.loop, tasklet.dts)
        self.onboarder = onboard.DescriptorOnboarder(
                self.log, "127.0.0.1", 8008, self.use_ssl, self.ssl_cert, self.ssl_key
                )
        self.package_store_map = {
                "vnfd": self.tasklet.vnfd_package_store,
                "nsd": self.tasklet.nsd_package_store,
                }

        self.exporter = export.DescriptorPackageArchiveExporter(self.log)
        self.loop.create_task(export.periodic_export_cleanup(self.log, self.loop, self.export_dir))

        attrs = dict(log=self.log, loop=self.loop)

        export_attrs = attrs.copy()
        export_attrs.update({
            "store_map": self.package_store_map,
            "exporter": self.exporter,
            "catalog_map": {
                "vnfd": self.vnfd_catalog,
                "nsd": self.nsd_catalog
                }
            })

        super(UploaderApplication, self).__init__([
            (r"/api/update", UpdateHandler, attrs),
            (r"/api/upload", UploadHandler, attrs),

            (r"/api/upload/([^/]+)/state", UploadStateHandler, attrs),
            (r"/api/update/([^/]+)/state", UpdateStateHandler, attrs),
            (r"/api/export/([^/]+)/state", export.ExportStateHandler, attrs),

            (r"/api/export/(nsd|vnfd)$", export.ExportHandler, export_attrs),
            (r"/api/export/([^/]+.tar.gz)", tornado.web.StaticFileHandler, {
                "path": self.export_dir,
                }),
            (r"/api/export/([^/]+.zip)", tornado.web.StaticFileHandler, {
                "path": self.export_dir,
                }),
            ])

    @property
    def log(self):
        return self.tasklet.log

    @property
    def loop(self):
        return self.tasklet.loop

    def get_logger(self, transaction_id):
        return message.Logger(self.log, self.messages[transaction_id])

    def onboard(self, part_streamer, transaction_id, auth=None):
        log = message.Logger(self.log, self.messages[transaction_id])

        OnboardPackage(
                log,
                self.loop,
                part_streamer,
                auth,
                self.onboarder,
                self.uploader,
                self.package_store_map,
                ).start()

    def update(self, part_streamer, transaction_id, auth=None):
        log = message.Logger(self.log, self.messages[transaction_id])

        UpdatePackage(
                log,
                self.loop,
                part_streamer,
                auth,
                self.onboarder,
                self.uploader,
                self.package_store_map,
                ).start()

    @property
    def vnfd_catalog(self):
        return self.tasklet.vnfd_catalog

    @property
    def nsd_catalog(self):
        return self.tasklet.nsd_catalog
