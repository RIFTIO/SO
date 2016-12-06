##
# Allow specific compiler warnings
##
rift_allow_compiler_warning(unused-but-set-variable)

set(subdirs
  rwmon_brocade
  )
rift_add_subdirs(SUBDIR_LIST ${subdirs})
