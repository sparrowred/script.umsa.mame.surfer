# -*- coding: utf-8 -*-

import os
import codecs
import time         # to measure how long the scan takes

class Dats:
    
    def __init__(self, datdir):
        
        time1 = time.time()
        self.dat = {}
        self.status = ""
        
        
        for d in os.listdir( datdir ):
            if d[-4:] != '.dat':
                continue
            x = os.path.join( datdir, d )
            #print("scanning " + x)
            fobj = None
            try:
                fobj = codecs.open( x, 'r')
            except:
                #print("cant open")
                self.status += "can't open %s" % (x,)
            if fobj:
                self.scan_dat(fobj)
                fobj.close()
                
        time2 = time.time()
        #print("- scan_dats     %0.3f ms" % ( (time2-time1)*1000.0, ))
        return
    
    def scan_dat(self, fobj):

        tag = ""
        swl = []
        sets = []
        flag = None
        
        for line in fobj:
            line = line.rstrip()
            if len(line) < 1:
                continue
    
            # into an entry
            if flag:
                # save entry
                if line == '$end':
                    # clear variables
                    tag = ""
                    swl = None
                    sets = None
                    flag = None
                    
                # add line to entry
                elif line == '$bio':
                    tag = 'History'
                    if tag not in self.dat[swl[0]][sets[0]]:
                        self.dat[swl[0]][sets[0]][tag] = ""
                    else:
                        self.dat[swl[0]][sets[0]][tag] += "-----NEXT--------[CR]"
                    
                elif line[:2] == '- ' and line[-2:] == ' -':
                    tag = line[2:-2].lower().capitalize()
                    if tag == "Tips and tricks":
                        tag = "Tips/Tricks"
                    if tag not in self.dat[swl[0]][sets[0]]:
                        self.dat[swl[0]][sets[0]][tag] = ""
                    else:
                        self.dat[swl[0]][sets[0]][tag] += "-----NEXT--------[CR]"
                    
                elif ( line == '$mame'
                       or line[:7] == 'LEVELS:'
                       or line[:7].lower() == 'romset:'
                       or line == 'Other Emulators:'
                      ):
                    tag = 'Info'
                    if tag not in self.dat[swl[0]][sets[0]]:
                        self.dat[swl[0]][sets[0]][tag] = ""
                    else:
                        self.dat[swl[0]][sets[0]][tag] += line + "[CR]"
                        
                elif ( line in ( 'WIP:',
                                 'STORY:',
                                 'START:',
                                 'SETUP:',
                                 'GAMEPLAY:',
                                 'PLAY INSTRUCTIONS:',
                               )
                     ):
                    tag = line[:-1].lower().capitalize()
                    if tag == 'Play instructions':
                        tag = 'Play Inst.'
                    elif tag == 'Wip':
                        tag = 'WIP'
                    if tag not in self.dat[swl[0]][sets[0]]:
                        self.dat[swl[0]][sets[0]][tag] = ""
                    else:
                        self.dat[swl[0]][sets[0]][tag] += "-----NEXT--------[CR]"
                        
                elif line[:17] == 'Recommended Games':
                    tag = "Rec"
                    if '(' in line:
                        cat = "- " + line[ line.find('(')+1:line.find(')') ] + ":[CR]"
                    else:
                        cat = ""
                    if tag not in self.dat[swl[0]][sets[0]]:
                        self.dat[swl[0]][sets[0]][tag] = cat
                    else:
                        self.dat[swl[0]][sets[0]][tag] += cat
                    
                else:
                    if tag in self.dat[swl[0]][sets[0]]:
                        self.dat[swl[0]][sets[0]][tag] += line + "[CR]"
                    else:
                        tag = 'others'
                        if tag not in self.dat[swl[0]][sets[0]]:
                            self.dat[swl[0]][sets[0]][tag] = line + "[CR]"
                        else:
                            self.dat[swl[0]][sets[0]][tag] += "-----NEXT--------[CR]"
                            self.dat[swl[0]][sets[0]][tag] += line + "[CR]"
    
            else:
                # check if entry begins
                if line[0] == '$' and '=' in line:
                    flag = True
                    
                    # remove last ,
                    if line[-1:] == ',':
                        line = line[:-1]
                        
                    # split at =
                    swl_str, sets_str = line[1:].split( '=', 1 )
                    
                    # replace info with mame
                    swl_str = swl_str.replace( 'info', 'mame' )
                    
                    # split swl and sets by ,
                    swl = swl_str.split(',')
                    sets = sets_str.split(',')
                    
                    # first swl gets dict                    
                    if swl[0] not in self.dat.keys():
                        self.dat[swl[0]] = {}

                    # if other swl reference to parent
                    if len(swl) > 1:
                        for s in swl[1:]:
                            if s not in self.dat.keys():
                                self.dat[s] = self.dat[swl[0]]
                    
                    # first set gets the info
                    if sets[0] not in self.dat[swl[0]]:
                        self.dat[swl[0]][sets[0]] = {}

                    # if other sets reference to parent                    
                    if len(sets) > 1:
                        for s in sets[1:]:
                            if s not in self.dat[swl[0]]:
                                self.dat[swl[0]][s] = self.dat[swl[0]][sets[0]]
                                
        return
    
def parse_mame_ini(ini_file):
    
    mame_ini = {}
    ini = None
    
    try:
        fobj = codecs.open(ini_file, 'r')
        ini = fobj.readlines()
        fobj.close()
    except:
        pass
    
    if ini:
        for line in ini:
            line = line.strip()
            if len(line) == 0:
                continue
            if line[0] == '#':
                continue
            option = line.split(' ', 1)
            if len(option) > 0:
                # can contain multiple directories
                if 'path' in option[0]:
                    x = option[1].strip().split(';')
                    mame_ini[option[0].strip()] = x
                # only one directory
                if 'directory' in option[0]:
                    mame_ini[option[0].strip()] = option[1].strip()

    return mame_ini

def load_filter(settings_folder, filter_file):

    flists = {
        'Softwarelists'         : [],
        'Game Categories'       : [],
        'Machine Categories'    : [],
        'Players'               : [],
        'Years'                 : [],
    }
    
    fobj = None
    try:
        fobj = codecs.open(
            os.path.join( settings_folder, filter_file ), 'r'
        )
        if fobj:
            # put all lines from file into a list
            f = list(fobj)
            fobj.close()
            
            # take care of empty lines
            if f[0].rstrip():
                flists['Softwarelists'] = f[0].rstrip().split(',')
            if f[1].rstrip():
                flists['Game Categories'] = f[1].rstrip().split(',')
            if f[2].rstrip():
                flists['Machine Categories'] = f[2].rstrip().split(',')
            if f[3].rstrip():
                flists['Years'] = f[3].rstrip().split(',')
            if f[4].rstrip():
                flists['Players'] = f[4].rstrip().split(',')
            # convert str from file into int
            # for k,v in flists.items():
            #     flists[k] = [ int(x) for x in v ]
    except:
        pass
    
    return flists

def save_filter(settings_folder, filter_file, filter_lists):
    
    fobj = None
    
    try: fobj = codecs.open(os.path.join (settings_folder, filter_file), 'w')
    except: pass
    
    # for k,v in filter_lists.items():
    #     filter_lists[k] = [ str(x) for x in v ]
    
    if fobj:
        fobj.write(','.join(filter_lists['Softwarelists'])+'\n')
        fobj.write(','.join(filter_lists['Game Categories'])+'\n')
        fobj.write(','.join(filter_lists['Machine Categories'])+'\n')
        fobj.write(','.join(filter_lists['Years'])+'\n')
        fobj.write(','.join(filter_lists['Players'])+'\n')
        
        fobj.close()
    
    return

def load_lastsaver(settings_folder):
    
    lastlist = []
    fobj = None
    
    try:
        fobj = codecs.open(
            os.path.join( settings_folder, 'lastsaver.txt' ), 'r'
        )
    except:
        pass
    
    if fobj:
        for line in fobj:
            lastlist.append ( line.strip().split(',') )
        fobj.close()
    
    return reversed( lastlist )

def load_software_list(settings_folder, filename):
    
    software_list = []
    fobj = None
    
    try:
        fobj = codecs.open(
            os.path.join( settings_folder, filename ), 'r'
        )
    except:
        pass
    
    if fobj:
        for line in fobj:
            for i in line.split(','):
                software_list.append(int(i))
    
        fobj.close()
        
    return software_list

def save_software_list(settings_folder, filename, software_list):
    
    fobj = None
    
    try:
        fobj = codecs.open(
            os.path.join ( settings_folder, filename ), 'w'
        )
    except:
        pass
    
    if fobj:
        fobj.write( ','.join( [ str(x) for x in software_list ] ) )
    
        fobj.close()
    
    return