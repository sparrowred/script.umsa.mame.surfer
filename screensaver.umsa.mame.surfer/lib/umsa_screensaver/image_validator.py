"""Bad-image detection for the screensaver snapshots.

A snapshot is rejected when its content hash is one of the known broken
images or when it is a single-colour image (Pillow is needed for the
variance check). Without Pillow only the hash list applies.
"""

from functools import reduce
from hashlib import md5

try:
    from PIL import Image as _Image
    from PIL import ImageStat as _ImageStat
    PIL = True
except ImportError:
    _Image = None
    _ImageStat = None
    PIL = False

# Broken images known with Pillow (hash of the decoded pixels)
BAD_IMAGE_LIST_PIL = (
    "98f4b5e0981192d781c35be7181c7b57",  # cover psx demo
    "8d80173851047da4aca3a9901a3b82c5",  # device
    "acf2a6f1537c82a19d3228f188c635f3",  # device
    "030d8394efbe41d0f4784ca8985d5b48",  # mechanical
    "92f04e810171e83ce868ce17f4e93737",  # mechanical
    "afdb9915c2b64e66e6af3dd00f637540",  # mechanical
    "844e8d74c384788196dc964686d1d5d0",  # mechanical
    "ca9cdda35a258466328d7fca93f445b4",  # screenless
    "3b43fd4467ace20511952f69c7889439",  # screenless
    "9b24d00807f94179a28f09619bc4e258",  # screenless
)

# Broken images known without Pillow (hash of the file content)
BAD_IMAGE_LIST_NO_PIL = (
    "cd773c91cffdb80457ab1c83bbd6cca5",  # cover psx demo
    "e2b8f257fea66b661ee70efc73b6c84a",  # device ingame
    "1b7928278186f053777dea680b0a2b2d",  # device ingame
    "47d7f4d18f0c9b4dcd87423e00c9917d",  # device ingame
    "0734aca010260cee0bbf08b08e642fed",  # device ingame
    "e940a4fdfd01163dae42bc0fe489c0e9",  # device ingame
    "b486065e909640d843dd4df98a0742fe",  # device title
    "7e8b76745b9daad337108fd2d09159bc",  # device title
    "8862b370e7c1785c336be63d464f14c7",  # device title
    "4330217adee809149c8e784e587e1f40",  # device title
    "30ab4d58332ef5332affe5f3320c647a",  # mechanical ingame
    "26bdf324b11da6190f38886a3b0f7598",  # mechanical ingame
    "f28cffce4c580b1c28ef0c24e8e25f80",  # mechanical ingame
    "11cf90ef6332e4e7643d5e4e84e411ba",  # mechanical title
    "cd3ada96083b26749cdb64f57662f0dc",  # mechanical title
    "eb910d22e89a24d09cb57bf111548f80",  # mechanical title
    "76707f5e81e41cb811a8a9f6050ccac7",  # screenless system
    "1b62951c72c91d2927da5a044af7e0bd",  # screenless system
    "6a4ca1ab352df8af4a25c50a65bb8963",  # screenless system
    "062a4b154b0aa03461ea3cdfe4f42172",  # screenless system
    "a766be38df34c5db61ad5cd559919487",  # screenless system
)

# A single-colour image has a variance below this value in every channel
SOLID_COLOR_VARIANCE = 0.010


def bad_image_list(pil_available=None):
    """Return the known broken image hashes for the given Pillow state."""

    if pil_available is None:
        pil_available = PIL
    return BAD_IMAGE_LIST_PIL if pil_available else BAD_IMAGE_LIST_NO_PIL


def check_snapshot(snapshot, bad_images=None, pil_available=None, kodi=None):
    """Return ``True`` when the snapshot is usable.

    Ok means it is not in the bad list and not only one color. ``bad_images``
    overrides the known hash list, ``pil_available`` overrides the Pillow
    detection and ``kodi`` is the Kodi module used for the (rare) error log.
    """

    if bad_images is None:
        bad_images = bad_image_list(pil_available)
    if pil_available is None:
        pil_available = PIL

    ret = True
    if pil_available and PIL and _Image is not None and _ImageStat is not None:
        img = False
        try:
            img = _Image.open(snapshot)
        except OSError:
            ret = False

        if img:
            try:
                imgmd5 = md5(img.tobytes()).hexdigest()
            except OSError as error:
                if kodi is not None:
                    kodi.log(
                        f"UMSA SSaver: {snapshot} error md5sum: {error}",
                        kodi.LOGWARNING)
                ret = False
            else:
                imgv = _ImageStat.Stat(img).var
                img.close()
                if imgmd5 in bad_images or reduce(
                        lambda x, y: x and y < SOLID_COLOR_VARIANCE,
                        imgv, True):
                    ret = False
    else:
        try:
            with open(snapshot, 'rb') as handle:
                imgmd5 = md5(handle.read()).hexdigest()
        except OSError:
            # an unreadable file is treated like a missing one
            return False
        if imgmd5 in bad_images:
            ret = False
    return ret
