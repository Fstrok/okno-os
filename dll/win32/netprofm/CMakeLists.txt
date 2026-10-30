# Imported from Wine by tools/wine/import_dll.py (wine-11.20)

spec2def(netprofm.dll netprofm.spec)

list(APPEND SOURCE
    list.c
    main.c
    ${CMAKE_CURRENT_BINARY_DIR}/netprofm.def)

add_library(netprofm MODULE ${SOURCE} netprofm.rc)
set_source_files_properties(netprofm.rc PROPERTIES OBJECT_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/netprofm.rgs")
set_module_type(netprofm win32dll)
target_compile_definitions(netprofm PRIVATE __WINESRC__ __ROS_LONG64__)
target_link_libraries(netprofm wine uuid wine_dll_canunload wine_dll_register oldnames)
add_importlibs(netprofm iphlpapi msvcrt kernel32 ntdll)
add_dependencies(netprofm psdk)
add_cd_file(TARGET netprofm DESTINATION reactos/system32 FOR all)
set_wine_module(netprofm)
