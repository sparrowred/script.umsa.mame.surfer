"""MARP and Youtube search, Artwork and support file scan

IDEAS:
 - with http://replay.marpirc.net/txt/scores3.htm we know all mame arcade sets with replays
   also scores and player (but only first 3)
"""

import os
from hashlib import md5
from html import unescape
from io import BytesIO
from re import findall
from urllib.parse import urlencode
from urllib.request import urlopen
from zipfile import ZipFile

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

