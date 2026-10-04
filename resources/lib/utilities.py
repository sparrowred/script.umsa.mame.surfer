# -*- coding: utf-8 -*-
"""Utilities for UI.

 - load last screensaver list
 - load/save filters
 - load/save last games viewed
 - log indirection for xbmc-free modules

TODO the list for filter categories need to come from importer
"""

import os

def load_filter(settings_folder, filter_file):
    """ load filter """

    flists = {
        'Softwarelists': [],
        'Game Categories': [],
        'Machine Categories': [],
        'Players': [],
        'Years': [],
    }

    fobj = False
    try:
        fobj = open(os.path.join(settings_folder, filter_file), 'r', encoding='utf-8')
    except IOError:
        pass

    if fobj:
        # put all lines from file into a list
        file_c = fobj.readlines()
        fobj.close()
        # take care of empty lines
        if file_c[0].rstrip():
            flists['Softwarelists'] = file_c[0].rstrip().split(',')
        if file_c[1].rstrip():
            flists['Game Categories'] = file_c[1].rstrip().split(',')
        if file_c[2].rstrip():
            flists['Machine Categories'] = file_c[2].rstrip().split(',')
        if file_c[3].rstrip():
            flists['Years'] = file_c[3].rstrip().split(',')
        if file_c[4].rstrip():
            flists['Players'] = file_c[4].rstrip().split(',')
    return flists

def save_filter(settings_folder, filter_file, filter_lists):
    """ save filter """

    fobj = False
    try:
        fobj = open(os.path.join(settings_folder, filter_file), 'w', encoding='utf-8')
    except IOError:
        pass
    if fobj:
        fobj.write(','.join(
            [str(x) for x in filter_lists['Softwarelists']])+'\n')
        fobj.write(','.join(
            [str(x) for x in filter_lists['Game Categories']])+'\n')
        fobj.write(','.join(
            [str(x) for x in filter_lists[
                'Machine Categories']])+'\n')
        fobj.write(','.join(
            [str(x) for x in filter_lists['Years']])+'\n')
        fobj.write(','.join(
            [str(x) for x in filter_lists['Players']])+'\n')
        fobj.close()

def load_lastsaver(settings_folder):
    """ load list of games from last screensaver run """

    lastlist = []
    fobj = False
    try:
        fobj = open(os.path.join(settings_folder, 'lastsaver.txt'), 'r', encoding='utf-8')
    except IOError:
        pass
    if fobj:
        for line in fobj:
            lastlist.append(line.strip().split(','))
        fobj.close()
    return reversed(lastlist)

def load_software_list(settings_folder, filename):
    """ load software list """

    software_list = []
    fobj = False
    try:
        fobj = open(os.path.join(settings_folder, filename), 'r', encoding='utf-8')
    except IOError:
        pass
    if fobj:
        line = fobj.readline()
        fobj.close()
        # check for empty line
        if line:
            software_list = [int(x) for x in line.split(',')]
    return software_list

def save_software_list(settings_folder, filename, software_list):
    """ save software list """

    fobj = False
    try:
        fobj = open(os.path.join(settings_folder, filename), 'w', encoding='utf-8')
    except IOError:
        pass

    if fobj:
        fobj.write(
            ','.join([str(x) for x in software_list])
        )
        fobj.close()

_log = None

def set_log(function):
    """Register log function from xbmc using modules."""

    global _log
    _log = function

def log(*args, level='debug'):
    """Log via registered function, no-op if none registered."""

    if _log:
        _log(*args, level=level)
