# -*- coding: utf-8 -*-
"""Utilities for UMSA

 - parse mame.ini
 - load last screensaver list
 - load/save filters
 - load/save last games viewed

TODO the list for filter categories need to come from importer
"""

import os
from io import open

def parse_mame_ini(ini_file):
    """ parse mame ini """

    fobj = False
    mame_ini = {}
    try:
        fobj = open(ini_file, 'r', encoding='utf-8')
    except IOError:
        pass
    if fobj:
        for line in fobj.readlines():
            line = line.strip()
            if len(line) == 0:
                continue
            if line[0] == '#':
                continue
            option = line.split(' ', 1)
            if len(option) > 0:
                # can contain multiple directories
                if 'path' in option[0]:
                    mame_ini[option[0].strip()] = option[1].strip().split(';')
                # only one directory
                if 'directory' in option[0]:
                    mame_ini[option[0].strip()] = option[1].strip()
        fobj.close()
    return mame_ini

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
        # PY2: remove encode and decode for py3 only
        fobj.write(','.join(
            [str(x) for x in filter_lists['Softwarelists']]).encode('utf-8').decode('utf-8')+'\n')
        fobj.write(','.join(
            [str(x) for x in filter_lists['Game Categories']]).encode('utf-8').decode('utf-8')+'\n')
        fobj.write(','.join(
            [str(x) for x in filter_lists[
                'Machine Categories']]).encode('utf-8').decode('utf-8')+'\n')
        fobj.write(','.join(
            [str(x) for x in filter_lists['Years']]).encode('utf-8').decode('utf-8')+'\n')
        fobj.write(','.join(
            [str(x) for x in filter_lists['Players']]).encode('utf-8').decode('utf-8')+'\n')
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
            # PY2: remove encode and decode for py3 only
            ','.join([str(x) for x in software_list]).encode('utf-8').decode('utf-8')
        )
        fobj.close()
