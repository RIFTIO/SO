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
# Creation Date: 2014/04/30
# 

cmake_minimum_required(VERSION 2.8)

# confd_client executable
add_executable(confd_client confd_client.c)

target_link_libraries(confd_client
  ${CMAKE_INSTALL_PREFIX}/usr/local/confd/lib/libconfd.so
  pthread
  )
