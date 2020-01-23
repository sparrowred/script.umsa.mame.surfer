# -*- coding: utf-8 -*-
# lib to fetch mame inp files from replay.marpirc.net

# 1. search for a game and see all results
# 2. get a random inp file from a relative actual version
#    means at least one search with a version

# INP Version 3.0 since which MAME version?

import re
import random
import zipfile
# from StringIO import StringIO
from io import BytesIO
#py3
try:
    from urllib.request import urlopen
    from urllib.parse import urlencode
# py2
except ImportError:
    from urllib import urlopen
    from urllib import urlencode

host = "http://replay.marpirc.net"

# or make a class so we can have internal lists
# of last search or with random elements?

def get_set(setname):

    uri = 'r/{}'.format( setname )

def search(short_name='', long_name='', version=''):

    parg = {
        "short" : short_name,
        "long" : long_name,
        "version" : version,
        "highest_pos" : "1",
        "per_game" : "999", # 3
        "per_table" : "999",
        "maxlines" : "999",
        "pic_mode" : "0",
        "tourn" : "0",
        "date_switch" : "none",
        "score" : "with",
        "clone" : "wild",
        "sort" : "short",
        "mode" : "search",
    }
    p_dl = urllib.urlencode( parg )
    req = urllib2.urlopen( host+'/index.cgi', data=p_dl, timeout=60 )
    c_dl = req.read()
    # user_set_score_version.zip
    dl_ver = re.findall( r'<A HREF=\'(\/inp\/.*?\.zip)\' onMouseOver=".*?">(.*?)</A>', c_dl )

    # text output: "no_table" : "on"
    parg['no_table'] = "on"
    p_dl = urllib.urlencode( parg )
    req2 = urllib2.urlopen( host+'/index.cgi', data=p_dl, timeout=60 )
    t_dl = req2.read()

    # cadashs (Cadash (Spain, version 1)) #1st : 116155 Jarl (100%)
    info = re.findall( r'<LI>\n(.*?) \((.*)\) (#.*?) : (.*?) (.*?) \((.*)\)\n', t_dl)

    ret = []
    for i in range(0, len(info)):
        # setname can contain *set or set-*
        x = info[i][0]
        if x[0] == '*':
            x = x[1:]
        z = x.find('-')
        if z > 0:
            x = x[:z]

        ret.append( [x] + list(info[i]) + list(dl_ver[i]) )

    # full list so it can be presented by umsa
    return ret

def rand(version):

    # or search(195) + search(194)
    x = search(version=version)

    # return list with short_name and url with zip
    return x

def download(zip_url, path):

    #print( host+zip_url)
    req = urllib2.urlopen( host+zip_url, timeout=20 )
    zip_file = req.read()
    zip_obj = zipfile.ZipFile(BytesIO(zip_file))
    
    files = zip_obj.namelist()
    #print( "zip-content:")
    #print( files)
    #print( "-----")

    inp = ''
    for name in zip_obj.namelist():
        #print( name)
        if name[-4:] == '.inp':
            x = zip_obj.extract(name, path)
            #print( x)
            inp = name
            break
    
    # name inp file like zip file from url
    # so we can precheck if file already exists in inp folder
    # then there is no need to redownload

    # download zip from url and unzip inp file to path
    # which should be the mame inp folder

    # return name of inp file
    return inp

# test
#x = search(version="194")
#y = download( random.choice(x),"/tmp/" )
#print( "mame start "+y)

# infos about marp search and result

# # search site http://replay.marpirc.net/index.cgi?mode=search&table=on&omit_search=yes
# "short=&long=&player=&player_pre=&version=194&orig_version=&desc=&highest_pos=1&per_game=3&\
# per_table=25&maxlines=100&pic_mode=0&tourn=0&date_switch=none&date_day=0&date_month=0&\
# date_year=0&score=with&clone=wild&sort=short&mode=search&link_score_to_edit="

# short = ''
# #long = ''
# version = ''
# highest_pos = 1
# per_game = 3
# per_table = 25
# maxlines = 100
# pic_mode = 0
# tourn = 0
# score = 'with' # confirmed, unconfirmed, without, all
# clone = 'wild' # no, yes
# sort = 'short'

# # result
'''
<TR ALIGN=CENTER><TD></TD><TD><FONT SIZE=+1>2</FONT><FONT SIZE=-1>nd</FONT><BR><BR>
<FONT SIZE=-1>&nbsp;clone&nbsp;of&nbsp;<BR><a target="_top" href="/r/baddudes"
onMouseOver="window.status='List Scores for baddudes'; return true">baddudes</a></FONT></TD>
<TD>Dragonninja (Japan)<BR>(<a target="_top" href="/r/drgninja"
onMouseOver="window.status='List Scores for drgninja'; return true">drgninja</a>)</TD><TD>
<A HREF='/index.cgi?mode=search&player=^Jarl$&highest_pos=1&per_game=100&show_betters=1&table=on&tourn=0&maxlines=999' \
onMouseOver="window.status='List Recordings by Player'; return true">
Jarl</A></TD><TD>28 Feb 18<BR>12:23:16</TD><TD>340,600</TD><TD>
<A HREF='/inp/3/c/d/jrl_drgninja_340600_wolf195.zip' onMouseOver="window.status='Download Recording'; return true">wolf195</A>\
<BR> <A HREF='https://github.com/mahlemiut/wolfmame/releases/tag/wolf195'
onMouseOver="window.status='Download wolf195'; return true">get MAME</A></TD></TR>
'''
