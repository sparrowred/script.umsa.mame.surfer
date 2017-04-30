# -*- coding: utf-8 -*-

import os            # always needed
import subprocess    # to start emulator
import time          # for play time
import zipfile       # for extracting zipped roms for non-mame
import random        # to shuffle the pics
import sys           # to get the kodi addon setting
import urllib2       # only needed for db download

import xbmc, xbmcgui, xbmcaddon

# utility functions to load/save internal data and get datfiles
import utilmod
from dbmod import DBMod # connection to status und maston sqlite db

__addon__    = sys.modules[ '__main__' ].__addon__
SCRIPTID = "script.umsa.mame.surfer"

# folder for settings
settings_folder = xbmc.translatePath(
        'special://profile/addon_data/%s' %(SCRIPTID)
)
media_folder = xbmc.translatePath(
        'special://home/addons/%s/resources/skins/Default/media/' %(SCRIPTID)
)

#Action Codes
# See guilib/Key.h
ACTION_CANCEL_DIALOG = (9,10,51,92,110)
ACTION_PLAYFULLSCREEN = (12,79,227)
ACTION_MOVEMENT_LEFT = (1,)
ACTION_MOVEMENT_RIGHT = (2,)
ACTION_MOVEMENT_UP = (3,)
ACTION_MOVEMENT_DOWN = (4,)
ACTION_MOVEMENT = (1, 2, 3, 4, 5, 6, 159, 160)
ACTION_INFO = (11,)
ACTION_CONTEXT = (117,)
ACTION_ENTER = (7,)

#ControlIds
SOFTWARE_BUTTON = 4000
GROUP_GAME_LIST = 407
GROUP_FILTER = 408
TEXTLIST = 4033
IMAGE_BIG_LIST = 2233
IMAGE_LIST = 2223
LEFT_IMAGE_HORI = 2222
LEFT_IMAGE_VERT = 2221
CONTROL_BUTTON_CONTEXT = 2101
CONTROL_BUTTON_FILTER = 2102
CONTROL_BUTTON_EXIT = 2103
CONTROL_BUTTON_SETTINGS = 2104
CONTROL_BUTTON_UPDATE = 2105
SET_LIST = 4003
SYSTEM_BORDER = 2405
SYSTEM_WRAPLIST = 4005
MACHINE_PLUS = 4210
MACHINE_SEP1 = 2406
MACHINE_SEP2 = 2407
MACHINE_SEP3 = 2408
CONTEXT_MENU = 4009
GAME_LIST = 4007
GAME_LIST_BG = 4107
GAME_LIST_LABEL = 4117
GAME_LIST_OPTIONS = 4118
GAME_LIST_SORT = 4119
GAME_LIST_IMAGE = 4115
FILTER_CATEGORY_LIST = 4008
FILTER_CONTENT_LIST = 4088
FILTER_LIST_BG = 4108
FILTER_LABEL = 4109
FILTER_LABEL2 = 4110
FILTER_OPTIONS = 4116
LABEL_STATUS = 4101
SHADOW_MACHINE = 4201
SHADOW_SET = 4202
SHADOW_DAT = 4203

# xmbc.sleep times in ms
WAIT_PLAYER = 500
WAIT_GUI = 100

class UMSA(xbmcgui.WindowXMLDialog):
    
    def __init__( self,
                  strXMLname,
                  strFallbackPath,
                  strDefaultName,
                  forceFallback
                ):
        
        # no settings
        if not os.path.exists(settings_folder):
            __addon__.openSettings()
        
        self.read_settings()

        # initialize
        random.seed()
        self.quit = False
        self.selectedControlId = 4000 # holds the old control id from skin
        self.info = None # contains all sets for actual software

        self.dummy = None # needed to prevent a software jump when popup is quit by left or right        
        self.enter = None # set when a gamelist select happens
        self.oldset = () # needed for show_info to see if set has changed
        
        # list for last selected games, only saves the software id
        self.last = []
        # pointer for last selected games list
        self.lastptr = 9
        # old search
        self.searchold = None
        # diff emu toggle
        self.diff_emu = False
        
        # filter categories
        self.filter_cat = [
                "Softwarelists", "Game Categories", "Machine Categories", "Players",
                "Years", "----------", "Load Filter", "Save Filter" 
            ]
        
        print "- UMSA: __init__ done"

    def onInit(self):
        
        # make all popups unvisible
        self.getControl(MACHINE_PLUS).setVisible(False)
        self.getControl(SHADOW_DAT).setVisible(False)
        self.getControl(SHADOW_MACHINE).setVisible(False)
        self.getControl(SHADOW_SET).setVisible(False)
        
        #separators for machine wraplist
        self.getControl(MACHINE_SEP1).setVisible(False)
        self.getControl(MACHINE_SEP2).setVisible(False)
        self.getControl(MACHINE_SEP3).setVisible(False)
        
        self.close_gamelist()
        self.close_filterlist( no_update=True )
        
        # no videos when something is already running        
        #if xbmc.Player().isPlayingVideo():
        #    self.playvideo = None
            
        # set aspectratio for left images depending on screen aspect
        if self.aratio == "16:10":
            _4to3 = self.getControl(LEFT_IMAGE_HORI).getWidth()
            _3to4 = self.getControl(LEFT_IMAGE_VERT).getWidth()
            self.getControl(LEFT_IMAGE_HORI).setWidth(int(_4to3 /1.6*1.77)) # 4:3
            self.getControl(LEFT_IMAGE_VERT).setWidth(int(_3to4 *1.77/1.6)) # 3:4
        elif self.aratio == "5:4":
            _4to3 = self.getControl(LEFT_IMAGE_HORI).getWidth()
            _3to4 = self.getControl(LEFT_IMAGE_VERT).getWidth()
            self.getControl(LEFT_IMAGE_HORI).setWidth(int(_4to3 /1.25*1.77)) # 4:3
            self.getControl(LEFT_IMAGE_VERT).setWidth(int(_3to4 *1.77/1.25)) # 3:4
        elif self.aratio == "4:3":
            _4to3 = self.getControl(LEFT_IMAGE_HORI).getWidth()
            _3to4 = self.getControl(LEFT_IMAGE_VERT).getWidth()
            self.getControl(LEFT_IMAGE_HORI).setWidth(int(_4to3  /1.33*1.77)) # 4:3
            self.getControl(LEFT_IMAGE_VERT).setWidth(int(_3to4  *1.77/1.33)) # 3:4
            
        self.selectedControlId = SOFTWARE_BUTTON
        
        # load mame.ini
        self.mame_ini = utilmod.parse_mame_ini(self.mameini)
        
        # set snap directory
        if 'snapshot_directory' in self.mame_ini:
            self.mame_ini['snapshot_directory'] = os.path.join(
                self.mame_dir,
                self.mame_ini['snapshot_directory']
            )
        else:
            self.mame_ini['snapshot_directory'] = ''

        # load filters
        self.filter_lists = utilmod.load_filter( settings_folder, 'filter_default.txt' )
        self.act_filter = 'default'
        self.getControl(FILTER_LABEL2).setLabel(self.act_filter)
        
        # fill filter lists
        l = []
        for i in self.filter_cat:
            l.append( xbmcgui.ListItem( i ) )
        self.getControl(FILTER_CATEGORY_LIST).addItems(l)
        self.getControl(FILTER_OPTIONS).addItems( ('all','none','invert') )
        
        # database connection
        self.ggdb = None
        if os.path.isfile( os.path.join( settings_folder, 'umsa.db' ) ):
            self.ggdb = DBMod(
                settings_folder,
                self.filter_lists,
                self.pref_country,
            )
        else:
            self.update()
            
        # load filter content for swl
        self.set_filter_content('Softwarelists')
        # set_filter_content also sets focus
        # then first keypress in gui is missed, therefore:
        self.setFocus(self.getControl(SOFTWARE_BUTTON))
            
        # load dats
        self.getControl(LABEL_STATUS).setLabel('scanning dat files...')
        self.dat = utilmod.Dats( self.datdir )
        
        # load last internal software list
        self.last = utilmod.load_software_list(
            settings_folder, 'lastgames.txt'
        )
        
        while len(self.last) < 10:
            # fill with random software if not 10
            self.last.append( self.ggdb.get_random_id() )
        self.select_software( self.last[self.lastptr] )
        
        self.dialog = xbmcgui.Dialog()
        
        #xbmc.sleep(250)
        print "- UMSA: GUI Init done"
        # dialog.notification(
        #     'UMSA',
        #     'GUI Init done.',
        #     xbmcgui.NOTIFICATION_INFO,
        #     5000
        # )
        
        if(self.quit):
            self.close()
            return

    # first is onFocus, then onClick, and last is onAction
    def onFocus(self, controlId):
        print "--- onFocus"
        print "-- old: %s" % (self.selectedControlId,)
        print "-- new: %s" % (controlId,)
        
        self.dummy = None
        # close popups
        if controlId == SOFTWARE_BUTTON or controlId == SYSTEM_WRAPLIST:
            
            if self.selectedControlId in (
                    GAME_LIST, GAME_LIST_OPTIONS, CONTEXT_MENU, GAME_LIST_SORT
                ):
                self.close_gamelist()
                if self.enter:
                    self.enter = None
                else:
                    self.dummy = True
                    
            elif self.selectedControlId in (
                    FILTER_CATEGORY_LIST, FILTER_CONTENT_LIST
                ):
                
                self.close_filterlist()
                if self.enter:
                    self.enter = None
                else:
                    self.dummy = True
                    
        # check if we have to move to next item
        # as the actual item has no or only 1 element
        if ( controlId == SYSTEM_WRAPLIST
             and self.getControl(SYSTEM_WRAPLIST).size() == 1
           ):
            if self.selectedControlId == SET_LIST:
                print "- from SET to SOFTWARE"
                self.setFocus(self.getControl(SOFTWARE_BUTTON))
            else:
                print "- from SOFTWARE to SET"
                self.setFocus(self.getControl(SET_LIST))
        if controlId == SET_LIST and self.getControl(SET_LIST).size() == 1:
            if self.selectedControlId == SYSTEM_WRAPLIST:
                print "- from MACHINE to TEXT"
                self.setFocus(self.getControl(TEXTLIST))
            else:
                print "- from TEXT to MACHINE"
                self.setFocus(self.getControl(SYSTEM_WRAPLIST))
        if controlId == TEXTLIST and self.getControl(TEXTLIST).size() < 2:
            if self.selectedControlId == SET_LIST:
                print "- from SET to SOFTWARE"
                self.setFocus(self.getControl(SOFTWARE_BUTTON))
            else:
                # TODO will not happen as we go from SOFTWARE TO BOTTOM CPANEL?
                print "- from SOFTWARE to SET"
                self.setFocus(self.getControl(SET_LIST))
                    
        # update controlId
        self.enter = None
        self.selectedControlId = controlId
        
    def onClick(self, controlID):
        print "--- onClick"

        if controlID in (
                SOFTWARE_BUTTON,
                SET_LIST,
                SYSTEM_WRAPLIST,
            ):
            self.run_emulator()
            
        elif controlID == TEXTLIST:
            item = self.getControl(TEXTLIST).getSelectedItem().getLabel()
            if 'Vid' in item or 'Man' in item or item[1] == ':':
                video = []
                for j in self.info:
                    for i in j:
                        if i['video']:
                            video.append( 'video: %s - %s' % (i['swl_name'],i['name']))
                        if i['manual']:
                            video.append( 'manual: %s - %s' % (i['swl_name'],i['name']))
                if len(video) == 1:
                    ret = 0
                else:
                    ret = self.dialog.select( 'Select manual or video: ', video )
                if ret == -1:
                        return
                else:
                    what, swl_name, sep, set_name = video[ret].split(' ')
                    for j in self.info:
                        for i in j:
                            if i['swl_name'] == swl_name and i['name'] == set_name:
                                if what == 'video:':
                                    video_file = i['video']['path']
                                else:
                                    manual_file = i['manual']
                                
                    if xbmc.Player().isPlayingVideo():
                        xbmc.Player().stop()
                        xbmc.sleep(500)
                    if what == 'video:':
                        xbmc.Player().play(
                            video_file,
                            windowed=True
                        )
                    else:
                        subprocess.call([self.pdfviewer, manual_file])
            elif item == 'Rec':
                text = self.dat.dat[ self.actset['swl_name'] ][ self.actset['name'] ][ 'Rec' ]
                ll = []
                for i in text.split('[CR]'):
                    print i
                    if '-' in i or i == '':
                        continue
                    x = self.ggdb.search_single(i)
                    ll.append(x)
                    print x
                self.show_context_menu()
                self.popup_gamelist(ll, 0, 'Recommended', [], [] )
            elif item == 'Series':
                x = self.ggdb.get_series(self.last[self.lastptr])
                if x:
                    self.show_context_menu()
                    self.popup_gamelist(x, 0, 'Series', [], [])
                else:
                    self.run_emulator()
            else:
                self.run_emulator()
            
        elif controlID == CONTROL_BUTTON_CONTEXT:
            self.show_context_menu(1)
            self.update_gamelist('Search')
            
        elif controlID == CONTROL_BUTTON_SETTINGS:
            __addon__.openSettings()
            self.read_settings()
        
        elif controlID == CONTROL_BUTTON_UPDATE:
            self.update()
            
        elif controlID == CONTROL_BUTTON_EXIT:
            self.exit()

        # show filter list
        elif controlID == CONTROL_BUTTON_FILTER:
            
            self.getControl(FILTER_LIST_BG).setVisible(True)
            self.getControl(FILTER_CATEGORY_LIST).setVisible(True)
            self.getControl(FILTER_CONTENT_LIST).setVisible(True)
            self.getControl(FILTER_LABEL).setVisible(True)
            self.getControl(FILTER_LABEL2).setVisible(True)
            self.getControl(FILTER_OPTIONS).setVisible(True)
            self.setFocus(self.getControl(FILTER_CATEGORY_LIST))
            
        elif controlID == CONTEXT_MENU:
            
            item = self.getControl(CONTEXT_MENU).getSelectedItem().getLabel()
            self.update_gamelist(item)
            
        # pushed GAME_LIST_OPTIONS
        elif controlID == GAME_LIST_OPTIONS:
            item = self.getControl(GAME_LIST_OPTIONS).getSelectedItem().getLabel()
            
            if item == "new search":
                keyboard = xbmc.Keyboard( '', "Search for", 0 )
                keyboard.doModal()
                if (keyboard.isConfirmed()):
                    self.searchold = keyboard.getText()
                else:
                    return
                x, pos, result_count = self.ggdb.get_searchresults(self.searchold)
                gl_label = '%d results for %s' % ( result_count, self.searchold )
                gl_options = ( 'new search', )
                
                # check how many results
                if len(x) == 0:
                    xbmc.executebuiltin('XBMC.Notification(nothing,,5000)')
                    return
                elif len(x) == 1:
                    self.searchold = None
                    self.close_gamelist()
                    self.lastptr += 1
                    self.last.insert( self.lastptr, x[0]['id'] )
                    self.select_software( self.last[self.lastptr] )
                    return
                
                # TODO no popup, but refill
                self.popup_gamelist( x, pos, gl_label, [], gl_options)
                
            # options from play status                
            elif item in ('time_played', 'last_played', 'play_count'):
                x, pos = self.ggdb.get_last_played(item)
                self.getControl(GAME_LIST).reset()
                l = []
                for i in x:
                    l.append( xbmcgui.ListItem( i['label'], str(i['id']) ) )
                self.getControl(GAME_LIST).addItems(l)
                
            elif item in ( 'name', 'year', 'publisher' ):
                self.ggdb.order = item
                context = self.getControl(CONTEXT_MENU).getSelectedItem().getLabel()
                self.update_gamelist(context)
                
        elif controlID == GAME_LIST_SORT:
            item = self.getControl(GAME_LIST_SORT).getSelectedItem().getLabel()
            
            if item == "filter: on":
                self.ggdb.use_filter = True
            elif item == "filter: off":
                self.ggdb.use_filter = False
    
            item = self.getControl(CONTEXT_MENU).getSelectedItem().getLabel()
            self.update_gamelist(item)
            
        elif controlID == FILTER_OPTIONS:
            item = self.getControl(FILTER_OPTIONS).getSelectedItem().getLabel()
            filter_category_name = self.getControl(
                        FILTER_CATEGORY_LIST
                    ).getSelectedItem().getLabel()
            for i in range( 0 , self.getControl(FILTER_CONTENT_LIST).size() ):
                f = self.getControl(FILTER_CONTENT_LIST).getListItem(i)
                f_id = f.getLabel2()
                if item == 'all':
                    f.setProperty('IsEnabled', '1')
                    if f_id in self.filter_lists[filter_category_name]:
                        self.filter_lists[filter_category_name].remove(f_id)
                elif item == 'invert':
                    if f.getProperty('IsEnabled'):
                        f.setProperty('IsEnabled', '')
                        if f_id not in self.filter_lists[filter_category_name]:
                            self.filter_lists[filter_category_name].append(f_id)
                    else:
                        f.setProperty('IsEnabled', '1')
                        if f_id in self.filter_lists[filter_category_name]:
                            self.filter_lists[filter_category_name].remove(f_id)
                elif item == 'none':
                    f.setProperty('IsEnabled', '')
                    if f_id not in self.filter_lists[filter_category_name]:
                        self.filter_lists[filter_category_name].append(f_id)
            self.setFocus(self.getControl(FILTER_CONTENT_LIST))
            
    def onAction(self, action):
        print "--- onAction"
        
        # needed for left/right exit from popup
        if self.dummy:
            print "- dummy"
            self.dummy = None
            if ( action.getId() in ACTION_MOVEMENT_LEFT
                 or action.getId() in ACTION_MOVEMENT_RIGHT
            ):
                return

        if(action.getId() == 0):
            return

        if (action.getId() in ACTION_CANCEL_DIALOG):
            
            # stop video and return
            if self.playvideo and xbmc.Player().isPlayingVideo(): 
                xbmc.Player().stop() 
                xbmc.sleep(WAIT_PLAYER) 
                return
            
            # exit only in main screen, otherwise close popup
            x = self.selectedControlId
            if x in (
                GAME_LIST, CONTEXT_MENU, GAME_LIST_OPTIONS, GAME_LIST_SORT
            ):
                self.close_gamelist()
                self.enter = True
                return
            elif x in (
                FILTER_CATEGORY_LIST, FILTER_CONTENT_LIST, FILTER_OPTIONS
            ):
                self.close_filterlist()
                self.enter = True
                return
            else:
                self.exit()
        
        # ACTION SOFTWARE_BUTTON
        if self.selectedControlId == SOFTWARE_BUTTON:
            print "- SOFTWARE_BUTTON"
                           
            if action.getId() in ACTION_MOVEMENT_RIGHT:
                self.software_move('right')

            elif action.getId() in ACTION_MOVEMENT_LEFT:
                self.software_move('left')
                    
            elif ( action.getId() in ACTION_MOVEMENT_DOWN
                   or action.getId() in ACTION_MOVEMENT_UP
                 ):
                self.show_info()
                    
            elif action.getId() in ACTION_CONTEXT:
                self.show_context_menu()
        
        # ACTION SYSTEM_WRAPLIST
        elif self.selectedControlId == SYSTEM_WRAPLIST:
            print "- MACHINE_LIST"
            
            if action.getId() in ACTION_MOVEMENT_RIGHT or action.getId() in ACTION_MOVEMENT_LEFT:
                self.system_move()
                
            elif action.getId() in ACTION_MOVEMENT_DOWN or action.getId() in ACTION_MOVEMENT_UP:
                self.show_info('machine')
            
            elif action.getId() in ACTION_CONTEXT:
                self.show_context_menu(2)
                
        elif self.selectedControlId == TEXTLIST:
                
            if action.getId() in ACTION_CONTEXT:
                self.show_context_menu()
        
        # ACTION GAME_LIST
        elif self.selectedControlId == GAME_LIST:
            print "- GAME_LIST"
            
            if action.getId() in ACTION_ENTER:
                self.gamelist_click()
    
        # ACTION FILTER_CATEGORY_LIST
        elif self.selectedControlId == FILTER_CATEGORY_LIST:
            print "- FILTER_CATEGORY_LIST"
            
            if action.getId() in ACTION_ENTER:
                self.filter_category()
                
        # ACTION FILTER_CONTENT_LIST
        elif self.selectedControlId == FILTER_CONTENT_LIST:
            print "- FILTER_CONTENT_LIST"
            
            if action.getId() in ACTION_ENTER:
                self.filter_content()
                
        # ACTION SET_LIST
        elif self.selectedControlId == SET_LIST:
            print "- SET_LIST"
            
            if action.getId() in ACTION_MOVEMENT_LEFT or action.getId() in ACTION_MOVEMENT_RIGHT:
                
                # update actual set
                pos_m = self.getControl(SYSTEM_WRAPLIST).getSelectedPosition()
                pos_s = self.getControl(SET_LIST).getSelectedPosition()
                self.actset = self.info[pos_m][pos_s]
                
                # update SYSTEM_WRAPLIST image
                # TODO should the icon be a part of set list
                # and machine wraplist shows pic from set?
                self.getControl(
                        SYSTEM_WRAPLIST
                    ).getSelectedItem().setArt( {
                            'icon' : self.get_machine_pic()
                        } )
                
                # update pics
                self.show_info('set')
                
            elif action.getId() in ACTION_MOVEMENT_DOWN or action.getId() in ACTION_MOVEMENT_UP:
                self.show_info('set')
                
            elif action.getId() in ACTION_CONTEXT:
                self.show_context_menu(2)

    def gamelist_click(self):
        
        # GAME LIST contains machines for a swl
        if 'Machines for' in self.getControl(GAME_LIST_LABEL).getLabel():
            
            # get machine shortname from skin
            machine_id = self.getControl(
                                GAME_LIST
                        ).getSelectedItem().getLabel2()
            machine_name, machine_label = self.ggdb.get_machine_name(
                                machine_id
                        )
            
            # set new image and machine label
            self.getControl(
                        SYSTEM_WRAPLIST
                ).getSelectedItem().setArt( {
                        'icon' : os.path.join(
                            self.cab_path, machine_name + '.png'
                        )
                    } )
            self.getControl(SET_LIST).getSelectedItem().setProperty(
                'Machine', machine_label
            )
            
            # save machine for set in self.info
            self.actset['machine_name'] = machine_name
            self.actset['machine_label'] = machine_label
            
            self.enter = True
            self.setFocus( self.getControl(SOFTWARE_BUTTON) )
                
        # GAME LIST contains software
        else:
    
            # get selected id
            software_id = self.getControl(
                                GAME_LIST
                        ).getSelectedItem().getLabel2()
            
            # get prev/next results and show them
            if software_id in ('prev', 'next'):
                if software_id == 'prev':
                    sid = int(
                        self.getControl(
                                GAME_LIST
                        ).getListItem(1).getLabel2()
                    )
                else:
                    size = self.getControl(GAME_LIST).size()
                    sid = int(
                        self.getControl(
                                GAME_LIST
                        ).getListItem(size-2).getLabel2()
                    )
                x, pos = self.ggdb.get_prevnext_software(
                                sid, software_id
                            )
                
                self.getControl(GAME_LIST).reset()
                l = []
                for i in x:
                    l.append(
                        xbmcgui.ListItem( i['label'], str( i['id'] ) )
                    )
                self.getControl(GAME_LIST).addItems(l)
                self.getControl(GAME_LIST).selectItem(pos)
            
            # new software selected    
            else:
                self.close_gamelist()
                software_id = int(software_id)
                # if self.lastptr == 9:
                #     del self.last[0]
                #     self.last.append( software_id )
                #     self.select_software( self.last[-1] )
                # else:
                #     self.last.insert(
                #         self.lastptr+1,
                #         software_id
                #     )
                #     del self.last[0]
                #     self.select_software( self.last[self.lastptr] )
                self.lastptr += 1
                self.last.insert( self.lastptr, software_id )
                self.select_software( self.last[self.lastptr] )
                
                    
                self.enter = True
                self.setFocus(self.getControl(SOFTWARE_BUTTON))

    def filter_category(self):
        
        # get filter category and set filter content list
        cat = self.getControl(
                    FILTER_CATEGORY_LIST
                ).getSelectedItem().getLabel()
        if cat in ( "Load Filter", "Save Filter" ):
            files = []
            for i in os.listdir( settings_folder ):
                if i[:7] == 'filter_':
                    files.append( i[7:-4] )
            
            if cat == "Load Filter":
                ret = self.dialog.select( 'Load Filter', files )
                if ret == -1:
                    return
                else:
                    self.filter_lists = utilmod.load_filter(
                        settings_folder, 'filter_' + files[ret] + '.txt'
                    )
                    c = self.ggdb.define_filter( self.filter_lists )
                    self.getControl(LABEL_STATUS).setLabel(
                        "%s filtered items" % ( c, )
                    )
                    self.act_filter = files[ret]
                self.getControl(FILTER_CONTENT_LIST).reset()
                self.getControl(FILTER_LABEL).setLabel("Select category")
                self.getControl(FILTER_LABEL2).setLabel(self.act_filter)
                self.setFocus(self.getControl(FILTER_CATEGORY_LIST))
            
            else:
                files.append('New Filter')
                ret = self.dialog.select( 'Save Filter', files )
                if ret == -1:
                    return
                elif files[ret] == 'New Filter':
                    keyboard = xbmc.Keyboard( '', "Name for Filter", 0 )
                    keyboard.doModal()
                    if (keyboard.isConfirmed()):
                        filter_filename = keyboard.getText()
                    else:
                        return
                else:
                    filter_filename = 'filter_' + files[ret] + '.txt'
                    
                # save filters
                utilmod.save_filter(
                    settings_folder,
                    'filter_' + filter_filename + '.txt',
                    self.filter_lists
                )
                self.act_filter = files[ret]
                self.getControl(FILTER_LABEL2).setLabel(self.act_filter)
                self.getControl(FILTER_LABEL).setLabel(
                    'saved ' + filter_filename
                )
        else:
            self.set_filter_content(cat)
        
    def filter_content(self):

        # switch the radio button
        filter_category_name = self.getControl(
                    FILTER_CATEGORY_LIST
                ).getSelectedItem().getLabel()
        filter_content_id = self.getControl(
                    FILTER_CONTENT_LIST
                ).getSelectedItem().getLabel2()
        
        x = self.getControl(
                    FILTER_CONTENT_LIST
                ).getSelectedItem().getProperty('IsEnabled')
        if x:
            self.getControl(
                    FILTER_CONTENT_LIST
                ).getSelectedItem().setProperty('IsEnabled', '')
            self.filter_lists[filter_category_name].append(
                    filter_content_id
                )
        else:
            self.getControl(
                    FILTER_CONTENT_LIST
                ).getSelectedItem().setProperty('IsEnabled', '1')
            self.filter_lists[filter_category_name].remove(
                    filter_content_id
                )
                
    def read_settings(self):
        
        # read in settings
        self.mame_emu = __addon__.getSetting('mame')
        self.mameini = __addon__.getSetting('mameini')
        self.mame_dir = __addon__.getSetting('mamedir')
        self.pref_country = __addon__.getSetting('pref_country')
        self.temp_dir = __addon__.getSetting('temp_path')
        self.progetto = __addon__.getSetting('progetto')
        self.aratio = __addon__.getSetting('aspectratio')
        self.playvideo = __addon__.getSetting('playvideo')
        self.datdir = __addon__.getSetting('datdir')
        self.pdfviewer = __addon__.getSetting('pdfviewer')
        
        # play videos
        if self.playvideo == 'true':
            self.playvideo = True
        else:
            self.playvideo = None
        
        self.cab_path = os.path.join(self.progetto,'cabinets/cabinets')
        
        return
    
    def close_filterlist(self, no_update=None ):
        
        # update filter
        if not no_update:
            c = self.ggdb.define_filter( self.filter_lists )
            self.getControl(LABEL_STATUS).setLabel(
                "%s filtered items" % ( c, )
            )
                
        self.getControl(FILTER_CATEGORY_LIST).setVisible(False)
        self.getControl(FILTER_CONTENT_LIST).setVisible(False)
        self.getControl(FILTER_LIST_BG).setVisible(False)
        self.getControl(FILTER_LABEL).setVisible(False)
        self.getControl(FILTER_LABEL2).setVisible(False)
        self.getControl(FILTER_OPTIONS).setVisible(False)
        return
                
    def close_gamelist(self):
    
        self.getControl(CONTEXT_MENU).setVisible(False)
        self.getControl(GAME_LIST).setVisible(False)
        self.getControl(GAME_LIST_OPTIONS).setVisible(False)
        self.getControl(GAME_LIST_SORT).setVisible(False)
        self.getControl(GAME_LIST_LABEL).setVisible(False)
        self.getControl(GAME_LIST_BG).setVisible(False)
        self.getControl(GAME_LIST_IMAGE).setVisible(False)
        return
                
    def get_diff_emulator(self, source=None, swl_name=None):
        
        if source:
            x = self.ggdb.get_emulator( source=source )
            text = 'source %s' % ( source, )
        else:
            x = self.ggdb.get_emulator( swl_name=swl_name )
            text = 'swl %s' % ( swl_name, )
            
        elist = x.keys() + [ 'Kodi Retroplayer', 'Different emulator' ]
        
        ret = self.dialog.select( 'Emulator: '+text, elist )
        if ret == -1:
            return
        
        if elist[ret] == 'Different emulator':
            
            x = self.ggdb.get_all_emulators()
            if x:
                dlist = [ 'New emulator' ] + x.keys()
                ret2 = self.dialog.select( 'Emulator: '+text, dlist )
                if dlist[ret2] == 'New emulator':
                    if source:
                        self.get_new_emulator( source=source )
                    else:
                        self.get_new_emulator( swl_name=swl_name )
                else:
                    if source:
                        self.ggdb.connect_emulator(
                            x[dlist[ret2]]['id'], # id of emu entry
                            source=source
                        )
                    else:
                        self.ggdb.connect_emulator(
                            x[dlist[ret2]]['id'], # id of emu entry
                            swl_name=swl_name
                        )
                    self.run_emulator( x[ dlist[ret2] ] )
                    return
                
            elif source:
                self.get_new_emulator( source=source )
            else:
                self.get_new_emulator( swl_name=swl_name )
                
        elif elist[ret] == "Kodi Retroplayer":
            self.run_emulator('kodi')
        else:
            self.run_emulator( x[ elist[ret] ] )
            
        return
    
    def get_new_emulator( self, source=None, swl_name=None ):
        
        # get filename
        fn = self.dialog.browse( 1, 'Emulator executable', 'files' )
        if not fn:
            return
        
        # get working dir
        wd = self.dialog.browse( 0, 'Working directory', 'files' )
        if not wd:
            return
        
        # zip support
        zip_support = self.dialog.yesno( 'Zip support?', 'means no zip uncompress' )
        print zip_support
        
        # name
        name = self.dialog.input('Name of emulator')
        if not name:
            return
        
        if source:
            self.ggdb.save_emulator( name, fn, wd, zip_support, source=source )
        else:
            self.ggdb.save_emulator( name, fn, wd, zip_support, swl_name=swl_name )
        
        self.run_emulator( {
                'exe' : fn,
                'dir' : wd,
                'zip' : zip_support
            }
        )
        
        return
    
    def update(self):
        
        # close db before update
        if self.ggdb:
            self.ggdb.close_db()
        
        # update database
        self.getControl(LABEL_STATUS).setLabel('downloading database...')
        # sanity check
        if not os.path.exists(settings_folder):
                os.mkdir(settings_folder)
        # TODO lookup download progress bar
        # TODO make backup of db file, when except then restore it
        # otherwise delete
        
        try:
            response = urllib2.urlopen(
                            'http://umsa.info/umsa_db.zip',
                            timeout=20
                        )
            answer = response.read()
            fout = open( os.path.join( settings_folder, 'umsa_db.zip' ), "wb")
            fout.write(answer)
            fout.close()
            # unzip and remove zipfile
            zfile = zipfile.ZipFile(
                        os.path.join( settings_folder, 'umsa_db.zip' ) )
            zfile.extractall(settings_folder)
            os.remove(os.path.join( settings_folder, 'umsa_db.zip' ) )
        except:
            xbmc.executebuiltin(
                'XBMC.Notification(update:,problem downloading database,5000)'
            )
        
        # connect
        self.ggdb = DBMod(
            settings_folder,
            self.filter_lists,
            self.pref_country,
        )
        self.getControl(LABEL_STATUS).setLabel('')
        
    def update_gamelist(self, item):
        
        if item == 'Different emulator':
            if self.actset['swl_name'] == 'mame':
                self.get_diff_emulator( source=self.actset['source'] )
            else:
                self.get_diff_emulator( swl_name=self.actset['swl_name'] )
            return
            
        elif item == "Complete list":
            x, pos, count = self.ggdb.get_by_software(
                                self.actset['id']
                            )
            gl_label = "Complete list (%d)" % (count,)
            gl_options = ( 'name', 'year', 'publisher' )
            
        elif item == "Software list":
            x, pos, count = self.ggdb.get_by_swl(
                self.actset['swl_name'],
                self.actset['id'],
            )
            gl_label = "swl: %s (%d)" % (
                self.actset['swl_name'], count
            )
            gl_options = ("all swls", "get connected swls")
            
        elif item == "Category":
            x, pos, count = self.ggdb.get_by_cat(
                self.actset['category'], self.actset['id']
            )
            gl_label = "Category: %s (%d)" % (
                self.actset['category'], count 
            )
            gl_options = ( 'name', 'year', 'publisher' )
            
        elif item == "Year":
            x, pos, count = self.ggdb.get_by_year(
                self.actset['year'],
                self.actset['id']
            )
            gl_label = "Year: %s (%d)" % ( self.actset['year'], count )
            gl_options = ( '±0', '±1', '±2' )
            
        elif item == "Publisher":
            x, pos, count = self.ggdb.get_by_maker(
                self.actset['publisher'],
                self.actset['id']
            )        
            gl_label = "Publisher: %s (%d)" % ( self.actset['publisher'], count )
            gl_options = ( 'name', 'year', 'publisher' )
            
        elif item == "Play status":
            x, pos = self.ggdb.get_last_played("time_played")
            gl_label = ("play status")
            gl_options = ('time_played', 'last_played', 'play_count')
            
        elif item == "Select machine":
            x, pos = self.ggdb.get_machines(
                self.actset['swl_name'], self.actset['machine_name']
            )
            gl_label = 'Machines for swl %s (%d)' % (
                self.actset['swl_name'], len(x)
            )
            gl_options = ( 'name', 'year', 'publisher' )
            
        elif item == "MAME Source":
            x, pos, result_count = self.ggdb.get_software_for_source(
                self.actset['id'], self.actset['source']
            )
            gl_label = "source: %s (%d)" % ( self.actset['source'], result_count )
            gl_options = ( 'name', 'year', 'publisher' )
            
        elif item == "Screensaver":
            x = []            
            for i in utilmod.load_lastsaver( settings_folder ):
                y = self.ggdb.get_info_by_set_and_swl( i[0], i[1] )
                x.append(
                    { 'label' : y['label'],
                      'id'    : str(y['software_id']) }
                )
            gl_label = 'last screensaver session'
            gl_options = ( 'name', 'year', 'publisher' )
            pos = 0
            
        elif item == "Search":
            if not self.searchold:
                keyboard = xbmc.Keyboard( '', "Search for", 0 )
                keyboard.doModal()
                if (keyboard.isConfirmed()):
                    self.searchold = keyboard.getText()
                else:
                    self.getControl(LABEL_STATUS).setLabel('user canceled')
                    return
            x, pos, result_count = self.ggdb.get_searchresults(self.searchold)
            gl_label = '%d results for %s' % ( result_count, self.searchold )
            gl_options = ( 'new search', )
        
        # check how many results
        if len(x) == 0:
            if item == "Search":
                self.searchold = None
            xbmc.executebuiltin('XBMC.Notification(nothing,,5000)')
            return
        elif len(x) == 1:
            if item == "Search":
                self.searchold = None
            xbmc.executebuiltin('XBMC.Notification(one hit,,5000)')
            self.close_gamelist()
            self.lastptr += 1
            self.last.insert( self.lastptr, x[0]['id'] )
            self.select_software( self.last[self.lastptr] )
            self.setFocus(self.getControl(SOFTWARE_BUTTON))
            return
        
        if self.ggdb.use_filter:
            fl = [ 'filter: on', 'filter: off' ]
        else:
            fl = [ 'filter: off', 'filter: on' ]
                
        self.popup_gamelist(
            x, pos, gl_label, fl, gl_options
        )
        
        return
    
    def popup_gamelist(self, gamelist, pos, label, sort, options):
        
        xl = []
        for i in gamelist:
            x = xbmcgui.ListItem( i['label'], str(i['id']) )
            if 'swl' in i and i['swl'] == 'mame':
                x.setArt( { 'icon' : os.path.join(
                    self.progetto, 'snap/snap', i['setname']+'.png'
                ) } )
            elif 'swl' in i:
                x.setArt( { 'icon' : os.path.join(
                    self.progetto, 'snap/'+i['swl'], i['setname']+'.png'
                ) } )
            xl.append(x)

        self.getControl(GAME_LIST_LABEL).setLabel(label)
        self.getControl(GAME_LIST_OPTIONS).reset()
        self.getControl(GAME_LIST_OPTIONS).addItems(options)
        self.getControl(GAME_LIST_SORT).reset()
        self.getControl(GAME_LIST_SORT).addItems(sort)
        self.getControl(GAME_LIST).reset()
        self.getControl(GAME_LIST).addItems(xl)
        self.getControl(GAME_LIST).selectItem(pos)
        self.setFocus(self.getControl(GAME_LIST))
        
        return
    
    def system_move(self):
        
        pos_m = self.getControl(SYSTEM_WRAPLIST).getSelectedPosition()
        self.fill_set_list(pos_m)
        
        xbmc.sleep(WAIT_GUI)
        pos_s = self.getControl(SET_LIST).getSelectedPosition()
        self.actset = self.info[pos_m][pos_s]
        
        self.show_info('machine')
            
        return
            
    def software_move(self, direction):
        
        # left
        if direction == 'left' and self.lastptr >= 1:
            self.lastptr -= 1
            self.select_software( self.last[self.lastptr] )
            return
        elif direction == 'right':
        # right
        # if self.lastptr == 9:
        #     del self.last[0]
        #     self.last.append( self.ggdb.get_random_id() )
        #     self.select_software( self.last[-1] )
        # else:
            self.lastptr += 1
            if self.lastptr >= len(self.last):
                self.last.append( self.ggdb.get_random_id() )
            self.select_software( self.last[self.lastptr] )
        
        return
    
    def show_context_menu(self, pos=0):
        
        if self.actset['swl_name'] == 'mame':
            x = [ "MAME Source" ]
        else:
            x = [ "Select machine", "Software list" ]
            
        cm = [ 'Complete list', 'Search', ] + x + [
            'Category',
            'Publisher',
            'Year',
            'Play status',
            'Screensaver',
            '-----------',
            #'Set options for set',
            'Different emulator',
            #'Add to Favorites'
        ]
        
        self.getControl(CONTEXT_MENU).reset()
        self.getControl(CONTEXT_MENU).addItems(cm)
        self.getControl(CONTEXT_MENU).selectItem(pos)
        
        self.getControl(CONTEXT_MENU).setVisible(True)
        self.getControl(GAME_LIST_BG).setVisible(True)
        self.getControl(GAME_LIST_LABEL).setVisible(True)
        self.getControl(GAME_LIST_OPTIONS).setVisible(True)
        self.getControl(GAME_LIST_SORT).setVisible(True)
        self.getControl(GAME_LIST).setVisible(True)
        self.getControl(GAME_LIST_IMAGE).setVisible(True)
        
        # TODO maybe stop the time and when its less than
        # say 5 secs then select game_list if content
        
        # set focus to game list when it has content
        # if self.getControl(GAME_LIST).size() == 0:
        #     self.setFocus( self.getControl(CONTEXT_MENU) )
        # else:
        #     self.setFocus( self.getControl(GAME_LIST) )
        self.setFocus( self.getControl(CONTEXT_MENU) )
        
        return
            
    def set_filter_content(self, cat):
        
        self.getControl(FILTER_CONTENT_LIST).reset()
        
        a = []
        for e in self.ggdb.get_all_dbentries(cat):
            
            x = xbmcgui.ListItem( "%s (%s)" % (e[1], e[2]) , str(e[0]) )
            
            if str(e[0]) in self.filter_lists[cat]:
                x.setProperty('IsEnabled', '')
            else:
                x.setProperty('IsEnabled', '1')
            
            a.append(x)
        
        self.getControl(FILTER_CONTENT_LIST).addItems(a)
        self.getControl(FILTER_LABEL).setLabel(cat)
        self.setFocus(self.getControl(FILTER_CONTENT_LIST))
        
        return
    
    def get_machine_pic(self, use_set=None ):
        
        if use_set:
            actset = use_set
        else:
            actset = self.actset
        
        # set machine pic for swl
        pic = os.path.join(
            self.cab_path,
            actset['machine_name']+'.png'
        )
        # change when no swl
        if actset['machine_name'] == 'mame':
            if actset['is_machine']:
                pic = os.path.join(
                    self.cab_path,
                    actset['name']+'.png'
                )
            elif actset['category'] == 'Electromechanical / Pinball':
                pic = os.path.join(
                    media_folder,
                    "pinball.png"
                )
            elif actset['category'] in (
                    'Electromechanical / Reels',
                    'Casino / Reels'
                ):
                pic = os.path.join(
                    media_folder,
                    "reels.png"
                )
            else:
                pic = os.path.join(
                    media_folder,
                    "arcade.png"
                )
        return pic
    
    def fill_set_list(self, pos):
        
        self.getControl(SET_LIST).reset()
        length = len(self.info[pos])
        count = 0
        
        # shadow pointer
        if length == 1:
            self.getControl(SHADOW_SET).setVisible(False)
        else:
            self.getControl(SHADOW_SET).setVisible(True)
        
        l = []    
        for i in self.info[pos]:
            
            count += 1
            label = ""
            x = xbmcgui.ListItem()
            
            # set label
            if i['category'] != 'Not Classified' or i['nplayers'] != '???':
                if i['detail']:
                    label = '%s - %s, %s' % (
                            i['detail'],
                            i['category'],
                            i['nplayers'],
                    )
                else:
                    label = '%s, %s' % (
                            i['category'],
                            i['nplayers'],
                    )
            elif i['detail']:
                label = '%s' % ( i['detail'], )
            
            # add swl when not mame    
            if i['swl_name'] != 'mame':
                label = '%s (%s)' % ( label, i['swl_name'] )
                
            # add * as a sign for a clone
            clone = ''
            if i['clone']:
                clone = '*'
            
            # add count to label
            if length > 1:
                label = '%s (%s%d/%d)' % (
                    label,
                    clone,
                    count,
                    length
                )
            
            x.setLabel(label)
            
            # set other labels in skin over setlist
            x.setProperty(
                # strip detail from gamename
                'Titel', i['gamename'][:len( i['gamename'] )
                                       - len( i['detail'] )].strip()
            )
            x.setProperty( 'Year', i['year'] )
            x.setProperty( 'Maker', i['publisher'] )
            x.setProperty( 'Machine', i['machine_label'] )
            
            l.append(x)
            
        self.getControl(SET_LIST).addItems(l)
                
        return
    
    # get all machines and sets for software_id and fill skin
    def select_software(self, software_id):
        
        time1 = time.time()
        print "--------------------------------"
        print "-- SELECT SOFTWARE: %d" % ( software_id, )
        
        self.getControl(LABEL_STATUS).setLabel('loading software...')
        self.getControl(SYSTEM_WRAPLIST).reset()
        self.getControl(SET_LIST).reset()
        #self.getControl(IMAGE_BIG_LIST).reset()
        #self.getControl(IMAGE_LIST).reset()
        
        # stop video
        if xbmc.Player().isPlayingVideo():
            xbmc.Player().stop()
            xbmc.sleep(100)
        
        # get infos
        self.info, pos_machine, pos_set = self.ggdb.get_all_for_software(
                software_id
        )
        
        # TODO should never happen
        if len(self.info) == 0:
            print "- software error with %d" % ( software_id, )
            xbmc.executebuiltin(
                'XBMC.Notification(fatal software error,id: %s,10000)' % (
                        software_id
                    )
                )
            
        no_systems = len(self.info)
        no_sets = len(self.info[pos_machine])
        self.actset = self.info[pos_machine][pos_set]

        # shadow pointers
        if no_systems == 1:
            self.getControl(SHADOW_MACHINE).setVisible(False)
        else:
            self.getControl(SHADOW_MACHINE).setVisible(True)
            
        # fill SET_LIST
        self.fill_set_list(pos_machine)
        self.getControl(SET_LIST).selectItem(pos_set)
            
        # set border for systems
        if no_systems == 1:
            self.getControl(SYSTEM_BORDER).setWidth(124)
            self.getControl(SYSTEM_BORDER).setImage("border1.png")
            self.getControl(MACHINE_SEP1).setVisible(False)
            self.getControl(MACHINE_SEP2).setVisible(False)
            self.getControl(MACHINE_SEP3).setVisible(False)
            self.getControl(MACHINE_PLUS).setVisible(False)
        elif no_systems == 2:
            self.getControl(SYSTEM_BORDER).setWidth(246)
            self.getControl(SYSTEM_BORDER).setImage("border2.png")
            self.getControl(MACHINE_SEP1).setVisible(True)
            self.getControl(MACHINE_SEP2).setVisible(False)
            self.getControl(MACHINE_SEP3).setVisible(False)
            self.getControl(MACHINE_PLUS).setVisible(False)
        elif no_systems == 3:
            self.getControl(SYSTEM_BORDER).setWidth(368)
            self.getControl(SYSTEM_BORDER).setImage("border3.png")
            self.getControl(MACHINE_SEP1).setVisible(True)
            self.getControl(MACHINE_SEP2).setVisible(True)
            self.getControl(MACHINE_SEP3).setVisible(False)
            self.getControl(MACHINE_PLUS).setVisible(False)
        else:
            self.getControl(SYSTEM_BORDER).setWidth(490)
            self.getControl(SYSTEM_BORDER).setImage("border4.png")
            self.getControl(MACHINE_SEP1).setVisible(True)
            self.getControl(MACHINE_SEP2).setVisible(True)
            self.getControl(MACHINE_SEP3).setVisible(True)
            
        # set width for wraplist
        if no_systems > 4:
            self.getControl(SYSTEM_WRAPLIST).setWidth(480)
            self.getControl(MACHINE_PLUS).setVisible(True)
        else:
            self.getControl(SYSTEM_WRAPLIST).setWidth(no_systems*120)
            
        # fill SYSTEM_WRAPLIST
        x = 0
        l = []
        for i in self.info:

            # check if we are at selected machine
            # to use the correct selected set
            set_no = 0
            if pos_machine == x:
                set_no = pos_set
            x += 1
            
            # set picture
            y = xbmcgui.ListItem()
            y.setArt( {
                'icon' : self.get_machine_pic( use_set = i[set_no])
            } )
            l.append(y)
            
        self.getControl(SYSTEM_WRAPLIST).addItems(l)
        self.getControl(SYSTEM_WRAPLIST).selectItem(pos_machine)
        
        # fill picture lists
        self.search_pics()
        # show pics and dat
        self.show_info()
        
        print "-set no. machines"
        # set number of machines
        if no_systems > 4:
            self.getControl(LABEL_STATUS).setLabel(
                str( len( self.info ) ) + ' machines' )
        else:
            self.getControl(LABEL_STATUS).setLabel('')
        
        print "-done"
        time2 = time.time()
        #xbmc.sleep(WAIT_GUI)
        print "- select_software complete  %0.3f ms" % ( (time2-time1)*1000.0 )      
        return
    
    def search_pics(self):
        time1 = time.time()
        print "-- SEARCH_PICS"

        # TODO speed up
        # - really scan all files under progetto_path and save under userdata
        # - longterm idea: make threaded
        
        # setting info text 
        self.getControl(LABEL_STATUS).setLabel('search pictures...')
        
        # set image paths progetto datfile style
        left_list = [
            os.path.join(self.progetto, 'snap/snap'),
            os.path.join(self.progetto, 'titles/titles'),
            os.path.join(self.progetto, 'howto/howto'),
        ]
        right_list = [
            'cabinets/cabinets/',
            'logo/logo/'
            'cpanel/cpanel/',
            'artpreview/artpreview/',
            'flyers/flyers/',
            'marquees/marquees/',
            'cabdevs/cabdevs/',
            'pcb/pcb/',
        ]
        
        # go over machines
        for m in self.info:

            # go over all sets in machine
            for s in m:
                
                s['video'] = None
                s['manual'] = None
                s['pics_left'] = []
                s['pics_right'] = []
                
                # check video only when turned on
                if self.playvideo:
                    if s['swl_name'] == 'mame':
                        vpath = os.path.join( self.progetto, 'videosnaps/videosnaps/' )
                    else:
                        vpath = os.path.join(
                            self.progetto,
                            'videosnaps/' + s['swl_name'] + '/'
                        )
                    x = vpath + s['name'] + '.mp4'
                    if os.path.isfile(x):
                        s['video'] = {
                            'path'   : x,
                            'played' : None
                        }
                        
                # check manual
                if s['swl_name'] == 'mame':
                    manual_path = os.path.join( self.progetto, 'manuals/manuals/' )
                else:
                    manual_path = os.path.join(
                        self.progetto, 'manuals/' + s['swl_name'] + '/'
                    )
                x = manual_path + s['name'] + '.pdf'
                if os.path.isfile(x):
                    s['manual'] = x
                
                # check pics
                # if mame use standard paths
                rl = None
                ll = None
                if s['swl_name'] == 'mame':
                    rl = right_list
                    ll = left_list
                # change path for swl sets                
                else:
                    rl = [ 'covers/' + s['swl_name'] + '/' ]
                    ll = [
                        os.path.join(self.progetto, 'snap/' + s['swl_name']),
                        os.path.join(self.progetto, 'titles/' + s['swl_name'])
                    ]
                # right side = covers, flyers, ...
                for i in rl:
                    image = os.path.join(self.progetto, i + s['name'] + '.png')
                    if os.path.isfile(image):
                        art = os.path.dirname(image).split('/')[-2]
                        x = xbmcgui.ListItem()
                        x.setLabel(
                            '%s: %s (%s)' % (
                                art, s['detail'], s['swl_name']
                            )
                        )
                        x.setProperty(
                            'detail', '%s: %s %s' % (
                                art, s['swl_name'] , s['detail']
                            )
                        )
                        x.setArt( { 'icon' : image } )
                        s['pics_right'].append(x)
                
                # left side = snaps, titles
                imagelist = []
                for i in ll:
                    newimage = os.path.join( i, s['name'] + '.png' )
                    if os.path.isfile(newimage):
                        imagelist.append( newimage )
                
                # additional mame snap path
                # TODO: has to be refreshed after emu run
                if s['swl_name'] == 'mame':
                    newpath = os.path.join(
                        self.mame_ini['snapshot_directory'],
                        s['name']
                    )
                else:
                    newpath = os.path.join(
                        self.mame_ini['snapshot_directory'],
                        s['swl_name'], s['name']
                    )
                if os.path.isdir(newpath):
                    for ni in os.listdir(newpath):
                        imagelist.append( os.path.join ( newpath, ni ) )
                
                # check all images and set options
                for image in imagelist:
                    if os.path.isfile(image):
                        art = os.path.dirname(image).split('/')[-2]
                        x = xbmcgui.ListItem()
                        x.setLabel(
                            '%s: %s (%s)' % (
                                art, s['detail'], s['swl_name']
                            )
                        )
                        x.setArt( { 'icon' : image } )

                        # label to later set
                        x.setProperty(
                            'detail', '%s: %s %s' % (
                                art, s['swl_name'] , s['detail']
                            )
                        )

                        # TODO: move to dbmod so screensaver can also use it
                        # damn must be in something with import xbmcgui
                        
                        # set 3:4 for vert, and aspect keep for lcd
                        if s['display_rotation'] in [ 90, 270 ]:
                            x.setProperty('Vertical', '1')
                            x.setProperty('Horizontal', '')
                            x.setProperty('NotScaled', '')
                        else:
                            x.setProperty('Vertical', '')
                            x.setProperty('Horizontal', '1')
                            x.setProperty('NotScaled', '')
                        # TODO: enhance list
                        #       check display_type
                        #   problem is that set is not lcd, but machine gameboy!
                        #   fetch display type for s['swl_system_id']
                        if s['display_type'] == 'lcd' or s['category'] in (
                                'Electromechanical / Pinball', 'Handheld Game'
                            ) or s['swl_name'] in (
                                'gameboy'
                            ):
                            x.setProperty('Vertical', '')
                            x.setProperty('Horizontal', '')
                            x.setProperty('NotScaled', '1')
                        s['pics_left'].append(x)

        time2 = time.time()
        print "- search_pics  %0.3f ms" % ( (time2-time1)*1000.0 )
        return
    
    # art, video and dats
    def show_info(self, howmuch='all' ):
        print "-- SHOW_PICS_AND_DAT: %s" % (howmuch,)
        
        # TODO
        # - see if we can check tab key press, cant go back from fullscreen video
        # - randomness is in, but actual set is not first.
        # - make new blank with no pics < use fallback in layout xml
        # - already done? check
        #  !IsEmpty as visible flag for multiimage so no blank is needed, try it
        #       <visible>!IsEmpty(ListItem.Property(videosizesmall))</visible>
        
        #print "-clean"
        # clean the image lists
        self.getControl(IMAGE_BIG_LIST).reset()
        x = xbmcgui.ListItem()
        x.setProperty('NotEnabled', '1')
        x.setArt( { 'icon' : 'blank.png' } )
        self.getControl(IMAGE_BIG_LIST).addItem(x)
        
        self.getControl(IMAGE_LIST).reset()
        #x = xbmcgui.ListItem()
        #self.getControl(IMAGE_LIST).addItem(x)
        
        #print "-create list"
        # create list regarding whats requests in howmuch
        # TODO: not nice?
        rlist = []
        llist = []
        video = []
        if howmuch == 'set':
            # if self.actset['video']:
            #     video.append( self.actset['video']['path'] )
            rlist = self.actset['pics_right']
            llist = self.actset['pics_left']
            detail = self.actset['detail']
        elif howmuch == 'machine':
            for i in self.info[self.getControl(SYSTEM_WRAPLIST).getSelectedPosition()]:
                # if i['video']:
                #     video.append( i['video']['path'] )
                rlist += i['pics_right']
                llist += i['pics_left']
        else: # all
            for j in self.info:
                for i in j:
                    # if i['video']:
                    #     video.append( i['video']['path'] )
                    rlist += i['pics_right']
                    llist += i['pics_left']
        
        #print "-fill pic right"
        # fill list for pictures
        if len(rlist) > 0:
            self.getControl(IMAGE_BIG_LIST).reset()
            random.shuffle(rlist)
            
            # set count/sets
            count = 1
            ll = []
            for i in rlist:
                # get detail from setlist property and set label new
                l = i.getProperty('detail')
                i.setLabel( '%s (%d/%d)' % (
                                l,
                                count,
                                len(rlist)
                            )
                )
                ll.append( i )
                count += 1
            self.getControl(IMAGE_BIG_LIST).addItems(ll)
            
        #print "-fill pic left"
        if len(llist) > 0:
            self.getControl(IMAGE_LIST).reset()
            random.shuffle(llist)
            
            # set count/sets
            count = 1
            ll = []
            for i in llist:
                # get detail from setlist property and set label new
                l = i.getProperty('detail')
                i.setLabel( '%s (%d/%d)' % (
                                l,
                                count,
                                len(llist)
                            )
                )
                ll.append( i )
                count += 1
            self.getControl(IMAGE_LIST).addItems(ll)
            
        #print "-show dat info"
        # show infos from datfiles only when changed
        if self.oldset == ( self.actset['swl_name'], self.actset['name'] ):
            #print "- detected same swl and set"
            return
        
        self.getControl(TEXTLIST).reset()
        
        # play status
        # TODO: atm only for set, expand to machine and sotware
        never_played = None
        if self.actset['last_played']:
            text = '%s - %s, %s*' % (
                self.actset['last_played']['last_nice'],
                self.actset['last_played']['time_played'],
                self.actset['last_played']['play_count']
            )
        else:
            text = 'never played'
            never_played = True
        # TODO: move check for series to select_software
        # so it's only gets executed once
        # check for series
        series_int_flag = None
        series = self.ggdb.check_series( self.last[self.lastptr] )
        if series:
            text += "[CR]is part of a series (%s)" % (series,)
            series_int_flag = True
            
        ll = []
        v_flag = 0
        m_flag = 0
        print "-- checking vidman"
        for i in self.info:
            for j in i:
                if j['video']:
                    v_flag += 1
                if j['manual']:
                    m_flag += 1
        label = ''
        if m_flag > 1:
            if v_flag > 1:
                label = 'V:%d/M:%d' % (v_flag, m_flag)
            elif v_flag == 1:
                label = 'Vid/M:%d' % (m_flag,)
            else:
                label = 'Manual:%d' % (m_flag,)
        elif m_flag == 1:
            if v_flag > 1:
                label = 'V:%d/Man' % (v_flag)
            elif v_flag == 1:
                label = 'Vid/Man'
            else:
                label = 'Manual'
        else:
            if v_flag > 1:
                label = 'Video:%d' % (v_flag)
            elif v_flag == 1:
                label = 'Video'
            else:
                label = 'Internal'
        
        if label == 'Internal' and never_played:
            pass
        else:
            x = xbmcgui.ListItem()
            x.setLabel(label)
            x.setProperty(
                'text',
                text
            )
            ll.append(x)
            
        count = 1
        series_flag = None
        if self.actset['swl_name'] in self.dat.dat:
            if self.actset['name'] in self.dat.dat[self.actset['swl_name']]:
                
                for k in sorted(
                        self.dat.dat[ self.actset['swl_name'] ][ self.actset['name'] ].keys()
                    ):
                    if k == 'Contribute':
                        continue
                    elif k == 'Series':
                        series_flag = True
                    x = xbmcgui.ListItem()
                    x.setLabel(k)
                    x.setProperty(
                        'text',
                        self.dat.dat[ self.actset['swl_name']][ self.actset['name']][k]
                    )
                    ll.append(x)
                    count += 1
        if not series_flag and series_int_flag:
            x = xbmcgui.ListItem()
            x.setLabel('Series')
            x.setProperty(
                'text',
                'internal series detected'
            )
            ll.append(x)
            count += 1
                    
        self.getControl(TEXTLIST).addItems(ll)
                    
        # shadow pointer
        if count > 1:
            self.getControl(SHADOW_DAT).setVisible(True)
        else:
            self.getControl(SHADOW_DAT).setVisible(False)
        
        # remember actual swl and set
        self.oldset = ( self.actset['swl_name'], self.actset['name'] )
        
        #print "-pics and dats done"
        
        return
    
    def find_roms(self, swl_name, set_name):
        
        if swl_name == 'mame':
            l = set_name + '.zip'
        else:
            l = swl_name + '/' + set_name + '.zip'
    
        for p in self.mame_ini['rompath']:
            
            z = os.path.join( p, l )
            
            if os.path.isfile( z ):
                return z
            
        return None
    
    def extract_rom(self, rom_file, swl_name, set_name ):
        
        xbmc.executebuiltin(
                'XBMC.Notification(extracting rom,,3000)'
        )
        folder = os.path.join( self.temp_dir, swl_name + '_' + set_name )
        
        # only extract when folder does not exists
        x = True
        if os.path.exists( folder ):
            x = None
        else:
            os.mkdir( folder )
            
        zfile = zipfile.ZipFile( rom_file )
        zfiles = zfile.namelist()
        
        # dialog when more than one file
        if len(zfiles) > 1:
            # TODO add: create single rom
            wf = self.dialog.select( 'Select file: ', zfiles )
            nf = zfiles[wf]
        else:
            wf = 0
            nf = zfiles[wf]
            
        if x:
            zfile.extractall( folder )
            
        # hack for snes higan emulator
        # renaming to .sfc
        if swl_name == 'snes' and nf[-4:] != '.sfc':
            new_fn = nf + '.sfc'
            os.rename(
                os.path.join( folder, nf ),
                os.path.join( folder, new_fn )
            )
            zfiles[0] = new_fn
        elif swl_name == 'gameboy' and nf[-4:] != '.gb':
            new_fn = nf + '.gb'
            os.rename(
                os.path.join( folder, nf ),
                os.path.join( folder, new_fn )
            )
            zfiles[0] = new_fn
        elif swl_name == 'gbcolor' and nf[-4:] != '.gbc':
            new_fn = nf + '.gbc'
            os.rename(
                os.path.join( folder, nf ),
                os.path.join( folder, new_fn )
            )
            zfiles[0] = new_fn
            
        if wf != 0:
            zfiles[wf] = zfiles[0]
            zfiles[0] = nf
        
        return folder, zfiles
    
    def run_emulator(self, diff_emu=None):
        
        # local vars
        path = None     # working directory
        emu = ""        # emulator to start
        params = ""     # parameters
        
        # different emulator than mame
        if diff_emu:
            
            rom_file = self.find_roms(
                self.actset['swl_name'], self.actset['name']
            )
            if not rom_file and self.actset['clone']:
                rom_file = self.find_roms(
                        self.actset['swl_name'],
                        self.ggdb.get_set_name( self.actset['clone'] )
                )
            if not rom_file:
                xbmc.executebuiltin(
                        'XBMC.Notification(rom not found,,3000)'
                )
                rom_file = ''
            
            if diff_emu == "kodi":
                
                # TODO not tested
                game_item = xbmcgui.ListItem(rom_file, "0", "", "")
                if xbmc.Player().isPlaying():
                    xbmc.Player().stop()
                    xbmc.sleep(100)
                xbmc.sleep(500)
                xbmc.Player().play( rom_file, game_item )
                return
                
            if not diff_emu['zip']:
                
                folder, files = self.extract_rom(
                    rom_file, self.actset['swl_name'], self.actset['name']
                )
                emu = '%s "%s"' % (
                    diff_emu['exe'],
                    os.path.join( folder, files[0] )
                )
                
            else:
                
                emu = '%s %s' % (
                    diff_emu['exe'],
                    rom_file
                )
                    
            path = diff_emu['dir']
                
        # swl is mame
        elif self.actset['swl_name'] == 'mame':
            
            # path = os.path.dirname(self.mame_emu)
            path = self.mame_dir
            emu = '%s %s' % (self.mame_emu, self.actset['name'])
            # emu = '%s %s' % (os.path.basename(self.mame_emu), self.actset['name'])
            # if 'linux' in sys.platform:
            #     emu = './' + emu
                
        # swl with mame
        else:
            # get cmd options
            machine = self.actset['machine_name']
            cmd_line = self.ggdb.get_cmd_line_options(
                self.actset['id'],
                self.actset['name'],
                machine,
                self.actset['swl_name'],
            )
            # path = os.path.dirname(self.mame_emu)
            path = self.mame_dir
            emu = '%s %s' % (self.mame_emu, cmd_line)
            # emu = '%s %s' % (os.path.basename(self.mame_emu), cmd_line)
            # if 'linux' in sys.platform:
            #     emu = './' + emu
        
        # stop playing video or pause audio
        # TODO: maybe also set cmd option -window as video is playing
        if xbmc.Player().isPlayingVideo() and self.playvideo:
            xbmc.Player().stop()
        elif xbmc.Player().isPlayingAudio():
            xbmc.Player().pause()
            
        # cd working dir and remember current directory
        if path:
            directory = os.getcwd()
            os.chdir(path)
        
        oldlabel = self.getControl(LABEL_STATUS).getLabel()
        self.getControl(LABEL_STATUS).setLabel("emulator is running...")
        # TODO: make popup with button to stop emulation
        
        # remember start time
        start = time.time()
        
        # start emulator
        #print emu, params
        proc = subprocess.Popen(
                    [emu, params],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=True
                )
        (out, err) = proc.communicate()
        
        # remember end time
        end = time.time()
        self.getControl(LABEL_STATUS).setLabel( oldlabel )
            
        # switch path back to original directory
        if path:
            os.chdir(directory)
            
        # TODO check if works when video runs
        # unpause audio again
        if xbmc.Player().isPlayingAudio():
            xbmc.Player().pause()
        
        # show emulator output
        if out.find('Average speed:') == -1:
            
            # errors go to TEXTLIST
            x = True
            # check if item already exists
            for i in range( 0 , self.getControl(TEXTLIST).size() ):
                y = self.getControl(TEXTLIST).getListItem(i)
                if y.getLabel() == 'Emulator output':
                    x = False
                    break
            # not: then create
            if x and ( out or err ):
                y = xbmcgui.ListItem()
                y.setLabel('Emulator output')
                self.getControl(TEXTLIST).addItem(y)
                
            if out or err:
                y.setProperty(
                    'text',
                    "Command line:\n" + emu + "\nError:\n" + err + out
                )
                self.getControl(TEXTLIST).selectItem(
                    self.getControl(TEXTLIST).size() - 1
                )
                out = "error"
            else:
                out = "nothing"
        else:
            # pretty output from mame
            out = out[out.find('Average speed:')+15:]
        xbmc.executebuiltin(
                'XBMC.Notification(emulator says:,%s,3000)' % ( out )
        )
            
        # write time, date to status db
        if int(end-start) > 60:
            self.ggdb.write_status_after_play(self.actset['id'], int(end-start))
            
        # move snapshots from machine to swl dir
        if ( self.actset['swl_name'] != 'mame'
             and not diff_emu
             and self.actset['swl_name'] != machine
           ):
            
            original_dir = os.path.join(
                self.mame_ini['snapshot_directory'],
                machine,
                self.actset['name']
            )
            
            # if new snaps dir exists, then snaps where taken
            if os.path.isdir(original_dir):
                
                swl_dir = os.path.join(
                    self.mame_ini['snapshot_directory'],
                    self.actset['swl_name']
                )
                set_dir = os.path.join(
                    self.mame_ini['snapshot_directory'],
                    self.actset['swl_name'],
                    self.actset['name']
                )
                
                # check if needed dirs exists or create
                if not os.path.isdir(swl_dir):
                    # create swl_name dir
                    os.mkdir(swl_dir)
                if not os.path.isdir(set_dir):
                    # create set_name dir
                    os.mkdir(set_dir)
                    # mv all files
                    
                # get all files (machine_name), iterate over
                for i in os.listdir(original_dir):
                    # while file exists in swl_name
                    x = i
                    while ( os.path.isfile( os.path.join(set_dir,x))):
                        #  rename (2 random digits in front)
                        x = ( str( random.randint(0,9) )
                              + str( random.randint(0,9) )
                              + i
                            )
                    # mv file to swl_name
                    os.rename( os.path.join( original_dir, i ),
                               os.path.join( set_dir, x )
                    )
                # remove original set and machine dir
                try:
                    os.rmdir(original_dir)
                    os.rmdir(
                        os.path.join(
                            self.mame_ini['snapshot_directory'],
                            machine
                        )
                    )
                except:
                    pass
                
        # TODO remove extracted zip content?
        
        return
        
    ### EXIT, close video and db conn
    def exit(self):
        
        utilmod.save_software_list(
            settings_folder, 'lastgames.txt', self.last[-10:]
        )
        
        # stop video if playing
        # if xbmc.Player().isPlayingVideo() and self.playvideo:
        #     xbmc.Player().stop()
            
        # close db
        self.ggdb.close_db()
        
        # close script
        self.close()

### MAIN LOOP
def main():

    skin = "Default"
    path = ''
    path = xbmcaddon.Addon(id='script.umsa.mame.surfer').getAddonInfo('path')

    # check Kodi skin
    if 'transparency' in xbmc.getSkinDir():
        ui = UMSA("umsa_transparency.xml", path, skin, "720p")
    else:
        ui = UMSA("umsa_estuary.xml", path, skin, "720p")
        
    ui.doModal()
    del ui
    
### start main loop
main()

