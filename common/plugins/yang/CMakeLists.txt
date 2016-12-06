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
# Author(s): Austin Cormier
# Creation Date: 2015/11/20
# 

##
# Yang targets
##
rift_add_yang_target(
  TARGET rwcloud_yang
  YANG_FILES rw-cloud.yang rw-sdn.yang
  COMPONENT ${PKG_LONG_NAME}
  LIBRARIES
    rwsdn_yang_gen
    rwcal_yang_gen
  DEPENDS
    rwcal_yang
)

rift_add_yang_target(
  TARGET rwconfig_agent_yang
  YANG_FILES rw-config-agent.yang
  COMPONENT ${PKG_LONG_NAME}
  LIBRARIES
    rwcal_yang_gen
  DEPENDS
    rwcal_yang
)
