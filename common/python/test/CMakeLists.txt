# Creation Date: 2016/1/12
# RIFT_IO_STANDARD_CMAKE_COPYRIGHT_HEADER(END)

cmake_minimum_required(VERSION 2.8)

rift_py3test(utest_juju_api
  TEST_ARGS
  ${CMAKE_CURRENT_SOURCE_DIR}/utest_juju_api.py
  )
