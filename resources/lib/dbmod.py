# -*- coding: utf-8 -*-

import os, time
import operator # only for sorting by values of a dict instead keys
import sqlite3

# new db for pics
# listdir recursive for progetto
# get set and swl from path
# write into db: path, swl_id and set_id
# select all -> for each set id check pics and attach

# new db for dats
# scan dats, put text into db with p_id
# second table with p_id and swl_id, set_id
# as one dat entry can have more than one set
# select all > for each set check dat, when finished, split dat entries

# dict for best machine
countries = {
    '1NTSC' : ( 'ntsc', ),
    '2PAL'  : ( 'pal', ),
    '3US'   : ( 'usa', 'america', 'nintendo entertainment system /', 'world' ),
    '4JP'   : ( 'jpn', 'japan', 'famicom' ),
    '5EU'   : ( 'euro', ),
    '6EU'   : ( 'euro', 'pal' ),
    '7KR'   : ( 'kor', ),
    '8BR'   : ( 'bra', ),
    #'uk', 'ger', 'fra', 'spa', 'ita', 'ned', 'aus' ],
}

class DBMod:
    
    def __init__(self, db_path, filter_lists = None, pref_country = 'US'):
        
        self.pref_country = pref_country
        self.use_filter = False
        self.order = 'name'
        
        # connect to maston db
        self.gdb = sqlite3.connect(os.path.join(db_path, "umsa.db"))
        self.gdb.text_factory = str
        self.gdbc = self.gdb.cursor()
        
        # connect to status db
        self.sdb = sqlite3.connect(os.path.join(db_path, "status.db"))
        self.sdb.text_factory = str
        self.sdbc = self.sdb.cursor()

        # defines filter with self.filter_tables, self.filter_where
        if filter_lists:
            self.define_filter( filter_lists )
        
        # - db layout:
        #
        #    #table software: id, last played set id (or name,swl), < maybe not needed, see below
        #    table variant: id, last played timestamp, time played, play count, options
        #     - makes it difficult to gather info for software:
        #       get info for all sets
        #       but set with lastest played timestamp = set to choose = no need for software table (:
        #
        #    table favorites: id, set id, fav_id
        #    table fav_lists: id, name
        #
        #    table emus: id, name, exe, working dir, extract zip/7z/chd (means build rom from xml when more than one file)
        #    table emus_swl: id, emus_id, swl id or source name for mame?
        #
        #    table search: better to save last 10 in txt file, easier to read and maintain last ten

        self.sdbc.execute(
            # last_playes = YYYY-MM-DD HH:MM
            # time_played = seconds
            """
            CREATE TABLE IF NOT EXISTS sets(
                id             INT PRIMARY KEY NOT NULL,
                last_played    DATETIME NOT NULL,
                time_played    BIGINT NOT NULL,
                play_count     INT NOT NULL,
                options        TEXT
            )
            """
        )
            
        self.sdbc.execute(
            """
            CREATE TABLE IF NOT EXISTS emu(
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      VARCHAR(100) NOT NULL,
                exe       VARCHAR(100) NOT NULL,
                dir       VARCHAR(200) NOT NULL,
                zip       INT NOT NULL
            )
            """
        )

        self.sdbc.execute(
            """
            CREATE TABLE IF NOT EXISTS emu_conn(
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                emu_id    INT NOT NULL,
                swl       VARCHAR(50),
                source    VARCHAR(100)
            )
            """
        )
        
        self.sdb.commit()
        
        return
            
    def close_db(self):
        self.gdb.close()
        self.sdb.close()
        
    def define_filter(self, filter_lists):
        
        self.filter_tables = []
        self.filter_where  = []
        
        # make a string with enough ?,?,? as in the lists
        if filter_lists['Softwarelists']:
            self.filter_tables.append( "swl" )
            self.filter_where.append(
                "swl.id NOT IN ( %s ) AND swl.id = sets.swllink_id" % (
                    ','.join( filter_lists['Softwarelists'] )
                )
            )
            
        if filter_lists['Game Categories'] or filter_lists['Machine Categories']:
            self.filter_tables.append( "category cat" )
            self.filter_where.append(
                "cat.id NOT IN ( %s ) and cat.id = sets.classification_id" % (
                    ','.join( filter_lists['Game Categories']
                              + filter_lists['Machine Categories']
                            )
                    )
            )
            
        if filter_lists['Players']:
            self.filter_tables.append( "nplayers np" )
            self.filter_where.append(
                "np.id NOT IN ( %s ) AND np.id = sets.nplayers_id" % (
                    ','.join( filter_lists['Players'] )
                )
            )
            
        if filter_lists['Years']:
            self.filter_tables.append( "years y" )
            self.filter_where.append(
                "y.id NOT IN ( %s ) AND y.id = sets.year_id" % (
                    ','.join( filter_lists['Years'] )
                )
            )
            
        # needed for later join so that it begins with , or AND
        # if self.filter_tables:
        #     self.filter_tables.insert( 0, '' )
        #     
        # if self.filter_where:
        #     self.filter_where.insert( 0, '' )
            
        # count
        select_statement = "SELECT COUNT (DISTINCT s.id) \
                            FROM %s \
                            WHERE %s \
                            ORDER BY RANDOM() LIMIT 1" % (
            ",".join( [ "software s", "sets" ] + self.filter_tables ),
            " AND ".join( [ "s.id = sets.softwarelink_id" ] + self.filter_where ),
        )
        
        self.gdbc.execute(select_statement)
        x = self.gdbc.fetchone()
        
        return x[0]
    
    def get_random_id(self):
        
        select_statement = "SELECT DISTINCT s.id \
                            FROM %s \
                            WHERE %s \
                            ORDER BY RANDOM() LIMIT 1" % (
            ",".join( [ "software s", "sets" ] + self.filter_tables ),
            " AND ".join( [ "s.id = sets.softwarelink_id" ] + self.filter_where ),
        )
        
        self.gdbc.execute(select_statement)
        x = self.gdbc.fetchone()
        
        return x[0]

    def get_set_ids_for_software(self, software_id):
        
        sets = []        
        self.gdbc.execute(
            "SELECT id FROM sets \
             WHERE softwarelink_id = ?", (software_id,)
        )
        for i in self.gdbc.fetchall():
            sets.append(i[0])
            
        return sets
    
    def get_status_for_software(self, software_id):

        sets = self.get_set_ids_for_software(software_id)

        # get count of play_count and time_played
        select_statement = "SELECT COUNT(play_count), COUNT(time_played) \
                            FROM sets WHERE id IN ( %s )" % (
            ','.join( ['?'] * len(sets) )
        )
        self.sdbc.execute( select_statement, sets )
        
        x = self.sdbc.fetchone()
        print x # TODO: check
        
        return x
    
    def get_series(self, software_id):
        
        self.gdbc.execute(
            "SELECT series_id \
             FROM series_seq WHERE software_id = ?", ( software_id, )
        )
        x = self.gdbc.fetchone()
        if not x:
            return None
        self.gdbc.execute(
            "SELECT software_id \
             FROM series_seq WHERE series_id = ? ORDER BY seqno", ( x[0], )
        )
        ll = []
        for i in self.gdbc.fetchall():
            self.gdbc.execute(
                "SELECT DISTINCT s.id, s.name, y.name, m.name \
                 FROM software s, sets v, \
                      year y, maker m \
                 WHERE s.id = v.softwarelink_id AND y.id = s.year_id \
                       AND m.id = s.developer_id AND s.id = ?", (i[0],)
            )
            r = self.gdbc.fetchone()
            ll.append( { 'id'    : r[0],
                         'label' : '%s - %s, %s' % ( r[2], r[1], r[3] )
                        }
                )
        return ll
    
    def check_series(self, software_id):
        
        self.gdbc.execute(
            "SELECT series_id \
             FROM series_seq WHERE software_id = ?", ( software_id, )
        )
        x = self.gdbc.fetchone()
        
        if x:
            self.gdbc.execute(
                "SELECT COUNT(series_id) \
                 FROM series_seq WHERE series_id = ?", ( x[0], )
            )
            return self.gdbc.fetchone()[0]
        else:
            return None

    def make_time_nice(self, t):
        
        m, s = divmod( int( time.time()
                            - time.mktime(
                                    time.strptime(
                                        t, "%Y-%m-%d %H:%M"
                                    )
                                )
                            ), 60
                      )
        h, m = divmod(m, 60)
        day, h = divmod(h, 24)
        if day > 0:
            last_nice = "%dd" % (day)
        elif h == 0:
            last_nice = "%dm" % (m,)
        else:
            last_nice = "%d:%02dh" % (h, m)
            
        return last_nice
    
    def get_status_for_set(self, set_id):
        
        self.sdbc.execute(
            "SELECT * FROM sets WHERE ID = ?", (set_id,)
        )
        i = self.sdbc.fetchone()
        if not i:
            return
        
        m, s = divmod(i[2], 60)
        h, m = divmod(m, 60)
        time_played = "%d:%02d" % (h, m)
        
        x = {
            'last_played'   : i[1],
            'time_played'   : time_played,
            'play_count'    : i[3],
            'options'       : i[4],
            'last_nice'     : self.make_time_nice(i[1]),
        }
        
        return x
    
    def get_all_emulators(self):
        
        self.sdbc.execute( "SELECT id, name, exe, dir, zip FROM emu ORDER BY name" )
        
        d = {}
        for i in self.sdbc.fetchall():
            d[ i[1] ] = {
                'id'    : i[0],
                'exe'   : i[2],
                'dir'   : i[3],
                'zip'   : i[4]
            }
            
        return d
            
    
    def get_emulator(self, source=None, swl_name=None):
    
        if source:
            self.sdbc.execute(
                "SELECT e.name, e.exe, e.dir, e.zip \
                 FROM emu e, emu_conn ec \
                 WHERE ec.source = ? AND ec.emu_id = e.id \
                 ORDER BY e.name", ( source, )
            )
        else:
            self.sdbc.execute(
                "SELECT e.name, e.exe, e.dir, e.zip \
                 FROM emu e, emu_conn ec \
                 WHERE ec.swl = ? AND ec.emu_id = e.id \
                 ORDER BY e.name", ( swl_name, )
            )
        
        d = {}
        for i in self.sdbc.fetchall():
            d[ i[0] ] = {
                'exe'   : i[1],
                'dir'   : i[2],
                'zip'   : i[3]
            }
            
        return d
                
    def save_emulator(
            self, name, exe, working_dir, zip_support, source=None, swl_name=None
        ):
        
        self.sdbc.execute(
            "INSERT INTO emu ( name, exe, dir, zip ) \
             VALUES (?,?,?,?)", (
                name, exe, working_dir, zip_support
            )
        )
        self.sdb.commit()
        emu_id = self.sdbc.lastrowid
        return self.connect_emulator( emu_id, source=source, swl_name=swl_name )
    
    def connect_emulator( self, emu_id, source=None, swl_name=None ):
        
        if source:
            self.sdbc.execute(
                "INSERT INTO emu_conn ( emu_id, source ) \
                VALUES (?,?)", (
                    emu_id, source
                )
            )
        elif swl_name:
            self.sdbc.execute(
                "INSERT INTO emu_conn ( emu_id, swl ) \
                 VALUES (?,?)", (
                    emu_id, swl_name
                )
            )
        else:
            return "error"
        
        self.sdb.commit()
        return
        
    def write_options(self, set_id, options):
        
        self.sdbc.execute(
            "UPDATE sets SET options = ? WHERE id = ?", (set_id, options)
        )
        self.sdb.commit()
    
    def write_status_after_play(self, set_id, played_seconds):
        
        date = time.strftime("%Y-%m-%d %H:%M")
        
        self.sdbc.execute(
            "SELECT time_played, play_count FROM sets WHERE id = ?", (set_id,)
        )
        set_fetch = self.sdbc.fetchone()
        
        if set_fetch:
            # update data
            set_data = (date, played_seconds+set_fetch[0], set_fetch[1]+1, set_id)
            self.sdbc.execute(
                "UPDATE sets \
                 SET last_played = ?, time_played = ?, play_count = ? \
                 WHERE id = ?", (set_data)
            )
        else:
            # new data
            set_data = (set_id, date, played_seconds, 1)
            self.sdbc.execute(
                "INSERT INTO sets (id, last_played, time_played, play_count) \
                 VALUES (?,?,?,?)", (set_data)
            )
        
        self.sdb.commit()
        return
    
    def get_latest_by_software( self, software_id):
        
        sets = self.get_set_ids_for_software(software_id)
        
        select_statement = "SELECT id FROM sets WHERE id IN ( %s ) \
                            ORDER BY last_played DESC LIMIT 1" % (
                ','.join( ['?'] * len(sets) )
            )
        self.sdbc.execute( select_statement, sets )
        set_id = self.sdbc.fetchone()
        if set_id:
            set_id = set_id[0]
        
        return set_id
    
    def get_prevnext_software( self, sid, prev_or_next ):

        if prev_or_next == 'prev':
            direction = "DESC"
            snd = "<"
            pos = 100
        else:
            direction = "ASC"
            snd = ">="
            pos = 1
            
        self.gdbc.execute(
            "SELECT s.name FROM software s WHERE s.id = ?", (sid,)
        )
        sname = self.gdbc.fetchone()[0]
        
        # duplicate from execute_statement
        # build tables and where clause
        if self.use_filter:
            tables = ','.join(
                [ "software s" , "sets" ] + self.filter_tables
            )
            where = " AND ".join(
                [ "s.id = sets.softwarelink_id" ] + self.filter_where
            )
        else:
            tables = "software s, sets"
            where = "s.id = sets.softwarelink_id"
        
        # add self.table and self.where
        if self.table:
            if self.table not in tables:
                tables += ", " + self.table
        if self.where:
            where += " AND " + self.where

        if "year y" not in tables:
            tables += ", year y"
        if "maker m" not in tables:
            tables += ", maker m"
            
        if self.order == 'name':
            order = 's.name'
        elif self.order == 'year':
            order = 'y.name, s.name'
        elif self.order == 'publisher':
            order = 'm.name, s.name'
        else:
            self.order = 's.name'
            
        execute = "SELECT DISTINCT s.name, s.id, y.name, m.name \
             FROM %s \
             WHERE y.id = s.year_id AND m.id = s.developer_id \
                   AND s.name %s ? AND %s ORDER BY %s %s LIMIT 100" % (
                tables, snd, where, order, direction )
        print execute
        self.gdbc.execute( execute, (sname,) )
        slist = self.gdbc.fetchall()
        
        if prev_or_next == 'prev':
            pos = len(slist)
            software_list = reversed(slist)
        else:
            pos = 0
            software_list = slist
            
        d = []
        if ( prev_or_next == 'next'
             or ( prev_or_next == 'prev' and len(slist) == 100 )
           ):
            d.append( { 'id' : 'prev', 'label' : '<<< PREVIOUS' } )
            pos += 1
        for i in software_list:
            d.append ({ "id" : i[1],
                        "label" : "%s - %s - %s" % (
                           i[0], i[2], i[3]
                         )
                     })
        if ( prev_or_next == 'prev'
             or ( prev_or_next == 'next' and len(slist) == 100 )
           ):
            d.append( { 'id' : 'next', 'label' : '>>> NEXT' } )
            pos -= 1
        
        return d, pos
        
    def execute_statement(self, set_id ):
        
        # build tables and where clause
        if self.use_filter:
            tables = ','.join(
                [ "software s" , "sets" ] + self.filter_tables
            )
            where = " AND ".join(
                 self.filter_where + [ "s.id = sets.softwarelink_id" ]
            )
        else:
            tables = "software s, sets"
            where = "s.id = sets.softwarelink_id"
        
        # add self.table and self.where
        if self.table:
            if self.table not in tables:
                tables += ", " + self.table
        if self.where:
            where += " AND " + self.where
        
        # get software name from set id
        self.gdbc.execute(
            "SELECT s.name \
             FROM software s, sets \
             WHERE sets.id = ? \
             AND s.id = sets.softwarelink_id", (set_id,)
        )
        sname = self.gdbc.fetchone()[0]
        
        # count overall
        count_statement = 'SELECT COUNT(DISTINCT s.id) \
             FROM %s WHERE %s' % ( tables, where )
        print count_statement
        self.gdbc.execute(count_statement)
        result_count = self.gdbc.fetchone()[0]
        
        if "year y" not in tables:
            tables += ", year y"
        if "maker m" not in tables:
            tables += ", maker m"
            
        if self.order == 'name':
            order = 's.name'
        elif self.order == 'year':
            order = 'y.name, s.name'
        elif self.order == 'publisher':
            order = 'm.name, s.name'
        else:
            self.order = 's.name'
            
        # get previous 50
        prev_statement = 'SELECT DISTINCT s.name \
             FROM %s \
             WHERE y.id = s.year_id AND m.id = s.developer_id \
                   AND s.name <= ? AND %s \
             ORDER BY %s DESC LIMIT 50' % ( tables, where, order )
        print prev_statement
        self.gdbc.execute( prev_statement, (sname,) )
        prev = self.gdbc.fetchall()
        
        # get the software list
        fetch_statement = 'SELECT DISTINCT s.name, s.id, y.name, m.name \
             FROM %s \
             WHERE y.id = s.year_id AND m.id = s.developer_id \
                   AND s.name >= ? AND %s ORDER BY %s ASC LIMIT 100' % (
                tables, where, order
            )
        print fetch_statement
        self.gdbc.execute( fetch_statement, (prev[-1][0],) )
        slist = self.gdbc.fetchall()
        
        # create dict for return, get pos, set prev/next
        d = []
        pos = 0
        x = 0
        if len(prev) == 50:
            d.append( { 'id' : 'prev', 'label' : '<<< PREVIOUS' } )
            x += 1
        for i in slist:
            # get a setname for a pic
            fetch_setname = "SELECT s.name, swl.name \
                             FROM sets s, year y, swl \
                             WHERE s.softwarelink_id = ? \
                                   AND s.year_id = y.id \
                                   AND s.swllink_id = swl.id \
                             ORDER BY y.name LIMIT 1"
            self.gdbc.execute( fetch_setname, (i[1],) )
            setname = self.gdbc.fetchone()
            d.append ( { "id" : i[1],
                         "setname" : setname[0],
                         "swl" : setname[1],
                         "label" : "%s - %s - %s" % (
                            i[0], i[2], i[3]
                        )
                     } )
            if sname == i[0]:
                pos = x
            x += 1
        if len(slist) == 100:
            d.append( { 'id' : 'next', 'label' : '>>> NEXT' } )
            
        return d, pos, result_count

    def get_by_software(self, set_id):
        
        self.table = ''
        self.where = ''
        
        return self.execute_statement( set_id )

    def get_software_for_source(self, set_id, source ):
        
        self.table = ''
        self.where = 'sets.source = "%s"' % (source,)

        return self.execute_statement( set_id )
    
    def get_by_cat(self, cat, set_id ):
        
        self.table = 'category cat'
        self.where = 'cat.name = "%s" AND cat.id = sets.classification_id' % (
            cat,
        )
        
        return self.execute_statement( set_id )
    
    def get_by_year(self, year, set_id ):
        
        self.gdbc.execute(
            "SELECT id FROM year WHERE name = ?", ( year, )
        )
        y_id = self.gdbc.fetchone()[0]
        
        self.table = 'year y'
        self.where = 'sets.id in (SELECT sets.id FROM sets, year y \
                      WHERE y.id = %s AND y.id = sets.year_id)' % (y_id,)
        
        return self.execute_statement( set_id )
        
    def get_by_maker(self, maker, set_id ):
        
        self.gdbc.execute(
            "SELECT id FROM maker WHERE name = ?", ( maker, )
        )
        m_id = self.gdbc.fetchone()[0]
        
        self.table = 'maker m'
        self.where = 'sets.id in (SELECT sets.id FROM sets, maker m \
                      WHERE m.id = %s AND m.id = sets.publisher_id)' % (m_id,)
        
        return self.execute_statement( set_id )
    
    def get_by_swl(self, swl_name, set_id ):

        self.gdbc.execute(
            "SELECT id FROM swl WHERE name = ?", ( swl_name, )
        )
        swl_id = self.gdbc.fetchone()[0]
        
        self.table = "swl"
        self.where = "swl.id = %s AND swl.id = sets.swllink_id" % ( swl_id, )
        
        return self.execute_statement( set_id )
    
    def get_last_played(self, order):
        
        d = []
        e = {}

        # get status for sets        
        self.sdbc.execute(
            "SELECT id, last_played, play_count, time_played FROM sets \
             ORDER BY %s DESC LIMIT 100" % (order)
        )
        lastplay = self.sdbc.fetchall()
        
        # get software info for sets from status.db
        for i in lastplay:
            self.gdbc.execute(
                "SELECT s.name, s.id, y.name, m.name \
                 FROM software s, sets v, \
                      year y, maker m \
                 WHERE s.id = v.softwarelink_id AND y.id = s.year_id \
                       AND m.id = s.developer_id AND v.id = ?", ( i[0], )
            )
            software = self.gdbc.fetchone()
            
            # put in dict to summarize sets
            if software[1] in e.keys():
                print e[software[1]]
                e[software[1]]["play_count"] += i[2]
                e[software[1]]["time_played"] += i[3]
                if e[software[1]]["last_played"] < i[1]:
                    e[software[1]]["last_played"] = i[1]
            else:
                e[software[1]] = {
                    "time_played"   : i[3],
                    "last_played"   : i[1],
                    "play_count"    : i[2],
                    "name"          : software[0],
                    "year"          : software[2],
                    "developer"     : software[3],
                }
            
        # sort dict after value in var order and create list for return
        for k, v in reversed(sorted( e.items() , key=lambda t: t[1][order] )):
                
            m, s = divmod(v["time_played"], 60)
            h, m = divmod(m, 60)
            time_played = "%d:%02d" % (h, m)
                
            last_nice = self.make_time_nice(v['last_played'])
        
            if order == "time_played":
                label = "%s - %s - %s : %s - %s, %s" % (
                    time_played,
                    v["play_count"],
                    last_nice,
                    v["name"],
                    v["year"],
                    v["developer"],
                )
            elif order == "play_count":
                label = "%s - %s - %s : %s - %s, %s" % (
                    v["play_count"],
                    time_played,
                    last_nice,
                    v["name"],
                    v["year"],
                    v["developer"],
                )
            else:
                label = "%s : %s (%s, %s), %s, %s" % (
                    last_nice,
                    v["name"],
                    time_played,
                    v["play_count"],
                    v["year"],
                    v["developer"],
                )
            
            d.append ( { "id" : k, "label" : label } )
            
        return d, 0
    
    def get_parts_for_set_id(self, set_id):
        
        # sets can have more than one media
        # like 2 floppies or 1 floppy and 1 hdd or cd-rom
        self.gdbc.execute(
            "SELECT   p.name, pv.name \
             FROM     part_set pv, part p \
             WHERE    p.id = pv.part_id AND pv.variant_id = ? \
             ORDER BY p.name", ( set_id, )
        )
        return self.gdbc.fetchall()
    
    def create_cmdline(self, parts, devices, setname ):

        cmd_options = []
        first_device = None
        
        for device in devices:
            # split the interface
            # because interface="c64_cart,vic10_cart" for c128_cart and c64_cart
            for interface in device[1].split(','):
                for part in parts:
                    if interface == part[1]:
                        cmd_options.append(
                            "-%s %s:%s" % ( device[0], setname, part[0] )
                        )
                        # use device from first hit for snaps and states
                        if not first_device:
                            first_device = device[0]
                        parts.remove(part)
                        break
        
        return cmd_options, first_device

    # create commandline options for mame        
    def get_cmd_line_options(self, set_id, set_name, system_name, swl_name):
        
        # get options for softwarelist
        ## this is manually set coz some swls need special options
        ## like a device in a slot so the system supports hdds
        self.gdbc.execute(
            "SELECT options FROM swl WHERE name = ?", (swl_name,)
        )
        swl_options = self.gdbc.fetchone()

        # get id for system        
        self.gdbc.execute(
            "SELECT v.id \
             FROM sets v, swl \
             WHERE v.swllink_id = swl.id AND swl.name = ? AND v.name = ?",
            ('mame', system_name)
        )
        system_id = self.gdbc.fetchone()
        
        # get devices supported by the system
        self.gdbc.execute(
            "SELECT d.name, dv.name \
             FROM device_set dv, device d \
             WHERE d.id = dv.device_id AND dv.variant_id = ? \
             ORDER BY d.name", (system_id[0],) )
        _devices = self.gdbc.fetchall()
        
        # get all parts for the choosen set
        _part = self.get_parts_for_set_id(set_id)
        #print "origsetid",set_id
        #print "origparts",_part
        
        # check if we have a requirement in sharedfeat
        self.gdbc.execute(
            "SELECT sfv.name FROM sharedfeature sf, sharedfeature_set sfv \
             WHERE sf.name = 'requirement' AND sf.id = sfv.sharedfeat_id AND sfv.variant_id = ? \
             ORDER BY sf.name", (set_id,)
        )
        _sharedfeat = self.gdbc.fetchone()

        # create cmd line
        _cmd_options, first_device = self.create_cmdline(
            list(_part), _devices, set_name
        )
                    
        if _cmd_options:
            # add additional manual swl options
            if swl_options[0]:
                system_name += ' '+swl_options[0]
                
            # sharedfeat requirements for set from xml
            # not needed anymore since, thx ajr
            # https://github.com/mamedev/mame/commit/17af0f9c661e0855607703faf66c1e807e888d82
            # ... is reverted
            
            if _sharedfeat:
                # security if definition for sharedfeat_requirement
                # is not swl:set
                if ':' in _sharedfeat[0]:
                    _swl, _set = _sharedfeat[0].split(':')
                else:
                    _set = _sharedfeat[0]
                    _swl = None
                # when definition is ok
                if _swl:
                    # create new cmdline option for requirement
                    print "set_swl",_set,_swl
                    _setinfo = self.get_info_by_set_and_swl( _set, _swl )
                    print "setid",_setinfo
                    _parts2 = self.get_parts_for_set_id( _setinfo['set_id'] )
                    print "parts",_parts2
                    _cmdopt, x = self.create_cmdline(
                        list(_parts2), _devices, _set
                    )
                    print "cmdopt",_cmdopt
                    system_name += ' '+' '.join(_cmdopt)
                # else add the requirement set as option
                # directly after machine name
                # hopefully most of the time mame will then
                # find the correct swl entry
                else:
                    system_name += ' '+_set
            
            # when we know the devices also set -snapname and -statename
            cmd_options = "{0} {1} -snapname %g/%d_{2}/%i -statename %g/%d_{2}".format(
                system_name,
                " ".join(_cmd_options),
                first_device
            )
            
        # when we have no cmd_options then the system needs a device
        # in a slot so it can support the media, thus we have no hit within
        # the devices and parts and therefore no cmd_options
        # little hack: normally we would need to get devices from mame
        # with the correct device in a slot: mame -slot xyz -lm
        elif swl_options[0]:
            cmd_options = "%s %s %s" % (system_name, swl_options[0], set_name)
            
        # last exit is to just start mame with the system and set as options
        else:
            cmd_options = "%s %s" % (system_name, set_name)

        return cmd_options
    
    def get_all_dbentries(self, cat):
        
        if cat == "Softwarelists":
            select_placeholders = (
                'description', 'swl', 'swllink', '', 'description'
            )
        elif cat == "Game Categories":
            select_placeholders = (
                'name', 'category', 'classification',
                'AND t.flag = 0', 'name'
            )
        elif cat == "Machine Categories":
            select_placeholders = (
                'name', 'category', 'classification',
                'AND t.flag = 1', 'name'
            )
        elif cat == "Years":
            select_placeholders = (
                'name', 'year', 'year', '', 'name'
            )
        elif cat == "Players":
            select_placeholders = (
                'name', 'nplayers', 'nplayers', '', 'name'
            )
        else:
            return
        
        select_statement = "SELECT t.id, t.%s, count(distinct s.id) \
                            FROM %s t, software s, sets v \
                            WHERE t.id = v.%s_id and s.id = v.softwarelink_id %s \
                            GROUP BY t.id ORDER BY t.%s" % select_placeholders
        
        self.gdbc.execute(select_statement)
        
        return self.gdbc.fetchall()
    
    def search_single(self, search):
        
        self.gdbc.execute(
            "SELECT DISTINCT s.id, s.name, y.name, m.name \
             FROM software s, sets v, \
                  year y, maker m \
             WHERE s.id = v.softwarelink_id AND y.id = s.year_id \
                   AND m.id = s.developer_id AND v.gamename like ? \
             ORDER BY s.name LIMIT 1", (search+'%',)
        )
        r = self.gdbc.fetchone()
        if r:
            ret = { 'id'    : r[0],
                    'label' : '%s - %s, %s' % ( r[2], r[1], r[3] )
                   }
        else:
            ret = { 'id'    : 0,
                    'label' : '???? - not found: %s' % ( search, )
                   }
        
        return ret
        
    ### get search results
    def get_searchresults(self, search):
        
        # TODO:
        # - single word search: split by " ": v.gamename IN ('test', 'wrum')
        #
        #      - remove s.name, problem with showing gamename when s.name is selected
        #      - use filters or present option to use filters
        #
        # LATER - show button for next/prev page
        #       - save last 10 search terms and make as a popup for search button incl new search
        
        self.gdbc.execute(
            "SELECT COUNT(DISTINCT s.id) \
             FROM software s, sets v \
             WHERE s.id = v.softwarelink_id AND v.gamename LIKE ?",
            ("%"+search+"%",)
        )
        results_count = self.gdbc.fetchone()[0]
        
        self.gdbc.execute(
            "SELECT DISTINCT s.id, s.name, y.name, m.name \
             FROM software s, sets v, \
                  year y, maker m \
             WHERE s.id = v.softwarelink_id AND y.id = s.year_id \
                   AND m.id = s.developer_id AND v.gamename LIKE ? \
             ORDER BY s.name LIMIT 100", ("%"+search+"%",)
        )
        r = self.gdbc.fetchall()

        c = 0
        pos = None
        result = []
        for i in r:
            result.append(
               { 'id' : i[0],
                 'label' : '%s - %s, %s' % ( i[2], i[1], i[3] )
               }
            )
            # check if search is in beginning of s.name and set pos
            if search.lower() == i[1][:len(search)].lower() and not pos:
                pos = c
            c += 1
        if not pos:
            pos = 0
            
        # if results_count > 100:
        #     result.append( {'id' : 'next', 'label' : '>>> NEXT'} )

        # print "search pos, c: %s, %s" % ( str(pos), str(c) )
        return result, pos, results_count
    
    def get_machine_name(self, machine_id):
        
        self.gdbc.execute(
            "SELECT m.name, m.gamename \
             FROM sets m \
             WHERE m.id = ?", ( machine_id, )
        )
        machine = self.gdbc.fetchone()
        return machine[0], machine[1]
        
    ### get_machines: get original/compatible machines for 1 swl
    def get_machines(self, swl_name, machine=None):
        
        self.gdbc.execute(
            "SELECT DISTINCT \
                s.id, s.name, s.gamename, s.detail, \
                y.name, m.name, ss.status, ss.filtr \
             FROM \
                sets s, swl sw, \
                swl_status ss, year y, \
                maker m \
            WHERE \
                sw.name = ? \
                AND sw.id = ss.swl_id \
                AND s.id = ss.system_id \
                AND y.id = s.year_id \
                AND m.id = s.publisher_id \
            ORDER BY \
                ss.status DESC, y.name, s.name",
            (swl_name,)
        )
        
        machines = []
        pos, x = 0,0
        for s in self.gdbc.fetchall():
            if s[7]:
                label = "%s - %s (%s) - %s, %s" % (
                    s[4], s[2], s[5], s[6], s[7]
                )
            else:
                label = "%s - %s (%s) - %s" % (
                    s[4], s[2], s[5], s[6]
                )
            label2 = s[2] #[:len(s[2]) - len(s[3])].strip() # remove detail
            machines.append(
                {
                    'id'       : s[0],
                    'label'    : label,
                    'label2'   : label2,
                    'name'     : s[1],
                    'detail'   : s[3],
                    'fullname' : s[2],
                    'status'   : s[6],
                    'filter'   : s[7],
                }
            )
            if machine == s[1]:
                pos = x
            x += 1

        return machines, pos
    
    def get_swl_id( self, swl_name ):
        
        self.gdbc.execute(
            "SELECT id FROM swl WHERE name = ?", ( swl_name, )
        )
        return self.gdbc.fetchone()[0]
    
    def get_set_name( self, set_id ):
        
        self.gdbc.execute(
            "SELECT name FROM sets WHERE id = ?", ( set_id, )
        )
        return self.gdbc.fetchone()[0]
    
    def get_info_for_id(self, _id):
        
        self.gdbc.execute(
            "SELECT DISTINCT v.id, v.name, v.gamename, c.name, c.flag \
             FROM sets v, swl, \
                  year y, category c \
             WHERE v.id = swl.system_id AND y.id = v.year_id \
                   AND c.id = v.classification_id AND swl.id IN \
                   ( SELECT DISTINCT swl.id \
                     FROM sets v, software s, \
                          swl, year y \
                     WHERE v.softwarelink_id = s.id AND y.id = s.year_id \
                           AND v.swllink_id = swl.id AND s.id = ? ) \
             ORDER BY y.name DESC", ( _id, ) )
        systems = self.gdbc.fetchall()
        return systems
    
    def get_sets_for_system(self, software_id, system_id):
        
        # get_sets: get all sets for s.id and system (can mean more than 1 swl)
        self.gdbc.execute(
            "SELECT \
                v.id, v.name, v.gamename, v.detail, v.source, \
                y.name, m.name, swl.name, \
                v.display_type, v.display_rotation, c.name, c.flag \
             FROM \
                sets v, swl, \
                year y, maker m, \
                category c \
             WHERE \
                v.softwarelink_id = ? \
                AND v.year_id = y.id \
                AND v.publisher_id = m.id \
                AND c.id = v.classification_id \
                AND v.swllink_id = swl.id \
                AND swl.id IN \
                    ( SELECT DISTINCT swl.id \
                      FROM swl, sets v \
                      WHERE swl.system_id = v.id AND v.id = ? ) \
             ORDER BY v.cloneof_id, v.detail, v.gamename",
            ( software_id, system_id )
        )
        
        sets = []
        for i in self.gdbc.fetchall():
            sets.append(
                {
                    'id'                  : i[0],
                    'name'                : i[1],
                    'gamename'            : i[2],
                    'detail'              : i[3],
                    'source'              : i[4],
                    'year'                : i[5],
                    'publisher'           : i[6],
                    'swl_name'            : i[7],
                    'display_type'        : i[8],
                    'display_rotation'    : i[9],
                    'category'            : i[10],
                    'category_is_machine' : i[11],
                }
            )
        
        return sets
    
    def get_best_machine_for_set(self, swl_name, detail, swl_machine_id):
        
        best_machine = None
        country = ''

        # get originals, compatible machines
        machines, dummy = self.get_machines(swl_name)
        
        # check machines
        if len(machines) == 1:
            return machines[0]
        elif len(machines) == 0:
            return None
        # check if only one original
        elif ( machines[0]['status'] == "original"
               and machines[1]['status'] == "compatible" ):
            return machines[0]
        # check if swl_machine is in machines
        for m in machines:
            #print m
            if m['id'] == swl_machine_id:
                best_machine = m
                #print "-- yeah, got %s from db" % (best_machine,)
        # no hit until now, set first machine
        if not best_machine:
            best_machine = machines[0]
            #print "-- ok, damn, setting the first entry %s" % (best_machine)
        # exception for famicom_flop
        # TODO famicom should be disconnected in mame source
        if swl_name == "famicom_flop":
            return machines[1]
        
        # get country from detail
        #for c in reversed( sorted( countries.keys() ) ):
        for c in sorted( countries.keys() ):
            for d in countries[c]:
                if d in detail.lower():
                    # check gamename of machines for country from detail
                    #print "-- check machines for country %s" % ( d, )
                    # first try actual best
                    for c2 in countries[c]:
                        if c2 in best_machine['fullname'].lower():
                            #print "-- use best machine"
                            return best_machine
                    # now check all machines
                    for m in machines:
                        for c2 in countries[c]:
                            if c2 in m['fullname'].lower():
                                best_machine = m
                                #print "-- got machine %s over country" % (best_machine)
                                return best_machine
        
        # return best machine
        return best_machine

    # get all sets nicely sorted (last played, prefered history, year)
    # includes a best machine to use for swl set
    def get_all_for_software(self, software_id):
        
        # TODO:
        # - include pref country (select it or make it first in list?)
        
        time1 = time.time()
        
        #print "get_all_for_software"
        pos_machine = 0
        pos_set = 0
        all_sets = []
        
        # get all sets for software id
        self.gdbc.execute(
            "SELECT \
                v.id, v.name, v.gamename, v.detail, v.source, \
                y.name, m.name, swl.name, swl.system_id, \
                v.display_type, v.display_rotation, c.name, c.flag, \
                np.name, v.cloneof_id \
             FROM \
                sets v, swl, \
                year y, maker m, \
                category c, nplayers np \
             WHERE \
                v.softwarelink_id = ? \
                AND v.year_id = y.id \
                AND v.publisher_id = m.id \
                AND c.id = v.classification_id \
                AND np.id = v.nplayers_id \
                AND v.swllink_id = swl.id \
             ORDER BY \
                y.name, v.cloneof_id, v.gamename",
            ( software_id, )
        )
        all_sets.append( self.gdbc.fetchall() )
        
        # TEST add other software with same name
        # TODO: give back status so it can be shown in textbox
        # get software name
        self.gdbc.execute(
            "SELECT name FROM software WHERE id = ?", (software_id,)
        )
        software_name = self.gdbc.fetchone()[0]
        # get all software ids for software name
        self.gdbc.execute(
            "SELECT id FROM software WHERE name = ?", (software_name,)
        )
        software_ids = self.gdbc.fetchall()
        for i in software_ids:
            #print "-- %s - %s" % (software_id, i[0])
            if software_id == i[0]:
                continue
            #print "-- oh look, different software with the same name"
            self.gdbc.execute(
                "SELECT \
                    v.id, v.name, v.gamename, v.detail, v.source, \
                    y.name, m.name, swl.name, swl.system_id, \
                    v.display_type, v.display_rotation, c.name, c.flag, \
                    np.name, v.cloneof_id \
                 FROM \
                    sets v, swl, \
                    year y, maker m, \
                    category c, nplayers np \
                 WHERE \
                    v.softwarelink_id = ? \
                    AND v.year_id = y.id \
                    AND v.publisher_id = m.id \
                    AND c.id = v.classification_id \
                    AND np.id = v.nplayers_id \
                    AND v.swllink_id = swl.id \
                 ORDER BY \
                    y.name, v.cloneof_id, v.gamename",
                ( i[0], )
            )
            all_sets.append( self.gdbc.fetchall() )
            
        diff_machines = {}
        c = 1
        for ds in all_sets:
            for s in ds:
                
                dm = ''
                
                # get last_played
                lp = self.get_status_for_set(s[0])
                #print "last played", lp
                
                if s[8] == 270257: # machine mame
                    # dm is the parent
                    if s[14]:
                        dm = s[14]
                    else:
                        dm = s[0]
                    # dm = s[11] use category
                    bm = None
                    machine_name = 'mame'
                    if s[12]: # ismachine
                        machine_label = s[11]
                    else:
                        machine_label = 'Arcade'
                else: # swl
                    # diff machine is swl machine
                    dm = str(s[8]) # TODO: to test used machine name from swl
                    # get best machine
                    bm = self.get_best_machine_for_set( s[7], s[3], s[8] )
                    #print "best machine:", bm
                    if bm:
                        machine_name = bm['name']
                        machine_label = bm['label2']
                    else:
                        self.gdbc.execute(
                            "SELECT name, gamename, detail \
                             FROM sets \
                             WHERE id = ?", ( s[8], )
                        )
                        x = self.gdbc.fetchone()
                        machine_name = x[0]
                        machine_label = x[1] #[:len(x[1]) - len(x[2])].strip() # remove detail
                
                # TODO: check for machine from software
                # and set first otherwise problem
                # when more machines with earliest year
                
                # create key in diff_machines
                if dm not in diff_machines:
                    diff_machines[dm] = {
                        'id'      : c,
                        'setlist' : []
                    }
                    c += 1
                    
                # TODO: what is really needed?
                # swl system is not needed?
                # make lp 3 entries here?
                
                diff_machines[dm]['setlist'].append(
                    {
                        'id'                    : s[0],
                        'name'                  : s[1],
                        'gamename'              : s[2],
                        'detail'                : s[3],
                        'source'                : s[4],
                        'year'                  : s[5],
                        'publisher'             : s[6],
                        'swl_name'              : s[7],
                        'swl_system_id'         : s[8],
                        'machine_name'          : machine_name,
                        'machine_label'         : machine_label,
                        'display_type'          : s[9],
                        'display_rotation'      : s[10],
                        'category'              : s[11],
                        'nplayers'              : s[13],
                        'clone'                 : s[14],
                        'is_machine'            : s[12],
                        'last_played'           : lp,
                    }
                )
        
        # create list to return
        return_list = []
        # sort seems to work for sorting by id
        sorted_x = sorted( diff_machines.items(), key=operator.itemgetter(1) )
        for i in sorted_x:
            return_list.append( i[1]['setlist'] )
        # get absolut latest played
        latest_set_id = self.get_latest_by_software(software_id)
        # find latest in return_list
        if latest_set_id:
            x = 0
            for i in return_list:
                y = 0
                for j in i:
                    if j['id'] == latest_set_id:
                        pos_machine = x
                        pos_set = y
                        break
                    y += 1
                x += 1  
        
        time2 = time.time()
        print "- get_all complete  %0.3f ms" % ( (time2-time1)*1000.0 )      
        return return_list, pos_machine, pos_set
    
    def get_info_by_set_and_swl(self, setname, swlname):
        
        # TODO: gamename is complete setname, do i want it without detail?
        
        self.gdbc.execute(
            "SELECT v.id, v.gamename, y.name, m.name, s.id \
             FROM software s, sets v, \
                  swl, year y, maker m \
             WHERE s.id = v.softwarelink_id AND v.swllink_id = swl.id \
                   AND y.id = v.year_id AND m.id = v.publisher_id \
                   AND v.name = ? AND swl.name = ?",
            ( setname, swlname )
        )
        r = self.gdbc.fetchone()
        result = {
            'software_id' : r[4],
            'set_id'      : r[0],
            'label'       : '%s - %s, %s' % ( r[2], r[1], r[3] )
        }
        return result
    
    # used by picture screensaver
    def get_info_by_filename( self,
                              filename,
                              dirname,
                              progetto_path,
                              media_folder
                            ):
        
        name = ''
        swl = None
        info = ''
        systempic = None
        snapshot = None
        snaporientation = 'horizontal'
        
        #check if directory is softwarelist based
        self.gdbc.execute(
            "SELECT swl.id, v.name \
             FROM swl, sets v \
             WHERE swl.name = ? AND swl.system_id = v.id", ( dirname, ) )
        swl_id = self.gdbc.fetchone()
        # if not then we have a picture from mame
        if swl_id is None:
            # so set mame as swl and snapshot path
            self.gdbc.execute(
                'SELECT swl.id, v.name \
                 FROM swl, sets v \
                 WHERE swl.name = "mame" AND swl.system_id = v.id'
            )
            swl_id = self.gdbc.fetchone()
            # set snapshot paths
            snapshot = os.path.join(
                progetto_path , 'snap/snap' , filename + '.png' )
            if not os.path.isfile(snapshot):
                snapshot = None
                
        # use variant game name or software name (v.gamename without detail like mame launcher?)
        self.gdbc.execute(
            "SELECT v.gamename, y.name, m.name, swl.name, c.name, \
                    v.display_type, v.display_rotation, c.flag \
            FROM software s, sets v, year y, \
                 maker m, swl, category c \
            WHERE v.name = ? AND swl.id = ? \
                  AND v.softwarelink_id = s.id AND v.year_id = y.id \
                  AND v.publisher_id = m.id AND v.classification_id = c.id \
                  AND v.swllink_id = swl.id", ( filename, swl_id[0] ) )
        result = self.gdbc.fetchone()
        
        # got no result in variants then try in systems
        # (should be obsolete as all mess systems are now in mame)
        # left for devices from mess until changed
        if not result:
            self.gdbc.execute(
                "SELECT s.name, y.name, m.name \
                 FROM sets s, year y, maker m \
                 WHERE s.name = ? AND s.year_id = y.id \
                       AND s.publisher_id = m.id ", ( filename, ) )
            result = self.gdbc.fetchone()
            if result:
                name = result[0]
                info = result[1] + ', ' + result[2] + ' (' + dirname + ')' 
            else:
                name = "unknown"
                info = filename + ' - ' + dirname
        # got result, set vars
        else:
            name = result[0]
            info = result[1] + ', ' + result[2] + ' (' + result[4] + ')'
            swl = result[3]
            
            # TODO: also in gui.py, make one function
            # set snaporientation
            if result[6] in [90,270]:
                snaporientation = "vertical"
            # set aspect ratio to keep for lcd, otherwise scale
            if result[5] and result[5] == "lcd":
                snaporientation = "keep"
            if result[4] in ( "Electromechanical / Pinball", "Handheld Game" ):
                snaporientation = "keep"
            if swl in ["gameboy", "vboy", "vectrex"]: # TODO: expand
                snaporientation = "keep"

            # TODO: duplicated from gui.py, select_id
            # make util function out of it
            if swl_id[1] == 'mame':
                systempic = os.path.join(media_folder,'arcade.png')
                if result[7] == 1: # classification is not a game
                    sytempic = os.path.join(
                        progetto_path,
                        'cabinets/cabinets',
                        swl_id[1] + '.png'
                    )
                elif result[4] == 'Electromechanical / Pinball':
                    systempic = os.path.join(media_folder,"pinball.png")
                elif result[4] == 'Electromechanical / Reels':
                    systempic = os.path.join(media_folder,"reels.png")
                else:
                    # use for mame/arcade swl or classifiaction flag = 0
                    systempic = os.path.join(media_folder,"arcade.png")
            else:            
                systempic = os.path.join(
                    progetto_path,
                    'cabinets/cabinets',
                    swl_id[1] + '.png'
                )
            # mainly for result[7] == 1
            # some systems don't have a cab
            if not os.path.isfile(systempic):
                systempic = None

            # no snap when system is a clone as only parents have a shot
            if not snapshot:
                white_systempic = os.path.join(
                    progetto_path,
                    'snap',
                    dirname,
                    filename + '.png'
                )
                if os.path.isfile(white_systempic):
                    snapshot = white_systempic
        
        return name, swl, info, systempic, snapshot, snaporientation
