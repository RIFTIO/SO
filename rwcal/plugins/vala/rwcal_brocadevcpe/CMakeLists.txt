
# STANDARD_RIFT_IO_COPYRIGHT

include(rift_plugin)

set(PKG_NAME rwcal-propcloud1)
set(PKG_VERSION 1.0)
set(PKG_RELEASE 1)
set(PKG_LONG_NAME ${PKG_NAME}-${PKG_VERSION})

rift_install_python_plugin(rwcal_propcloud1 rwcal_propcloud1.py)

rift_python_install_tree(
  FILES
    rift/rwcal/brocadevcpe/__init__.py
    rift/rwcal/brocadevcpe/brocadevcpe_drv.py
    rift/rwcal/brocadevcpe/mgmt_session.py
    rift/rwcal/brocadevcpe/brocade_rest.py
    rift/rwcal/brocadevcpe/prepare_vm.py
  PYTHON3_ONLY
  COMPONENT ${PKG_LONG_NAME})

set(subdirs yang vala)
rift_add_subdirs(SUBDIR_LIST ${subdirs})


