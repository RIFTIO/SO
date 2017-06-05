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
# Author(s): Anil Gunturu
# Creation Date: 03/26/2014
# 

##
# DEPENDENCY ALERT
# The submodule dependencies must be specified in the
# .gitmodules.dep file at the top level (supermodule) directory
# If this submodule depends other submodules remember to update
# the .gitmodules.dep
##

cmake_minimum_required(VERSION 2.8)

message(CMAKE_MODULE_PATH=${CMAKE_MODULE_PATH})

##
# DO NOT add any code before this and DO NOT
# include this file anywhere else
##
include(rift_submodule NO_POLICY_SCOPE)
include(rift_python)

##
# Submodule specific includes will go here, 
# These are specified here, since these variables are accessed
# from multiple sub directories. If the variable is subdirectory
# specific it must be declared in the subdirectory.
##

##
# Include the subdirs
##
set(subdirs
  common
  examples
  models
  rwcal
  rwmon
  rwcm
  rwlaunchpad
  )

if (NOT RIFT_AGENT_BUILD STREQUAL "XML_ONLY")
  list(APPEND subdirs confd_client)
endif()

rift_add_subdirs(SUBDIR_LIST ${subdirs})

install(FILES BUILD.sh DESTINATION bin COMPONENT installer)

##
# Set up package details
##
rift_set_component_package_fields(
  "rwcal-aws-1.0"
  DESCRIPTION "RIFT.ware rwcal-aws"
  )

rift_set_component_package_fields(
  "vcpe_yang_ylib-1.0"
  DESCRIPTION "RIFT.ware vcpe_yang_ylib"
  )

rift_set_component_package_fields(
  "rwcal-cloudsim-1.0"
  DESCRIPTION "RIFT.ware rwcal-cloudsim"
  )

rift_set_component_package_fields(
  "rwmon-1.0"
  DESCRIPTION "RIFT.ware rwmon"
  )

rift_set_component_package_fields(
  "models-1.0"
  DESCRIPTION "RIFT.ware models"
  )

rift_set_component_package_fields(
  "mano-types_yang_ylib-1.0"
  DESCRIPTION "RIFT.ware mano-types_yang_ylib"
  )

rift_set_component_package_fields(
  "rwcalproxytasklet-1.0"
  DESCRIPTION "RIFT.ware rwcalproxytasklet"
  )

rift_set_component_package_fields(
  "installer"
  DESCRIPTION "RIFT.ware installer"
  )

rift_set_component_package_fields(
  "lpmocklet_yang_ylib-1.0"
  DESCRIPTION "RIFT.ware lpmocklet_yang_ylib"
  )

rift_set_component_package_fields(
  "rwcm-1.0"
  DESCRIPTION "RIFT.ware rwcm"
  )

rift_set_component_package_fields(
  "rwmon_yang_ylib-1.0"
  DESCRIPTION "RIFT.ware rwmon_yang_ylib"
  )

rift_set_component_package_fields(
  "rwcloud_yang_ylib-1.0"
  DESCRIPTION "RIFT.ware rwcloud_yang_ylib"
  )

rift_set_component_package_fields(
  "rwconfig_agent_yang_ylib-1.0"
  DESCRIPTION "RIFT.ware rwconfig_agent_yang_ylib"
  )

rift_set_component_package_fields(
  "rwmano_examples-1.0"
  DESCRIPTION "RIFT.ware rwmano_examples"
  )

rift_set_component_package_fields(
  "rwlaunchpad_yang_ylib-1.0"
  DESCRIPTION "RIFT.ware rwlaunchpad_yang_ylib"
  )

rift_set_component_package_fields(
  "rwcal-1.0"
  DESCRIPTION "RIFT.ware rwcal"
  )

rift_set_component_package_fields(
  "rwcal-openmano-vimconnector-1.0"
  DESCRIPTION "RIFT.ware rwcal-openmano-vimconnector"
  )

rift_set_component_package_fields(
  "rwcal-mock-1.0"
  DESCRIPTION "RIFT.ware rwcal-mock"
  )

rift_set_component_package_fields(
  "rwcal-openstack-1.0"
  DESCRIPTION "RIFT.ware rwcal-openstack"
  )

rift_set_component_package_fields(
  "rwcal-propcloud1-1.0"
  DESCRIPTION "RIFT.ware rwcal-propcloud1"
  )

rift_set_component_package_fields(
  "rwcal-cloudsimproxy-1.0"
  DESCRIPTION "RIFT.ware rwcal-cloudsimproxy"
  )

rift_set_component_package_fields(
  "rwlaunchpad-1.0"
  DESCRIPTION "RIFT.ware rwlaunchpad"
  )

rift_set_component_package_fields(
  "common-1.0"
  DESCRIPTION "RIFT.ware common"
  )

rift_set_component_package_fields(
  "rwsdn_yang_ylib-1.0"
  DESCRIPTION "RIFT.ware rwDSN yang ylib"
  )

rift_set_component_package_fields(
  "mano_yang_ylib-1.0"
  DESCRIPTION "RIFT.ware MANO yang ylib"
  )

rift_set_component_package_fields(
  "rwcal_yang_ylib-1.0"
  DESCRIPTION "RIFT.ware rwCAL yang ylib"
  )

rift_set_component_package_fields(
  "rw_conman_yang_ylib-1.0"
  DESCRIPTION "RIFT.ware rw conman yang ylib"
  )

##
# This macro adds targets for documentaion, unittests, code coverage and packaging
##
rift_add_submodule_targets(SUBMODULE_PACKAGE_NAME "rw.core.mano")

# Workaround whatever mess rw.package is doing as it can't seem
# to figure out that it should make a directory -before- making
# symlinks..
set(dir usr/lib64/python${RIFT_PYTHON3}/site-packages/gi/overrides)
install(FILES
  ${CMAKE_CURRENT_SOURCE_DIR}/.cpack-workaround
  DESTINATION ${dir})

if (RIFT_SUPPORT_PYTHON2)
  set(dir usr/lib64/python${RIFT_PYTHON2}/site-packages/gi/overrides)

  install(FILES
    ${CMAKE_CURRENT_SOURCE_DIR}/.cpack-workaround
    DESTINATION ${dir})
endif()
