# sitecustomize.py
# this file was added by PythonEmbed4Win.ps1
# https://github.com/jtmoon79/PythonEmbed4Win/blob/0a2e24cc224743ecc199d51bd6f43bb5990bce25/PythonEmbed4Win.ps1

import os
import site
import sys

# do not use user-wide site.USER_SITE path; it refers to a path location
# outside of this embed installation
site.ENABLE_USER_SITE = False

# remove site.USER_SITE and the realpath variation from sys.path
# XXX: somewhat time consuming to do on every startup but thorough
__sys_path_index_del = list()
"""index to delete from sys.path"""
__user_site_resolve = os.path.realpath(site.USER_SITE)
for __i, __path in enumerate(sys.path):
    __path_resolve = os.path.realpath(__path)
    if site.USER_SITE in (__path, __path_resolve):
        __sys_path_index_del.append(__i)
        continue
    if __user_site_resolve in (__path, __path_resolve):
        __sys_path_index_del.append(__i)
for __index_del in reversed(__sys_path_index_del):
    sys.path.pop(__index_del)
del __sys_path_index_del
del __user_site_resolve

