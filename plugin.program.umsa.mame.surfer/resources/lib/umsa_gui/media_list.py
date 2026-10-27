"""Media list and recommended games list of the UMSA frontend.

Both lists end up in the game list control, so they build the entries and hand
them over to ``popup_gamelist``.
"""

from json import loads

import xbmc
from umsa_core.database import parse_recommended_games


def choose_media(gui):
    """Dialog to choose media for playing."""

    # labels in list
    media_list = []
    video = [{'name': '- Videos -', 'id': '0', 'year': '', 'maker': ''}]
    manual = [{'name': '- Manuals -', 'id': '0', 'year': '', 'maker': ''}]
    vgm = [{'name': '- Music -', 'id': '0', 'year': '', 'maker': ''}]

    xbmc.log(f"UMSA gui: choose media - {gui.vgms}", xbmc.LOGDEBUG)
    if gui.vgms:
        for vgmitem in gui.vgms:
            vgm.append({'name': vgmitem, 'id': "vgm::" + vgmitem, 'year': '', 'maker': ''})
    xbmc.log(f"UMSA gui: choose media - vgmlist {vgm}", xbmc.LOGDEBUG)
    # get media
    for j in gui.info:
        for i in j:
            if 'video' in i:
                video.append(
                    {'name': f"{i['gamename']} ({i['swl_name']})",
                     'id': i['video'],
                     'year': '',
                     'maker': ''
                     }
                    )
            if 'manual' in i:
                manual.append(
                    {'name': f"{i['gamename']} ({i['swl_name']})",
                     'id': i['manual'],
                     'year': '',
                     'maker': ''
                     }
                    )
    # get youtube videos
    media = gui.ggdb.get_further_media(gui.actset['id'])
    if media and media['youtube']:
        yt_list = [{'name': '- Youtube -', 'id': 'nan', 'year': '', 'maker': ''}]
        for i in loads(media['youtube']):
            yt_list.append(
                {'name': i[1], 'id': f"yt::{i[0]}", 'year': '', 'maker': ''})
    else:
        yt_list = [{'name': '- Youtube (click for online search) -',
                    'id': 'nan', 'year': '', 'maker': ''}]
    if media and media['marp']:
        marp_list = [{'name': '- Replays -', 'id': 'nan', 'year': '', 'maker': ''}]
        for i in loads(media['marp']):
            marp_list.append({
                'name': "{} ({} - {})".format(i['player'], i['percentage'], i['points']),
                'id': "{}::{}".format(i['set_name'], i['download']),
                'year': i['rank'], 'maker': i['version']})
    else:
        marp_list = [{'name': '- Replays (click for MARP search) -', 'id': 'nan',
                      'year': '', 'maker': ''}]

    pos = 0
    if len(video) > 1:
        media_list.extend(video)
        pos = 1
    if len(manual) > 1:
        media_list.extend(manual)
        pos = 1
    if len(vgm) > 1:
        media_list.extend(vgm)
        pos = 1
    media_list.extend(yt_list)
    media_list.extend(marp_list)

    gui.popup_gamelist(media_list, 'Choose Media', pos=pos)


def show_rec(gui):
    """Shows recommended section from mameinfo.dat in gamelist"""

    text = ''
    if (gui.actset['id'] in gui.all_dat
            and 'Rec' in gui.all_dat[gui.actset['id']]):
        text = gui.all_dat[gui.actset['id']]['Rec']
    else:
        for i in gui.all_dat:
            if 'Rec' in gui.all_dat[i]:
                text = gui.all_dat[i]['Rec']
                break
    rec_list, pos = parse_recommended_games(text, gui.ggdb)
    gui.popup_gamelist(rec_list, 'Recommended', pos=pos)
