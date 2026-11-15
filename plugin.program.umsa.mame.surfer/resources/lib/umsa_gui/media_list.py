"""Media list and recommended games list of the UMSA frontend.

Both lists end up in the game list control, so they build the entries and hand
them over to ``popup_gamelist``.
"""

from dataclasses import dataclass
from json import loads

import xbmc
from umsa_core.game_repository import parse_recommended_games

from . import gamelist as gamelist_workflows
from . import strings as S
from .constants import ENTRY_SEARCH, KIND_MEDIA, SEARCH_MARP, SEARCH_YOUTUBE
from .strings import tr

# heading rows that start an online search when clicked
YOUTUBE_SEARCH_ID = f"{ENTRY_SEARCH}::{SEARCH_YOUTUBE}"
MARP_SEARCH_ID = f"{ENTRY_SEARCH}::{SEARCH_MARP}"


@dataclass
class MediaCtx:
    """Media and recommended games of the shown software."""

    services: object = None
    software: object = None
    # context of the game list the entries are shown in
    gamelist: object = None


def choose_media(ctx):
    """Dialog to choose media for playing."""

    # labels in list
    media_list = []
    video = [{'name': tr(S.MEDIA_VIDEOS), 'id': '0', 'year': '', 'maker': ''}]
    manual = [{'name': tr(S.MEDIA_MANUALS), 'id': '0', 'year': '', 'maker': ''}]
    vgm = [{'name': tr(S.MEDIA_MUSIC), 'id': '0', 'year': '', 'maker': ''}]

    xbmc.log(f"UMSA gui: choose media - {ctx.software.vgms}", xbmc.LOGDEBUG)
    if ctx.software.vgms:
        # show the title, keep the short set name as id for playback
        vgm_titles = ctx.software.vgm_titles or {}
        titled = sorted(
            ((vgm_titles.get(vgmitem) or vgmitem, vgmitem) for vgmitem in ctx.software.vgms),
            key=lambda entry: entry[0].lower())
        for title, vgmitem in titled:
            vgm.append({'name': title, 'id': "vgm::" + vgmitem, 'year': '', 'maker': ''})
    xbmc.log(f"UMSA gui: choose media - vgmlist {vgm}", xbmc.LOGDEBUG)
    # get media
    for j in ctx.software.info:
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
    media = ctx.services.ggdb.status.get_further_media(ctx.software.actset['id'])
    if media and media['youtube']:
        yt_list = [{'name': tr(S.MEDIA_YOUTUBE), 'id': YOUTUBE_SEARCH_ID,
                    'year': '', 'maker': ''}]
        for i in loads(media['youtube']):
            yt_list.append(
                {'name': i[1], 'id': f"yt::{i[0]}", 'year': '', 'maker': ''})
    else:
        yt_list = [{'name': tr(S.MEDIA_YOUTUBE_SEARCH),
                    'id': YOUTUBE_SEARCH_ID, 'year': '', 'maker': ''}]
    if media and media['marp']:
        marp_list = [{'name': tr(S.MEDIA_REPLAYS), 'id': MARP_SEARCH_ID,
                      'year': '', 'maker': ''}]
        for i in loads(media['marp']):
            marp_list.append({
                'name': "{} ({} - {})".format(i['player'], i['percentage'], i['points']),
                'id': "{}::{}".format(i['set_name'], i['download']),
                'year': i['rank'], 'maker': i['version']})
    else:
        marp_list = [{'name': tr(S.MEDIA_REPLAYS_SEARCH),
                      'id': MARP_SEARCH_ID, 'year': '', 'maker': ''}]

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

    gamelist_workflows.popup_gamelist(ctx.gamelist, media_list, tr(S.CHOOSE_MEDIA), pos=pos, kind=KIND_MEDIA)


def show_rec(ctx, focus=True):
    """Shows recommended section from mameinfo.dat in gamelist"""

    text = ''
    if (ctx.software.actset['id'] in ctx.software.all_dat
            and 'Rec' in ctx.software.all_dat[ctx.software.actset['id']]):
        text = ctx.software.all_dat[ctx.software.actset['id']]['Rec']
    else:
        for i in ctx.software.all_dat:
            if 'Rec' in ctx.software.all_dat[i]:
                text = ctx.software.all_dat[i]['Rec']
                break
    rec_list, pos = parse_recommended_games(text, ctx.services.ggdb.games)
    gamelist_workflows.popup_gamelist(ctx.gamelist, rec_list, tr(S.RECOMMENDED), pos=pos, focus=focus)
