"""MARP and Youtube search, Artwork and support file scan

IDEAS:
 - with http://replay.marpirc.net/txt/scores3.htm we know all mame arcade sets with replays
   also scores and player (but only first 3)
"""

import glob
import os
from hashlib import md5
from html import unescape
from io import BytesIO
from re import findall
from urllib.parse import urlencode
from urllib.request import urlopen
from zipfile import ZipFile

from .artwork import root_key_for_path
from .logging import log

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
    with urlopen(
        f'{MARP_URL}/index.cgi',
        data=urlencode(parg).encode('utf-8'), timeout=10) as req:
        # contains: user_set_score_version.zip, version
        dl_ver = findall(
            r'<A HREF=\'(\/inp\/.*?\.zip)\' onMouseOver=".*?">(.*?)</A>',
            req.read().decode('utf-8', errors='ignore'))

    # text output: "no_table" : "on"
    parg['no_table'] = "on"
    with urlopen(
        f'{MARP_URL}/index.cgi',
        data=urlencode(parg).encode('utf-8'), timeout=10) as req:
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
        with urlopen(f"{MARP_URL}{zip_url}", timeout=30) as response:
            archive_data = response.read()
        with BytesIO(archive_data) as buffer, ZipFile(buffer) as zip_obj:
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

    query_string = urlencode({"search_query" : f'{gamename.split()}+{machine}'})
    with urlopen(f"{YT_URL}/results?{query_string}", timeout=30) as url_open:
        html_content = unescape(url_open.read().decode('utf-8', errors='ignore'))
    return findall(r'{"videoId":"(.{11})".*?"text":"(.*?)"', html_content)


def scan_exodos_artwork(exodos_path, exodos_sets, abc, report_progress=None):
    """Index eXoDOS artwork and GameData MP4s into ``art_set``.

    ``exodos_sets`` maps the normalized gamename to the set id. ``abc`` is the
    caller-owned artwork DB cursor. This is the legacy image/videosnap portion
    of the eXoDOS scan; it neither parses ``MS-DOS.xml`` nor writes the eXoDOS
    DAT metadata.
    """

    if report_progress is None:
        def report_progress(percent=None, what=None):
            pass

    art_path = os.path.join(exodos_path, 'Images', 'MS-DOS')
    art_type_indicator = len(art_path.split('/'))
    log(f"UMSA support: art path and ind.: {art_path} : {art_type_indicator}", level='debug')
    pics = ('.gif', '.png', '.jpg')

    report_progress(None, 'scan md5sum for titles...')
    # get md5sum from all titles to sort out wrong title boxfronts
    titles = []
    alltitles = glob.glob(
        f"{os.path.join(art_path, 'Screenshot - Game Title')}/**", recursive=True)
    maxno = len(alltitles)
    log(f"UMSA support: found {maxno} title screenshot to scan for md5", level='info')
    count = 1.0
    for titlefile in alltitles:
        if os.path.splitext(titlefile)[1].lower() in pics:
            titles.append(md5sum(titlefile))
        report_progress(int(count / maxno * 100) if maxno else 100, None)
        count += 1

    report_progress(None, 'scan all exodos art...')
    report_progress(0, None)
    allart = glob.glob(f"{art_path}/**", recursive=True)
    maxno = len(allart)
    count = 1.0
    for art_entry in allart:
        dirname, basename = os.path.split(art_entry)
        pic_fullname, extension = os.path.splitext(basename)
        if extension.lower() in pics:
            pic_name, empty, pic_no = pic_fullname.rpartition('-')
            if pic_name.lower() in exodos_sets:
                if dirname.split('/')[art_type_indicator] == 'Box - Front':  # get md5, check against titles
                    if md5sum(art_entry) in titles:
                        continue
                abc.execute(
                    "INSERT INTO art_set (id, source, root_key, scan_unit, type, extension, relative_path, archive_member) VALUES (?,?,?,?,?,?,?,?)",
                    (exodos_sets[pic_name.lower()],
                     'exodos',
                     root_key_for_path(exodos_path) if exodos_path else '',
                     dirname.split('/')[art_type_indicator] if art_type_indicator < len(dirname.split('/')) else '',
                     exodos_type_convert[dirname.split('/')[art_type_indicator]],
                     extension[1:],
                     os.path.relpath(art_entry, exodos_path) if exodos_path else art_entry,
                     None)
                )
        report_progress(int(count / maxno * 100) if maxno else 100, None)
        count += 1

    report_progress(None, 'scan GameData zips...')
    report_progress(0, None)
    gamedata_zip_path = os.path.join(exodos_path, 'Content', 'GameData', 'eXoDOS')
    gamedata_zips = glob.glob(f"{gamedata_zip_path}/**", recursive=True)
    maxno = len(gamedata_zips)
    count = 1.0
    allext = {}
    allext['mp4notfound'] = 0
    for gamedata_zip in gamedata_zips:
        if gamedata_zip[-3:] != 'zip':
            continue
        with ZipFile(gamedata_zip, 'r') as archive:
            for entry in archive.namelist():
                root, ext = os.path.splitext(entry)
                if ext.lower() in allext:
                    allext[ext.lower()] += 1
                else:
                    allext[ext.lower()] = 1
                if 'Videos' in entry or ext == '.mp4':
                    exodos_name = os.path.split(gamedata_zip)[1][:-11].lower()
                    # TODO convert name or find other way to match...
                    # get short name and then .bat name from filesystem, is same as .mp4
                    if exodos_name in exodos_sets:
                        abc.execute(
                            "INSERT INTO art_set (id, source, root_key, scan_unit, type, extension, relative_path, archive_member) VALUES (?,?,?,?,?,?,?,?)",
                            (exodos_sets[exodos_name],
                             'exodos',
                             root_key_for_path(exodos_path) if exodos_path else '',
                             os.path.relpath(gamedata_zip, exodos_path) if exodos_path and os.path.isabs(gamedata_zip) else (os.path.relpath(gamedata_zip, exodos_path) if exodos_path else os.path.basename(gamedata_zip)),
                             'videosnaps', 'mp4',
                             os.path.relpath(gamedata_zip, exodos_path) if exodos_path else gamedata_zip,
                             entry)
                        )
                    else:
                        log(f"UMSA support: found {entry} but {exodos_name} not found in exodos_sets", level='warning')
                        allext['mp4notfound'] += 1
        report_progress(int(count / maxno * 100) if maxno else 100, None)
        count += 1
    log(f"UMSA support: {allext}", level='debug')
    report_progress(None, 'exodos finished!')
