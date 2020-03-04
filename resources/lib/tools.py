# -*- coding: utf-8 -*-
"""Library for MARP, Youtube search and special emulator handling.

Functions:
 marp_search
 marp_download
 youtube_search

IDEAS:
 - with http://replay.marpirc.net/txt/scores3.htm we know all mame arcade sets with replays
   also scores and player (but only first 3)
"""

import os
from sys import version_info
from io import BytesIO
from re import findall, search
from zipfile import ZipFile
# PY2: remove except part for py3 only
try:
    from urllib.request import urlopen
    from urllib.parse import urlencode
    from html import unescape
except ImportError:
    from urllib2 import urlopen
    from urllib import urlencode
    from HTMLParser import HTMLParser

MARP_URL = "http://replay.marpirc.net"
YT_URL = "http://www.youtube.com"

def split_gamename(complete_name):
    """Split the complete name of a MAME description into the name and details plus version.

    Return: gamename, detail

    TODO
    - only save complete mame set name and split when needed (not here)
      ^ can remove 2 columns from maston_variant db table (2 or 1?)
    - make util function for web and kodi add-on
    """

    gamename, detail, details = '', '', []
    # dont be greedy, exlucde ( from detail
    for name, detail in findall(r'(.*?) (\([^(]*?\))', complete_name):
        gamename += name.strip()
        details.append(detail[1:-1]) # remove ()
    detail = ', '.join(details)
    # check as above does not match when () is missing
    if not gamename:
        gamename = complete_name

    # TODO rework finding version in gamename
    # might need version finding without v or V
    # find versions like 1.1 at the end of gamename
    version = search(r'([vV]\d+\.\d+)', gamename)
    if version:
        if not detail:
            detail = version.group()
        else:
            detail = '{} {}'.format(version.group(), detail)

    return gamename, detail

def marp_search(short_name='', long_name='', version=''):
    """Search on MARP site for MAME input files

    Returns a list of MARP entries:
    [set_name, 2nd_set_name, game_name, rank, points, player_name, percentage,
     zipfile_uri, mame_version]

    Infos about MARP search and results:

    Search:
    http://replay.marpirc.net/index.cgi?mode=search&table=on&omit_search=yes
    "short=&long=&player=&player_pre=&version=194&orig_version=&desc=&highest_pos=1&per_game=3&
    per_table=25&maxlines=100&pic_mode=0&tourn=0&date_switch=none&date_day=0&date_month=0&
    date_year=0&score=with&clone=wild&sort=short&mode=search&link_score_to_edit="

    Arguments:
    short = ''
    long = ''
    version = ''
    highest_pos = 1
    per_game = 3
    per_table = 25
    maxlines = 100
    pic_mode = 0
    tourn = 0
    score = 'with' # confirmed, unconfirmed, without, all
    clone = 'wild' # no, yes
    sort = 'short'

    Result:
    <TR ALIGN=CENTER><TD></TD><TD><FONT SIZE=+1>2</FONT><FONT SIZE=-1>nd</FONT><BR><BR>
    <FONT SIZE=-1>&nbsp;clone&nbsp;of&nbsp;<BR><a target="_top" href="/r/baddudes"
    onMouseOver="window.status='List Scores for baddudes'; return true">baddudes</a></FONT></TD>
    <TD>Dragonninja (Japan)<BR>(<a target="_top" href="/r/drgninja"
    onMouseOver="window.status='List Scores for drgninja'; return true">drgninja</a>)</TD><TD>
    <A HREF='/index.cgi?mode=search&player=^Jarl$&highest_pos=1&per_game=100&show_betters=1
     &table=on&tourn=0&maxlines=999'
    onMouseOver="window.status='List Recordings by Player'; return true">
    Jarl</A></TD><TD>28 Feb 18<BR>12:23:16</TD><TD>340,600</TD><TD>
    <A HREF='/inp/3/c/d/jrl_drgninja_340600_wolf195.zip'
     onMouseOver="window.status='Download Recording'; return true">wolf195</A>
    <BR> <A HREF='https://github.com/mahlemiut/wolfmame/releases/tag/wolf195'
    onMouseOver="window.status='Download wolf195'; return true">get MAME</A></TD></TR>
    """

    parg = {
        "short" : short_name,
        "long" : long_name,
        "version" : str(version),
        "highest_pos" : "1",
        "per_game" : "999",
        "per_table" : "999",
        "maxlines" : "999",
        "pic_mode" : "0",
        "tourn" : "0",
        "date_switch" : "none",
        "score" : "with",
        "clone" : "wild",
        "sort" : "short",
        "mode" : "search"
    }
    req = urlopen(
        '{}/index.cgi'.format(MARP_URL),
        data=urlencode(parg).encode('utf-8'), timeout=10)
    # contains: user_set_score_version.zip, version
    dl_ver = findall(
        r'<A HREF=\'(\/inp\/.*?\.zip)\' onMouseOver=".*?">(.*?)</A>',
        req.read().decode('utf-8', errors='ignore'))

    # text output: "no_table" : "on"
    parg['no_table'] = "on"
    req = urlopen(
        '{}/index.cgi'.format(MARP_URL),
        data=urlencode(parg).encode('utf-8'), timeout=10)
    # contains: cadashs (Cadash (Spain, version 1)) #1st : 116155 Jarl (100%)
    info = findall(
        r'<LI>\n(.*?) \((.*)\) #(.*?) : (.*?) (.*?) \((.*)\)\n',
        req.read().decode('utf-8', errors='ignore'))

    ret = []
    for count, marp_info in enumerate(info):
        # TODO rework cleaning set name
        set_name = marp_info[0]
        # set_name can contain *set or set-*, remove them
        if set_name[0] == '*':
            set_name = set_name[1:]
        find_dash = set_name.find('-')
        if find_dash > 0:
            set_name = set_name[:find_dash]
        ret.append({
            'set_name': set_name,
            'gamename': marp_info[1],
            'rank': marp_info[2],
            'points': marp_info[3],
            'player': marp_info[4],
            'percentage': marp_info[5],
            'download': dl_ver[count][0],
            'version': dl_ver[count][1]
        })
    return ret

def marp_download(zip_url, path):
    """Check if INP already exists, otherwise download and extract."""

    inp_name = os.path.split(zip_url)[1].replace('.zip', '.inp')
    if not os.path.isfile(os.path.join(path, inp_name)):
        zip_obj = ZipFile(BytesIO(urlopen("{}{}".format(MARP_URL, zip_url), timeout=30).read()))
        # extract only first *.inp file from zip
        for name in zip_obj.namelist():
            if name[-4:] == '.inp':
                zip_obj.extract(name, path)
                os.rename(os.path.join(path, name), os.path.join(path, inp_name))
                break
    return inp_name

def youtube_search(gamename, machine):
    """Search for Youtube videos

    Returns result of findall with Youtube Video IDs and Titles
    """

    query_string = urlencode({"search_query" : '{} {}'.format(gamename.split(), machine)})
    url_open = urlopen("{}/results?{}".format(YT_URL, query_string), timeout=30)
    # PY2
    if version_info < (3, 0):
        html = HTMLParser()
        html_content = html.unescape(url_open.read().decode('utf-8', errors='ignore'))
    else:
        html_content = unescape(url_open.read().decode('utf-8', errors='ignore'))
    return findall(r'<a href="\/watch\?v=(.{11})".*?title="(.*?)"', html_content)

def scan_dat(fobj, all_sets, datfile, dbc):
    """Scan MAME support file and write seperate infos to database.

    TODO check where to put double [CR]
    TODO: score.dat when last line $end
    """

    swl = []
    sets = []
    dat = {}
    tag = ""
    flag = None

    for line in fobj:
        line = line.rstrip()
        if len(line) < 1:
            continue

        # into an entry
        if flag:
            # save entry
            if line == '$end':

                # save entries to DB
                dat_ids = []
                for tag, text in dat.items():

                    # check sysinfo.dat for stub entries
                    if tag == "Sysinfo":
                        if "just a stub" in text:
                            continue
                        flag = True
                        for i in text.split('[CR]'):
                            if i and i[0] != '=':
                                flag = False
                        if flag:
                            continue

                    dbc.execute(
                        "INSERT INTO dat (file, entry) \
                            VALUES (?, ?)", (tag, text)
                    )
                    dat_ids.append(dbc.lastrowid)

                # save pointers to sets
                for swl_name in swl:
                    for set_name in sets:
                        if "{}:{}".format(swl_name, set_name) in all_sets:
                            for i in dat_ids:
                                dbc.execute(
                                    "INSERT INTO dat_set (id, dat_id) VALUES (?, ?)",
                                    (all_sets["{}:{}".format(swl_name, set_name)], i)
                                )

                # clear variables
                tag = ""
                swl = None
                sets = None
                flag = None
                dat = {}

            # add line to entry
            elif line == '$bio':
                if datfile == 'history.dat':
                    tag = 'History'
                elif datfile == 'mameinfo.dat':
                    tag = 'MInfo'
                elif datfile == 'sysinfo.dat':
                    tag = "Sysinfo"
                else:
                    tag = "Info"
                if tag not in dat:
                    dat[tag] = ""
                else:
                    dat[tag] += "-----NEXT--------[CR]"

            elif line == '$story':
                tag = 'Score'
                if tag not in dat:
                    dat[tag] = ""
                else:
                    dat[tag] += "-----NEXT--------[CR]"

            elif line == '$cmd':
                tag = 'Command'
                if tag not in dat:
                    dat[tag] = ""
                else:
                    dat[tag] += "-----NEXT--------[CR]"

            elif line[:2] == '- ' and line[-2:] == ' -':
                if datfile == 'command.dat':
                    dat[tag] += "[CR]"+line
                else:
                    tag = line[2:-2].lower().capitalize()
                    if tag == "Tips and tricks":
                        tag = "Tips/Tricks"
                    if tag not in dat:
                        dat[tag] = ""
                    else:
                        dat[tag] += "-----NEXT--------[CR]"


            elif (line == '$mame'
                  or line[:7] == 'LEVELS:'
                  or line[:7].lower() == 'romset:'
                  or line == 'Other Emulators:'):

                tag = 'Info'
                if tag not in dat:
                    dat[tag] = ""
                else:
                    dat[tag] += line + "[CR]"

            elif (line in (
                    'WIP:',
                    'STORY:',
                    'STORY AND PLAY INSTRUCTIONS:', # TODO: only 2 times in mameinfo.dat
                    'START:',
                    'SETUP:',
                    'GAMEPLAY:',
                    'PLAY INSTRUCTIONS:',)):

                tag = line[:-1].lower().capitalize()
                if tag == 'Play instructions':
                    tag = 'Play Inst.'
                elif tag == 'Wip':
                    tag = 'WIP'
                elif tag == 'Story and play instructions':
                    tag = 'Story'
                if tag not in dat:
                    dat[tag] = ""
                else:
                    dat[tag] += "-----NEXT--------[CR]"

            elif line[:17] == 'Recommended Games':
                tag = "Rec"
                if '(' in line:
                    cat = "- {}:[CR]".format(line[line.find('(')+1:line.find(')')])
                else:
                    cat = ""
                if tag not in dat:
                    dat[tag] = cat
                else:
                    dat[tag] += cat

            else:
                if tag in dat:
                    dat[tag] += line + "[CR]"
                else:
                    tag = 'others'
                    if tag not in dat:
                        dat[tag] = line + "[CR]"
                    else:
                        dat[tag] += "-----NEXT--------[CR]"
                        dat[tag] += line + "[CR]"

        else:
            # check if entry begins
            if line[0] == '$' and '=' in line:
                flag = True

                # remove last ,
                if line[-1:] == ',':
                    line = line[:-1]

                # split at =
                swl_str, sets_str = line[1:].split('=', 1)

                # replace info with mame
                swl_str = swl_str.replace('info', 'mame')

                # split swl and sets by ,
                swl = swl_str.split(',')
                sets = sets_str.split(',')
