# -*- coding: utf-8 -*-
"""UMSA screensaver module

- check snapshot images
- check snapshot aspect ratio

TODO change to screensaver module for umsa and kodi
 get wall from kodi slideshow
 get slide from kodi slideshow
 get videoplayer from umsa
 get randpic from umsa TODO make with doModal and transparent background: deletion is then fast
 make own kodi utility add-on
"""

from os import path
from hashlib import md5
from functools import reduce
from xbmcgui import ListItem
try:
    from PIL import Image, ImageStat
    PIL = True
except ImportError:
    PIL = False

class Check:
    """Snapshot check class with checksums for bad images."""

    def __init__(self):

        if PIL:
            self.pil = True
            self.bad_image_list = [
                "98f4b5e0981192d781c35be7181c7b57", # cover psx demo
                "8d80173851047da4aca3a9901a3b82c5", # device
                "acf2a6f1537c82a19d3228f188c635f3", # device
                "030d8394efbe41d0f4784ca8985d5b48", # mechanical
                "92f04e810171e83ce868ce17f4e93737", # mechanical
                "afdb9915c2b64e66e6af3dd00f637540", # mechanical
                "844e8d74c384788196dc964686d1d5d0", # mechanical
                "ca9cdda35a258466328d7fca93f445b4", # screenless
                "3b43fd4467ace20511952f69c7889439", # screenless
                "9b24d00807f94179a28f09619bc4e258", # screenless
            ]

        else:
            self.pil = False
            self.bad_image_list = [
                "cd773c91cffdb80457ab1c83bbd6cca5", # cover psx demo
                "e2b8f257fea66b661ee70efc73b6c84a", # device ingame
                "1b7928278186f053777dea680b0a2b2d", # device ingame
                "47d7f4d18f0c9b4dcd87423e00c9917d", # device ingame
                "0734aca010260cee0bbf08b08e642fed", # device ingame
                "e940a4fdfd01163dae42bc0fe489c0e9", # device ingame
                "b486065e909640d843dd4df98a0742fe", # device title
                "7e8b76745b9daad337108fd2d09159bc", # device title
                "8862b370e7c1785c336be63d464f14c7", # device title
                "4330217adee809149c8e784e587e1f40", # device title
                "30ab4d58332ef5332affe5f3320c647a", # mechanical ingame
                "26bdf324b11da6190f38886a3b0f7598", # mechanical ingame
                "f28cffce4c580b1c28ef0c24e8e25f80", # mechanical ingame
                "11cf90ef6332e4e7643d5e4e84e411ba", # mechanical title
                "cd3ada96083b26749cdb64f57662f0dc", # mechanical title
                "eb910d22e89a24d09cb57bf111548f80", # mechanical title
                "76707f5e81e41cb811a8a9f6050ccac7", # screenless system
                "1b62951c72c91d2927da5a044af7e0bd", # screenless system
                "6a4ca1ab352df8af4a25c50a65bb8963", # screenless system
                "062a4b154b0aa03461ea3cdfe4f42172", # screenless system
                "a766be38df34c5db61ad5cd559919487", # screenless system
            ]

    def check_snapshot(self, snapshot):
        """Return true when snapshot is Ok.

        Ok means it's not in the bad list and not only one color.
        """

        ret = True
        if PIL:
            img = False
            try:
                img = Image.open(snapshot)
            except IOError:
                ret = False

            if img:
                imgmd5 = md5(img.tobytes()).hexdigest()
                imgv = ImageStat.Stat(img).var
                img.close()

                if imgmd5 in self.bad_image_list:
                    ret = False
                elif reduce(lambda x, y: x and y < 0.010, imgv, True): # 0.005
                    ret = False
        else:
            img = False
            try:
                img = open(snapshot, 'rb')
            except IOError:
                ret = False

            if img:
                imgmd5 = md5(img.read()).hexdigest()
                img.close()
                if imgmd5 in self.bad_image_list:
                    ret = False
                else:
                    ret = True
        return ret

def check_image_aspect(set_info):
    """Pseudo aspect ratio check for image.

    Returns Vertical, Horizontal or NotScaled for one set
    based on display_type, display_rotation, category and swl.name

    """

    aspect_ratio = None
    if set_info['display_rotation'] in [90, 270]:
        aspect_ratio = 'Vertical'
    else:
        aspect_ratio = 'Horizontal'
    # TODO
    # - enhance list, check display_type
    # - problem is that set is not lcd, but machine gameboy!
    # - fetch display type for s['swl_machine_id']
    if (set_info['display_type'] == 'lcd' or
            set_info['category'] in (
                'Electromechanical / Pinball', 'Handheld Game') or
            set_info['swl_name'] in (
                'gameboy', 'lynx', 'gamegear')
       ):
        aspect_ratio = 'NotScaled'
    return aspect_ratio

def create_gui_element_from_snap(set_info, image, art_type='unset'):
    """Returns Kodi ListItem element for a snapshot."""

    # set art
    if image:
        dir_split = path.dirname(image).split('/')
        if len(dir_split) < 2:
            art = art_type
        else:
            art = dir_split[-2]
            # dir is the same as swl, then set filename as art
            if art == set_info['swl_name']:
                art = path.basename(image)[:-4]
    else:
        art = art_type

    # create listitem
    list_item = ListItem()
    list_item.setLabel("{}: {} ({})".format(
        art, set_info['detail'], set_info['swl_name']))
    list_item.setArt({'icon': image})
    # label to later set
    list_item.setProperty('detail', "{}: {} {}".format(
        art, set_info['swl_name'], set_info['detail']))
    aspect = check_image_aspect(set_info)
    if aspect == 'Vertical':
        list_item.setProperty('Vertical', '1')
        list_item.setProperty('Horizontal', '')
        list_item.setProperty('NotScaled', '')
    elif aspect == 'Horizontal':
        list_item.setProperty('Vertical', '')
        list_item.setProperty('Horizontal', '1')
        list_item.setProperty('NotScaled', '')
    elif aspect == 'NotScaled':
        list_item.setProperty('Vertical', '')
        list_item.setProperty('Horizontal', '')
        list_item.setProperty('NotScaled', '1')
    return list_item
