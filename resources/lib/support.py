# -*- coding: utf-8 -*-
"""MARP and Youtube search, Artwork and support file scan

TODO create google cover image search

IDEAS:
 - with http://replay.marpirc.net/txt/scores3.htm we know all mame arcade sets with replays
   also scores and player (but only first 3)
"""

import os
import glob
from io import BytesIO
from re import findall
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from urllib.request import urlopen
from urllib.parse import urlencode, quote
from html import unescape
from hashlib import md5
from utilities import log

MARP_URL = "http://replay.marpirc.net"
YT_URL = "http://www.youtube.com"

exodos_type_convert = {
    "Clear Logo": "marquees",
    "Advertisement Flyer - Back": "flyers",
    "Advertisement Flyer - Front": "flyers",
    "Arcade - Marquee": "marquees",
    "Banner": "marquees",
    "Box - 3D": "box",
    "Box - Spine": "box",
    "Box - Back": "covers - back",
    "Box - Back - Reconstructed": "covers - back",
    "Box - Front": "covers",
    "Box - Front - Reconstructed": "covers",
    "Cart - Front": "media",
    "Cart - Back": "media",
    "Disc": "media",
    "Fanart - Background": "fanart",
    "Fanart - Box - Front": "fanart",
    "Fanart - Disc": "media",
    "Screenshot - Game Over": "gameover",
    "Screenshot - Game Select": "select",
    "Screenshot - Game Title": "titles",
    "Screenshot - Gameplay": "snap",
    "Screenshot - High Scores": "scores"
}

def md5sum(filename):
    hash = md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(128 * hash.block_size), b""):
            hash.update(chunk)
    return hash.hexdigest()

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

    if broken:
    - make search in browser to check query_string
    - curl -o /tmp/ytsearch.html the resulting url, open in browser, search for id of video
    """

    query_string = urlencode({"search_query" : '{}+{}'.format(gamename.split(), machine)})
    url_open = urlopen("{}/results?{}".format(YT_URL, query_string), timeout=30)
    html_content = unescape(url_open.read().decode('utf-8', errors='ignore'))
    return findall(r'{"videoId":"(.{11})".*?"text":"(.*?)"', html_content)

def scan_artwork():
    """Scan artwork and more. """
    pass

def scan_exodos(exodos_path, exodos_sets, exodos_sets_names, dbc, abc, other_self):
    """Scan eXoDOS xml file for dat infos and artwork path"""

    # fetch: Developer, Notes, Source, Genre, Region
    # also: ManualPath, MusicPath, but these are media > check against filesystem

    '''
    exodos directory structure:

    # contains batch and dosbox.conf
    Content/!DOSmetadata.zip/eXo/eXoDOS/!dos/<shortname>/<description>/

    # contains artwork
    Content/XODOSMetadata.zip/Images/MS-DOS/

    # contains extra content like pdf,mp4, names equal to .bat in !DOSmetadata.zip
    Content/GameData/eXoDOS/

    # contains game files in zips, names equal to .bat in !DOSmetadata.zip
    eXo/eXoDOS/

    '''

    # Content/XODOSMetadata.zip xml/all/MS-DOS.xml
    other_self.scan_what = 'reading MS-DOS.xml from zip'
    xml_file = os.path.join(exodos_path, 'Content', 'XODOSMetadata.zip')
    with ZipFile(xml_file, 'r') as archive:
        exodos_xml = archive.read('xml/all/MS-DOS.xml').decode('utf-8', 'ignore')
    root = ET.fromstring(exodos_xml)
    xmldata = {}

    other_self.scan_what = 'scanning xml...'
    maxno = len(root) 
    count = 1.0
    for game in root.iter('Game'):
        noapppath = False
        for child in game.iter():
            if child.tag == 'RootFolder':
                set_name = child.text.split('\\')[-1]
            elif child.tag == 'Developer':
                developer = child.text
            elif child.tag == 'Publisher':
                publisher = child.text
            elif child.tag == 'Notes':
                notes = child.text
            elif child.tag == 'Series':
                series = child.text
            elif child.tag == 'Source':
                source = child.text
            elif child.tag == 'Genre':
                genre = child.text
            elif child.tag == 'Rating':
                rating = child.text
            elif child.tag == 'Region':
                region = child.text
            elif child.tag == 'ManualPath':
                manual = child.text
            elif child.tag == 'MusicPath':
                music = child.text
            elif child.tag == 'VideoUrl':
                videourl = child.text
            elif child.tag == 'ApplicationPath':
                # get longname
                long_name = os.path.split(child.text.replace('\\','/'))[-1][:-4]
        note = f"""Genre: {genre}

Developer: {developer}
Publisher: {publisher}

{notes}

Source: {source}
Rating: {rating}
Series: {series}
Region: {region}
"""

        # set_name = RootFolder
        # ^ if no match: lowercase
        if (set_name in exodos_sets_names) or (set_name.lower() in exodos_sets_names):
            dbc.execute(
                "INSERT INTO dat (file, entry) \
                 VALUES (?, ?)", ('eXoDOS', note)
            )
            lastrow = dbc.lastrowid
            # TODO check if key exists 1st
            if set_name in exodos_sets_names:
                db_setid = exodos_sets_names[set_name]
            elif set_name.lower() in exodos_sets_names:
                db_setid = exodos_sets_names[set_name.lower()]
            else:
                log(f"UMSA exodos: shouldnt happen {set_name}", level='warning')
                continue

            dbc.execute(
                "INSERT INTO dat_set (id, dat_id) VALUES (?, ?)",
                (db_setid, lastrow)
            )
        else:
            log(f"UMSA exodos: cant find entry for dat {set_name}", level='warning')
        other_self.scan_perc = int(count / maxno * 100)
        count += 1

    # scan artwork
    # TODO needs tools.py and tools-xbmc.py modules for
    # filesystem operations > "import os" or "import xbmcvfs" 
    #
    # replace special char :' to _
    # Images/MS-DOS/*/Game Name_ Title-\d{2}.*  #Zork III_ The Dungeon Master-01.jpg
    # Images/MS-DOS/*/Country/Game Name_ Title-\d{2}.*  #Zork III_ The Dungeon Master-01.jpg
    # Manuals/^
    # Music/^
    #
    # new since exodos v6:
    #shasum Box\ -\ Front/1,000\ Miler-00.png Screenshot\ -\ Game\ Title/1,000\ Miler-01.png
    #eb613f06927300b9cc82caab90fbd77f3a0f961d  Box - Front/1,000 Miler-00.png
    #eb613f06927300b9cc82caab90fbd77f3a0f961d  Screenshot - Game Title/1,000 Miler-01.png
    # all games w/o box, got the game title, so shasum gametitle and check if box is same

    # TODO scan from Content/XODOSMetadata.zip and use images from zipfile
    art_path = os.path.join(exodos_path, 'Images', 'MS-DOS')
    art_type_indicator = len(art_path.split('/'))
    log(f"art path and ind.: {art_path} : {art_type_indicator}", level='debug')
    pics = ('.gif','.png','.jpg')

    other_self.scan_what = 'scan md5sum for titles...'
    # get md5sum from all titles to sort out wrong title boxfronts
    titles = []
    alltitles = glob.glob(f"{os.path.join(art_path,'Screenshot - Game Title')}/**", recursive=True)
    maxno = len(alltitles)
    log(f"found {maxno} title screenshot to scan for md5", level='info')
    count = 1.0
    for titlefile in alltitles:
        if os.path.splitext(titlefile)[1].lower() in pics:
            titles.append(md5sum(titlefile))
        other_self.scan_perc = int(count / maxno * 100)
        count += 1
    
    other_self.scan_what = 'scan all exodos art...'
    other_self.scan_perc = 0
    allart = glob.glob(f"{art_path}/**", recursive=True)
    maxno = len(allart) 
    count = 1.0
    for art_entry in allart:
        dirname, basename = os.path.split(art_entry)
        pic_fullname, extension =  os.path.splitext(basename)
        if extension.lower() in pics:
            pic_name, empty, pic_no = pic_fullname.rpartition('-')
            if pic_name.lower() in exodos_sets:
                #print(f"UMSA exodos art hit: {exodos_sets[pic_name.lower()]} - {pic_no}")
                #ext_dir = exodos_type_convert[dirname.split('/')[7]] 
                if dirname.split('/')[art_type_indicator] == 'Box - Front': # get md5, check against titles
                    if md5sum(art_entry) in titles:
                        continue
                #pic_type = ext_dir
                #print(f"UMSA exodos: {pic_type} - {dirname.split('/')[7]}")
                abc.execute(
                    "INSERT INTO art_set (id, type, extension, path, filename) VALUES (?,?,?,?,?)",
                    (exodos_sets[pic_name.lower()],
                     exodos_type_convert[dirname.split('/')[art_type_indicator]],
                     extension[1:], 0, art_entry)
                )
            #else:
            #    try:
            #        print(f"UMSA exodos art MISS: {pic_name} - {pic_no}")
            #    except UnicodeEncodeError:
            #        print("UMSA exodos art MISS: UnicodeEncodeError")
        #else:
        #    print(f"UMSA exodos: {art_entry}")
        other_self.scan_perc = int(count / maxno * 100)
        count += 1

    other_self.scan_what = 'scan GameData zips...'
    other_self.scan_perc = 0
    gamedata_zip_path = os.path.join(exodos_path, 'Content', 'GameData', 'eXoDOS')
    gamedata_zips = glob.glob(f"{gamedata_zip_path}/**", recursive=True)
    maxno = len(gamedata_zips) 
    count = 1.0
    allext = {}
    allext['mp4notfound'] = 0
    for gamedata_zip in gamedata_zips:
        # easy way without namelist:
        # just check for Videos/MS-DOS/zipname.mp4
        if gamedata_zip[-3:] != 'zip':
            continue
        with ZipFile(gamedata_zip, 'r') as archive:
            for entry in archive.namelist():
                root, ext = os.path.splitext(entry)
                if ext.lower() in allext.keys():
                    allext[ext.lower()] += 1
                else:
                    allext[ext.lower()] = 1
                if 'Videos' in entry or ext == '.mp4':
                    exodos_name = os.path.split(gamedata_zip)[1][:-11].lower()
                    # TODO convert name or find other way to match...
                    # get short name and then .bat name from filesystem, is same as .mp4
                    if exodos_name in exodos_sets:
                        abc.execute(
                            "INSERT INTO art_set (id, type, extension, path, filename) VALUES (?,?,?,?,?)",
                            (exodos_sets[exodos_name],
                            'videosnaps', 'mp4', 0, f'zip://{gamedata_zip}{entry}')
                        )
                    else:
                        log(f"found {entry} but {exodos_name} not found in exodos_sets", level='warning')
                        allext['mp4notfound'] += 1
        other_self.scan_perc = int(count / maxno * 100)
        count += 1
    log(allext, level='debug')

    other_self.scan_what = 'exodos finished!'
    return

def scan_gb64_nfo(all_gb64_sets, gb64_name, gb64_path, dbc, abc, other_self):

    # Extras/
    #  Adverts/A/Publisher_Game + \d _\d\w.jpg
    #  Cover/A/Title_Name{_*}.jpg
    #  Docs/^
    #  Maps/^
    #  Tips/^

    other_self.scan_what = 'reading covers...'
    cover_path = os.path.join(gb64_path,'Extras','Cover')
    cover_files = glob.glob(f"{cover_path}/**", recursive=True)
    maxno = len(cover_files) 
    count = 1.0
    hit , miss = 0 , 0
    for art_entry in cover_files:
        arttype = 'covers'
        dirname, basename = os.path.split(art_entry)
        filebase, filext = os.path.splitext(basename)
        filesplit = filebase.split('_')
        if filesplit[-1] == '[Back]':
            arttype = 'covers - back'
            del filesplit[-1]
        if filesplit[-1].startswith('(') and filesplit[-1].endswith(')'):
            info = filesplit.pop()
        title_name = ' '.join(filesplit)
        if title_name in gb64_name:
            abc.execute(
                "INSERT INTO art_set (id, type, extension, path, filename) VALUES (?,?,?,?,?)",
                (gb64_name[title_name], arttype, filext, 0, art_entry)
            )
        other_self.scan_perc = int(count / maxno * 100)
        count += 1

    other_self.scan_what = 'reading info files from zips...'
    maxno = len(all_gb64_sets)
    count = 1.0
    for setname, setid in all_gb64_sets.items():
        filename = os.path.join(gb64_path,'Games',setname+'.zip')
        if os.path.isfile(filename):
            with ZipFile(filename) as archive:
                nfo = archive.read('VERSION.NFO').decode('utf-8', 'ignore')
        else:
            log(f"UMSA gb64: zip not found {filename}", level='warning')
            continue
        infopart = 'internal'
        gameinfo, versioninfo, notesinfo = [],[],[]
        snap = ''
        for i in nfo.split('\n'):
            if ('-----' in i) or ('=====' in i):
                continue
            elif 'GAME INFO:' in i:
                infopart = 'game'
            elif 'VERSION INFO:' in i:
                infopart = 'version'
            elif 'NOTES:' in i:
                infopart = 'notes'
            elif 'Screenshot:' in i:
                snap = i.split(':')[-1].strip().replace('\\','/')
            elif 'SID:' in i:
                sid = i.split(':')[-1].strip()
            else:
                if infopart == 'game':
                    gameinfo.append(i)
                elif infopart == 'version':
                    versioninfo.append(i)
                elif infopart == 'notes':
                    notesinfo.append(i)
        if snap:
            abc.execute(
                "INSERT INTO art_set (id, type, extension, path, filename) VALUES (?,?,?,?,?)",
                (setid, 'snap', snap[:-3], 0, f"{gb64_path}Screenshots/{snap}")
            )
            title_image_path = f"{gb64_path}Screenshots/{snap[:-4]}_1{snap[-4:]}"
            if os.path.isfile(os.path.join(gb64_path, 'Screenshots', title_image_path)):
                abc.execute(
                    "INSERT INTO art_set (id, type, extension, path, filename) VALUES (?,?,?,?,?)",
                    (setid, 'titles', snap[:-3], 0, title_image_path)
                )
        
        # now put into db
        datinfo = '\n'.join(gameinfo)
        datinfo += '\n'+'\n'.join(versioninfo)
        datinfo += '\n'+'\n'.join(notesinfo)
     
        dbc.execute(
            "INSERT INTO dat (file, entry) \
             VALUES (?, ?)", ('GameBase64', datinfo)
        )
        lastrow = dbc.lastrowid
        dbc.execute(
            "INSERT INTO dat_set (id, dat_id) VALUES (?, ?)",
            (setid, lastrow)
        )
        other_self.scan_perc = int(count/maxno*100)
        count += 1
    other_self.scan_what = 'gamebase64 finished!'
    return

def scan_history(history_string, all_sets, dbc):
    """Scan history.xml. """

    root = ET.fromstring(history_string)
    #print(root.tag) # history
    #print(root.attrib) # version, date
    
    for entry in root:
        new_db_entries = []
        for child in entry:
            if child.tag == 'systems':
                for innerchild in child:
                    set_info = f"mame:{innerchild.attrib['name']}"
                    if set_info in all_sets:
                        new_db_entries.append(all_sets[set_info])
                    #else:
                    #    print(f"UMSA - history.xml: not found {set_info}")
            elif child.tag == 'software':
                for innerchild in child:
                    set_info = f"{innerchild.attrib['list']}:{innerchild.attrib['name']}"
                    if set_info in all_sets:
                        new_db_entries.append(all_sets[set_info])
                    #else:
                    #    print(f"UMSA - history.xml: not found {set_info}")
            elif child.tag == 'text':
                #dbc.save_setdat(new_db_entries, child.text)
                # now put into db
                dbc.execute(
                    "INSERT INTO dat (file, entry) \
                     VALUES (?, ?)", ('History', child.text)
                )
                lastrow = dbc.lastrowid

                for new_id in new_db_entries:        
                    dbc.execute(
                        "INSERT INTO dat_set (id, dat_id) VALUES (?, ?)",
                        (new_id, lastrow)
                    )
 
def scan_dat(fobj, all_sets, datfile, dbc):
    """Scan MAME support file and write seperate infos to database.

    TODO check where to put double [CR]
    TODO score.dat when last line $end
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
