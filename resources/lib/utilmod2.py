# -*- coding: utf-8 -*-

import hashlib

class Check:
    
    def __init__( self, pil ):

        self.pil = pil
        
        if pil:
            
            # chrashes on some machines when screensaver starts the second time
            # now works, seems some PIL or Kodi Update fixed it
            from PIL import Image, ImageStat
            #print("##### Loaded PIL library!")
            self.Image = Image
            self.ImageStat = ImageStat
            
            self.bad_image_list = [
                "8d80173851047da4aca3a9901a3b82c5", # device
                "acf2a6f1537c82a19d3228f188c635f3", # device
                "ca9cdda35a258466328d7fca93f445b4", # screenless
                "3b43fd4467ace20511952f69c7889439", # screenless
                "9b24d00807f94179a28f09619bc4e258", # screenless
                "030d8394efbe41d0f4784ca8985d5b48", # mechanical
                "92f04e810171e83ce868ce17f4e93737", # mechanical
                "afdb9915c2b64e66e6af3dd00f637540", # mechanical
                "844e8d74c384788196dc964686d1d5d0", # mechanical
            ]
            
        else:
            
            self.bad_image_list = [
                "30ab4d58332ef5332affe5f3320c647a", # mechanical ingame
                "062a4b154b0aa03461ea3cdfe4f42172", # screenless system
                "a766be38df34c5db61ad5cd559919487", # screenless system
                "11cf90ef6332e4e7643d5e4e84e411ba", # mechanical title
                "b486065e909640d843dd4df98a0742fe", # device title
                "e2b8f257fea66b661ee70efc73b6c84a", # device ingame
                "1b7928278186f053777dea680b0a2b2d", # device ingame
                "cd3ada96083b26749cdb64f57662f0dc", # mechanical title
                "47d7f4d18f0c9b4dcd87423e00c9917d", # device ingame
                "7e8b76745b9daad337108fd2d09159bc", # device title
                "1b62951c72c91d2927da5a044af7e0bd", # screenless system
                "eb910d22e89a24d09cb57bf111548f80", # mechanical title
                "26bdf324b11da6190f38886a3b0f7598", # mechanical ingame
                "8862b370e7c1785c336be63d464f14c7", # device title
                "6a4ca1ab352df8af4a25c50a65bb8963", # screenless system
                "4330217adee809149c8e784e587e1f40", # device title
                "f28cffce4c580b1c28ef0c24e8e25f80", # mechanical ingame
                "76707f5e81e41cb811a8a9f6050ccac7", # screenless system
                "0734aca010260cee0bbf08b08e642fed", # device ingame
                "e940a4fdfd01163dae42bc0fe489c0e9", # device ingame
            ]
            
        return
    
    # checks if a snapshot is ok
    def check_snapshot( self, snapshot ):
        
        if self.pil:
            
            # sanity
            try:
                img = self.Image.open( snapshot )
            except:
                return False
            
            imgmd5 = hashlib.md5( img.tobytes() ).hexdigest()
            imgv = self.ImageStat.Stat( img ).var
            img.close()
            
            if imgmd5 in self.bad_image_list:
                #print("- check_snapshot_pil {} - bad".format(snapshot))
                return False
            elif reduce( lambda x, y: x and y < 0.010, imgv, True ): # 0.005
                #print("- check_snapshot_pil {} - same color".format(snapshot))
                return False
            else:
                #print("- check_snapshot_pil {} - {}".format( snapshot, imgmd5 ))
                return True
        
        else:
            
            # sanity
            try:
                img = open( snapshot, 'rb' )
            except:
                return False
            imgmd5 = hashlib.md5( img.read() ).hexdigest()
            img.close()
            
            if imgmd5 in self.bad_image_list:
                #print("- check_snapshot {} - bad".format(snapshot))
                return False
            else:
                #print("- check_snapshot {} - {}".format( snapshot, imgmd5 ))
                return True
            
        return False
