# -*- coding: utf-8 -*-
"""Module for umsa.info sqlite3 database

TODO
 - remove usage of detail, use tools.split_gamename
 - optimize logic for filters
 - move scanning to tools
 - get rid of xbmc dependency
"""

import os
import time
import sqlite3
from sys import version_info
import xbmc
import xbmcvfs
from tools import scan_dat

if version_info < (3, 0):
    from codecs import open as codecs_open

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
COUNTRIES = {
    '1NTSC' : ('ntsc',),
    '2PAL'  : ('pal',),
    '3US'   : ('usa', 'america', 'nintendo entertainment system /', 'world'),
    '4JP'   : ('jpn', 'japan', 'famicom'),
    '5EU'   : ('euro',),
    '6EU'   : ('euro', 'pal'),
    '7KR'   : ('kor',),
    '8BR'   : ('bra',),
    #'uk', 'ger', 'fra', 'spa', 'ita', 'ned', 'aus'],
}

class DBMod:
    """Database class for umsa.info sqlite3 database"""

    def __init__(self, db_path, filter_lists=None, pref_country='US'):

        self.pref_country = pref_country
        self.use_filter = True
        self.order = 'name'
        self.scan_perc = 0
        self.scan_what = 'nothing'
        self.join = ''
        self.where = ''

        # connect to umsa db
        self.gdb = sqlite3.connect(os.path.join(db_path, "umsa.db"))
        self.gdb.row_factory = sqlite3.Row
        self.gdb.text_factory = str # PY2
        self.gdbc = self.gdb.cursor()

        # sanity
        self.create_dat_tables(self.gdbc)
        self.create_art_tables(self.gdbc)
        self.gdb.commit()

        # connect to status db
        self.sdb = sqlite3.connect(os.path.join(db_path, "status.db"))
        self.sdb.row_factory = sqlite3.Row
        self.sdb.text_factory = str # PY2
        self.sdbc = self.sdb.cursor()

        # defines filter with self.filter_tables, self.filter_where
        if filter_lists:
            self.define_filter(filter_lists)

        # create db layout (first run)
        self.sdbc.execute(
            # last_playes = YYYY-MM-DD HH:MM
            # time_played = seconds
            """
            CREATE TABLE IF NOT EXISTS sets(
                id             INT PRIMARY KEY NOT NULL,
                last_played    DATETIME,
                time_played    BIGINT DEFAULT 0,
                play_count     INT DEFAULT 0,
                options        TEXT,
                emu_id         INT,
                marp           TEXT,
                youtube        TEXT
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
                zip       INT NOT NULL,
                mode      INT NOT NULL
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
        # update from version without
        # emu.mode
        try:
            self.sdbc.execute('SELECT EXISTS(SELECT 1 FROM emu WHERE mode="mode")')
        except sqlite3.OperationalError:
            self.sdbc.execute('ALTER TABLE emu ADD COLUMN mode INT NOT NULL DEFAULT 0')
        # sets.marp
        try:
            self.sdbc.execute('SELECT EXISTS(SELECT 1 FROM sets WHERE marp="marp")')
        except sqlite3.OperationalError:
            self.sdbc.execute('ALTER TABLE sets ADD COLUMN marp TEXT')
        # sets.youtube
        try:
            self.sdbc.execute('SELECT EXISTS(SELECT 1 FROM sets WHERE youtube="youtube")')
        except sqlite3.OperationalError:
            self.sdbc.execute('ALTER TABLE sets ADD COLUMN youtube TEXT')
        self.sdb.commit()

    def open_db(self, db_path):
        """Reopen umsa database, needed after update of umsa.db

        Reconnect and import support and artwork databases
        """

        # connect to umsa db
        self.gdb = sqlite3.connect(os.path.join(db_path, "umsa.db"))
        self.gdb.row_factory = sqlite3.Row
        self.gdb.text_factory = str # PY2
        self.gdbc = self.gdb.cursor()

        # creat additonal tables
        self.create_dat_tables(self.gdbc)
        self.create_art_tables(self.gdbc)
        self.gdb.commit()

        # copy dat, art over via attach
        self.gdbc.execute(
            "ATTACH DATABASE ? AS dat", (os.path.join(db_path, 'dat.db'),)
        )
        self.gdbc.execute(
            "ATTACH DATABASE ? AS art", (os.path.join(db_path, 'artwork.db'),)
        )
        self.gdbc.execute("INSERT INTO main.dat SELECT * FROM dat.dat")
        self.gdbc.execute("INSERT INTO main.dat_set SELECT * FROM dat.dat_set")
        self.gdbc.execute("INSERT INTO main.art_set SELECT * FROM art.art_set")
        self.gdb.commit()
        self.gdbc.execute("DETACH DATABASE 'dat'")
        self.gdbc.execute("DETACH DATABASE 'art'")

    def create_dat_tables(self, db_cursor):
        """create dat tables"""

        db_cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS dat(
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                file    VARCHAR(50),
                entry   TEXT
            )
            """
        )
        db_cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS dat_set(
                id      INTEGER,
                dat_id  INTEGER
            )
            """
        )

    def create_art_tables(self, db_cursor):
        """create art tables"""

        # id = sets.id
        # type = videosnap, cover, snap, titles, ...
        # path = 0 = progettosnaps, 1 = other
        db_cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS art_set(
                id          INTEGER,
                type        VARCHAR(20),
                extension   VARCHAR(10),
                path        BOOLEAN
            )
            """
        )

    def close_db(self):
        """close database"""
        self.gdb.close()
        #self.sdb.close()

    def scan_dats(self, datdir, db_path):
        """Read all MAME dat files from a directory

        datdir -- directory with dat files
        db_path -- directory for database files

        Todo: split file reading part to other module

        Idea:
        scan dat: first split entry and save topics (also dat file name???)
        then get ids from umsa for all sets at once
        save all pointers to dat entry
        """

        self.scan_what = 'files'
        # connect to db
        db_conn = sqlite3.connect(os.path.join(db_path, "dat.db"))
        db_conn.text_factory = str # PY2
        dbc = db_conn.cursor()

        # create tables for first run
        self.create_dat_tables(dbc)
        db_conn.commit()

        # clean table
        dbc.execute("DELETE FROM dat")
        dbc.execute("DELETE FROM dat_set")
        db_conn.commit()

        # get all sets from umsa database
        all_sets = {}
        try:
            gdb = sqlite3.connect(os.path.join(db_path, "umsa.db"))
        except sqlite3.OperationalError:
            return
        gdb.row_factory = sqlite3.Row
        gdbc = gdb.cursor()
        gdbc.execute("SELECT sets.id, sets.name, swl.name as swl \
                      FROM sets JOIN swl ON sets.swllink_id=swl.id")
        for i in gdbc.fetchall():
            all_sets["{}:{}".format(i['swl'], i['name'])] = i['id']
        gdbc.close()

        # scan dat files
        files_in_datdir = os.listdir(datdir)
        count = 1.0
        for datfile in files_in_datdir:
            if datfile[-4:] != '.dat':
                continue
            # PY2: remove codecs.open part
            if version_info < (3, 0):
                try:
                    fobj = codecs_open(os.path.join(datdir, datfile), 'r')
                except IOError:
                    fobj = False
            else:
                try:
                    fobj = open(
                        os.path.join(datdir, datfile), 'r', encoding='utf-8', errors='ignore'
                    )
                except IOError:
                    fobj = False
            if fobj:
                self.scan_what = datfile
                self.scan_perc = int(count/len(files_in_datdir)*100)

                scan_dat(fobj, all_sets, datfile, dbc)
                db_conn.commit()
                fobj.close()
            count += 1
        db_conn.close()

    def add_dat_to_db(self, db_path):
        """add dat to database"""

        gdb = sqlite3.connect(os.path.join(db_path, "umsa.db"))
        gdbc = gdb.cursor()
        # creat additonal tables
        self.create_dat_tables(gdbc)
        gdbc.execute("DELETE FROM dat")
        gdbc.execute("DELETE FROM dat_set")
        gdb.commit()
        # attach dat db and copy
        gdbc.execute("ATTACH DATABASE ? AS dat", (os.path.join(db_path, 'dat.db'),))
        gdbc.execute("INSERT INTO main.dat SELECT * FROM dat.dat")
        gdbc.execute("INSERT INTO main.dat_set SELECT * FROM dat.dat_set")
        gdb.commit()
        # detach
        gdbc.execute("DETACH DATABASE 'dat'")
        gdb.close()

    def scan_artwork(self, paths, db_path):
        """scan artwork"""

        # create list with all swls from path
        # and save types of artwork in them
        # [{swl : {cab, fly, cov, snap}},]
        # get all set names with ids from db for swl
        # listdir for all types of given swl
        # save in db

        # connect to db
        db_conn = sqlite3.connect(os.path.join(db_path, "artwork.db"))
        dbc = db_conn.cursor()
        # umsa connect for swl sets
        gdb = sqlite3.connect(os.path.join(db_path, "umsa.db"))
        gdbc = gdb.cursor()

        # create tables for first run
        self.create_art_tables(dbc)
        db_conn.commit()

        # clean table
        dbc.execute("DELETE FROM art_set")
        db_conn.commit()

        # scan art/swl from filesystem
        self.scan_what = 'dirs'
        swls = {}
        c_dirs = 0
        first_path = True # only 2 paths allowed
        for path in paths:
            for art_type in xbmcvfs.listdir(path)[0]:
                c_dirs += 1
                for swl in xbmcvfs.listdir(os.path.join(path, art_type))[0]:
                    c_dirs += 1
                    if swl == art_type:
                        if 'mame' not in swls.keys():
                            swls['mame'] = []
                        swls['mame'].append(art_type)
                    else:
                        if swl not in swls.keys():
                            swls[swl] = []
                        swls[swl].append(art_type)

            # scan sets from fs and write to db
            count = 0.0
            for swl in swls:
                # get all entries from umsa
                self.scan_what = 'db sets for {}'.format(swl)
                gdbc.execute("SELECT id FROM swl WHERE name = ?", (swl,))
                db_swl_id = gdbc.fetchone()
                if db_swl_id:
                    swl_id = db_swl_id[0]
                else:
                    xbmc.log("UMSA dbmod scan_artwork: swl {} not found... next".format(swl))
                    continue
                swl_dict = {}
                gdbc.execute(
                    "SELECT id, name FROM sets WHERE swllink_id = ?", (swl_id,)
                )
                for i in gdbc.fetchall():
                    swl_dict[i[1]] = i[0]

                # scan all art fs for swl
                count += 1
                self.scan_perc = int(count/c_dirs*100)
                for art_type in swls[swl]:
                    # no icons as Kodi can't display them
                    if art_type == 'icons':
                        continue
                    self.scan_what = "{0}/{1}".format(swl, art_type)
                    # TODO remove xbmcvfs
                    if swl == 'mame':
                        files = xbmcvfs.listdir(
                            os.path.join(path, art_type, art_type))[1]
                    else:
                        files = xbmcvfs.listdir(
                            os.path.join(path, art_type, swl))[1]
                    # TODO: commit every 1000?
                    for file_name in files:
                        try:
                            set_name, file_extension = file_name.split('.')
                        except ValueError:
                            xbmc.log(
                                "UMSA dbmod scan_artwork: unknown file = {}".format(file_name))
                            continue
                        # if set known write to db
                        if set_name in swl_dict.keys():
                            dbc.execute(
                                "INSERT INTO art_set (id, type, extension, path) VALUES (?,?,?,?)",
                                (swl_dict[set_name], art_type, file_extension, first_path)
                            )
                        else:
                            xbmc.log(
                                "UMSA dbmod scan_artwork: set {} not found in swl {}".format(
                                    set_name, swl
                                ))
                    db_conn.commit()
                    count += 1
                    self.scan_perc = int(count/c_dirs*100)
            first_path = False
            swls = {}

        db_conn.close()
        gdb.close()
        self.scan_what = "done"
        self.scan_perc = 100

    def add_art_to_db(self, db_path):
        """add artwork to database

        can be threaded
        """

        # own connect to umsa.db
        gdb = sqlite3.connect(os.path.join(db_path, "umsa.db"))
        gdbc = gdb.cursor()
        # sanity: create additonal tables
        self.create_art_tables(gdbc)
        # delete existing data
        gdbc.execute("DELETE FROM art_set")
        gdb.commit()
        # attach and copy over
        gdbc.execute(
            "ATTACH DATABASE ? AS art", (os.path.join(db_path, 'artwork.db'),)
        )
        gdbc.execute("INSERT INTO main.art_set SELECT * FROM art.art_set")
        gdb.commit()
        gdbc.execute("DETACH DATABASE 'art'")
        gdb.close()

    def get_art_types(self):
        """get all types of artwork which contain images

        except videosnaps, manuals, soundtracks and patches
        """

        art_types = []
        self.gdbc.execute("SELECT DISTINCT type FROM art_set ORDER BY type")
        for i in self.gdbc.fetchall():
            if i['type'] not in ('videosnaps', 'manuals', 'soundtrack', 'ips'):
                art_types.append(i['type'])
        return art_types

    def get_artwork_for_set(self, set_id):
        """get artwork for one set

        TODO think about if dict with key = type is better?
        """

        self.gdbc.execute("SELECT type, extension, path FROM art_set WHERE id = ?", (set_id,))
        return self.gdbc.fetchall()

    def get_artwork_for_sets(self, set_ids):
        """get artwork for a list of sets"""

        self.gdbc.execute(
            "SELECT id, type, extension, path FROM art_set WHERE id in ({})".format(
                ','.join(set_ids)
            )
        )
        art_set = {}
        for i in self.gdbc.fetchall():
            # TODO rework
            # create key if not exist
            if i['id'] not in art_set:
                art_set[i['id']] = []
            art_set[i['id']].append(
                {'type': i['type'], 'extension': i['extension'], 'path': i['path']})
        return art_set

    def get_dat_for_set(self, set_id):
        """get dat file entries for one set"""

        set_dats = {}
        self.gdbc.execute(
            "SELECT dat.file, dat.entry \
             FROM dat JOIN dat_set ON dat.id = dat_set.dat_id \
             WHERE dat_set.id = ?", (set_id,)
        )
        for i in self.gdbc.fetchall():
            set_dats[i['file']] = i['entry']
        return set_dats

    def get_dat_for_sets(self, set_ids):
        """get dat file entries for a list of sets"""

        self.gdbc.execute("SELECT dat_set.id, dat.file, dat.entry \
                           FROM dat JOIN dat_set ON dat.id = dat_set.dat_id \
                           WHERE dat_set.id in ({})".format(
                               ','.join(set_ids)))
        set_file = {}
        for i in self.gdbc.fetchall():
            if i['id'] not in set_file:
                set_file[i['id']] = {}
            set_file[i['id']][i['file']] = i['entry']
        return set_file

    def get_random_id(self):
        """get a random id"""

        where = ''
        if self.filter_join and self.filter_where:
            where = "WHERE sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
                " ".join(self.filter_join), " AND ".join(self.filter_where)
            )

        select_statement = "SELECT DISTINCT software.id \
                            FROM sets JOIN software ON software.id = sets.softwarelink_id \
                            {} ORDER BY RANDOM() LIMIT 1".format(where)
        self.gdbc.execute(select_statement)
        return self.gdbc.fetchone()[0]

    def get_random_art(self, art_types):
        """Get 1 random artwork

        Takes a list of artwork types
        Returns a dictonary with informations or None if nothing is found
        """

        rand_art = False
        end_result = {}

        # get with filter if on
        if self.use_filter:
            statement = "SELECT sets.id, art_set.extension, art_set.path, art_set.type \
                         FROM art_set JOIN sets ON sets.id = art_set.id {} \
                         WHERE type IN ({}) AND {} \
                         ORDER BY RANDOM() LIMIT 1".format(
                             " ".join(self.filter_join),
                             "'"+"','".join(art_types)+"'",
                             " AND ".join(self.filter_where))
            self.gdbc.execute(statement)
            rand_art = self.gdbc.fetchone()
        # and without filter if we haven't found anything
        if not rand_art:
            statement = "SELECT sets.id, art_set.extension, art_set.path, art_set.type \
                        FROM art_set JOIN sets ON sets.id = art_set.id \
                        WHERE type IN ({}) \
                        ORDER BY RANDOM() LIMIT 1".format("'"+"','".join(art_types)+"'")
            self.gdbc.execute(statement)
            rand_art = self.gdbc.fetchone()
            if not rand_art:
                xbmc.log("UMSA dbmod get_random art: no artwork for {}".format(art_types))
                return None
        end_result.update(rand_art)

        # get needed infos
        self.gdbc.execute(
            "SELECT sets.name, swl.name as swl, gamename, \
                    year.name as year, maker.name as maker, softwarelink_id as s_id, \
                    swl.system_id as swl_system_id, cat.name as cat \
             FROM sets, swl, year, maker, category cat \
             WHERE sets.id = ? \
             AND sets.year_id = year.id AND sets.publisher_id = maker.id \
             AND sets.swllink_id = swl.id AND sets.classification_id = cat.id",
            (rand_art['id'],)
        )
        art_info = self.gdbc.fetchone()
        end_result.update(art_info)

        # snap/title: get display
        if 'snap' in art_types or 'titles' in art_types:
            if end_result['swl'] == 'mame':
                machine = rand_art['id']
            else:
                machine = end_result['swl_system_id']
            self.gdbc.execute(
                "SELECT display_rotation, display_type \
                FROM sets WHERE id = ?", (machine,)
            )
            art_displayinfo = self.gdbc.fetchone()
            end_result.update(art_displayinfo)
        else:
            end_result.update({'display_rotation': 0, 'display_type': ''})

        return end_result

    def get_set_ids_for_software(self, software_id):
        """Return all set ids for given software id"""

        sets = []
        self.gdbc.execute(
            "SELECT id FROM sets \
             WHERE softwarelink_id = ?", (software_id,)
        )
        for i in self.gdbc.fetchall():
            sets.append(i[0])

        return sets

    def get_status_for_software(self, software_id):
        """Return play status for given software id"""

        # call umsa.db for sets
        sets = self.get_set_ids_for_software(software_id)
        # get count of play_count and time_played from status.db
        select_statement = "SELECT COUNT(play_count), COUNT(time_played) \
                            FROM sets WHERE id IN ({})".format(','.join(['?'] * len(sets)))
        self.sdbc.execute(select_statement, sets)

        status = self.sdbc.fetchone()
        xbmc.log("UMSA dbmod get_status_for_software: result = {}".format(status))
        return status

    def get_series(self, software_id):
        """Return all software from a series based on a software id

        TODO software can belong to more than one series
        """

        # check if software has a series attached
        self.gdbc.execute(
            "SELECT series_id \
             FROM series_seq WHERE software_id = ?", (software_id,)
        )
        series_ids = self.gdbc.fetchall()
        if not series_ids:
            return None

        # get all entries for the series
        all_series = []
        self.gdbc.execute(
            "SELECT software_id \
             FROM series_seq, software, year \
             WHERE series_id = ? AND software_id = software.id \
             AND software.year_id = year.id \
             ORDER BY seqno, year.name", (series_ids[0]['series_id'],) # simply use first series
        )
        for i in self.gdbc.fetchall():
            self.gdbc.execute(
                "SELECT DISTINCT s.id, s.name, y.name as year, m.name as maker \
                 FROM software s, sets v, \
                      year y, maker m \
                 WHERE s.id = v.softwarelink_id AND y.id = s.year_id \
                       AND m.id = s.developer_id AND s.id = ?", (i[0],)
            )
            all_series.append(self.gdbc.fetchone())
        return all_series

    def check_series(self, software_id):
        """Return count of series entries based on software id"""

        # first check if series exists
        self.gdbc.execute(
            "SELECT series_id \
             FROM series_seq WHERE software_id = ?", (software_id, )
        )
        series_exists = self.gdbc.fetchone()
        # now count
        if series_exists:
            self.gdbc.execute(
                "SELECT COUNT(series_id) \
                 FROM series_seq WHERE series_id = ?", (series_exists['series_id'],)
            )
            return self.gdbc.fetchone()[0]
        return None

    def check_compilation(self, software_id):
        """Return if software is connected to a compilation

        2 = Software is on a compilation
        1 = Software is a compilation
        0 = No connection found
        """

        self.gdbc.execute(
            "SELECT software.id FROM software \
                JOIN compilations ON compilations.software_id = software.id \
             WHERE software.id = ?", (software_id,))
        if self.gdbc.fetchone():
            return 1

        self.gdbc.execute(
            "SELECT software.id FROM software \
                JOIN compilations ON compilations.compilation_id = software.id \
             WHERE software.id = ?", (software_id,))
        if self.gdbc.fetchone():
            return 2

        return 0

    def make_time_nice(self, timestamp):
        """Return a nice time string from a timestamp"""

        if not timestamp:
            return ""
        minute = divmod(
            int(time.time() - time.mktime(time.strptime(timestamp, "%Y-%m-%d %H:%M"))), 60
        )[0]
        hour, minute = divmod(minute, 60)
        day, hour = divmod(hour, 24)
        if day > 0:
            last_nice = "%dd" % (day)
        elif hour == 0:
            last_nice = "%dm" % (minute,)
        else:
            last_nice = "%d:%02dh" % (hour, minute)
        return last_nice

    def get_status_for_set(self, set_id):
        """Return play status for a set id"""

        self.sdbc.execute(
            "SELECT * FROM sets WHERE ID = ?", (set_id,)
        )
        i = self.sdbc.fetchone()
        if not i:
            return None

        minute = divmod(i[2], 60)[0]
        hour, minute = divmod(minute, 60)
        time_played = "%d:%02d" % (hour, minute)

        status = {
            'last_played'   : i[1],
            'time_played'   : time_played,
            'time_played2'  : i[2],
            'play_count'    : i[3],
            'options'       : i[4],
            'last_nice'     : self.make_time_nice(i[1]),
        }
        return status

    def get_further_media(self, set_id):
        """Return MARP and Youtube entries for a set"""

        self.sdbc.execute("SELECT marp, youtube FROM sets WHERE sets.id = ?", (set_id,))
        return self.sdbc.fetchone()

    def save_further_media(self, set_id, marp=None, youtube=None):
        """Save MARP or Youtube entries for a set"""

        # check set_id
        self.sdbc.execute("SELECT sets.id FROM sets WHERE id = ?", (set_id,))
        if self.sdbc.fetchone():
            # update
            if marp:
                self.sdbc.execute("UPDATE sets SET marp = ? WHERE id = ?", (marp, set_id))
            if youtube:
                self.sdbc.execute("UPDATE sets SET youtube = ? WHERE id = ?", (youtube, set_id))
        else:
            # insert
            if marp:
                self.sdbc.execute("INSERT INTO sets (id, marp) VALUES(?,?)", (set_id, marp))
            if youtube:
                self.sdbc.execute("INSERT INTO sets (id, youtube) VALUES(?,?)", (set_id, youtube))
        self.sdb.commit()

    def get_emulators(self, source=None, swl_name=None):
        """Returns emulators based on source or swl_name"""

        if source:
            self.sdbc.execute(
                "SELECT emu.id, emu.name, emu.exe, emu.dir, emu.zip, emu.mode, \
                        emu_conn.id as emu_conn_id \
                 FROM emu JOIN emu_conn ON emu.id = emu_conn.emu_id \
                 WHERE emu_conn.source = ? ORDER BY emu.name", (source,))
        elif swl_name:
            self.sdbc.execute(
                "SELECT emu.id, emu.name, emu.exe, emu.dir, emu.zip, emu.mode, \
                        emu_conn.id as emu_conn_id \
                 FROM emu JOIN emu_conn ON emu.id = emu_conn.emu_id \
                 WHERE emu_conn.swl = ? ORDER BY emu.name", (swl_name,))
        else:
            self.sdbc.execute("SELECT id, name, exe, dir, zip, mode FROM emu ORDER BY name")
        return self.sdbc.fetchall()

    def get_emulator(self, emu_id=None, emu_conn_id=None):
        """Return information about saved emulator"""

        if emu_id:
            self.sdbc.execute(
                "SELECT id, name, exe, dir, zip, mode FROM emu WHERE id = ?", (emu_id,))
        elif emu_conn_id:
            self.sdbc.execute(
                "SELECT id, name, exe, dir, zip, mode FROM emu WHERE id = \
                 (SELECT emu_id FROM emu_conn WHERE id = ?)", (emu_conn_id,))
        return self.sdbc.fetchone()

    def save_emulator(self, emu_info, reconfigure, source=None, swl_name=None):
        """Save emulator to database and connect if needed."""

        if 'id' in emu_info:
            self.sdbc.execute(
                "UPDATE emu SET name = ?, exe = ?, dir = ?, zip = ?, mode = ? \
                    WHERE id = ?",
                (emu_info['name'], emu_info['exe'], emu_info['dir'],
                 emu_info['zip'], emu_info['mode'], emu_info['id']))
        else:
            self.sdbc.execute(
                "INSERT INTO emu (name, exe, dir, zip, mode) VALUES (?, ?, ?, ?, ?)",
                (emu_info['name'], emu_info['exe'], emu_info['dir'],
                 emu_info['zip'], emu_info['mode']))
        self.sdb.commit()
        if not reconfigure:
            emu_id = self.sdbc.lastrowid
            self.connect_emulator(emu_id, source=source, swl_name=swl_name)

    def connect_emulator(self, emu_id, source=None, swl_name=None):
        """Connect emulator to source or softwarelist"""

        if source:
            self.sdbc.execute(
                "INSERT INTO emu_conn (emu_id, source) VALUES (?, ?)", (emu_id, source)
            )
        elif swl_name:
            self.sdbc.execute(
                "INSERT INTO emu_conn (emu_id, swl) VALUES (?, ?)", (emu_id, swl_name)
            )
        else:
            xbmc.log("UMSA dbmod: connect_emulator error")
        self.sdb.commit()

    def delete_emulator_connection(self, emu_conn_id):
        """Delete emulator connection to softwarelist or source

        Return emulator id it not used anymore
        """

        # get emu.ids for emu_conn.id before deleting
        self.sdbc.execute("SELECT emu_id FROM emu_conn WHERE emu_id IN \
                           (SELECT emu_id FROM emu_conn WHERE id = ?)", (emu_conn_id,))
        connected_emus = self.sdbc.fetchall()
        # delete emu_conn.id
        self.sdbc.execute("DELETE FROM emu_conn WHERE id = ?", (emu_conn_id,))
        self.sdb.commit()
        # return it if only 1
        if len(connected_emus) == 1:
            return connected_emus[0][0]
        return None

    def delete_emulator(self, emu_id):
        """Delete emulator and all connections"""

        self.sdbc.execute("DELETE FROM emu_conn WHERE emu_id = ?", (emu_id,))
        self.sdb.commit()
        self.sdbc.execute("DELETE FROM emu WHERE id = ?", (emu_id,))
        self.sdb.commit()

    def write_options(self, set_id, options):
        """Write options"""

        self.sdbc.execute(
            "UPDATE sets SET options = ? WHERE id = ?", (set_id, options)
        )
        self.sdb.commit()

    def write_status_after_play(self, set_id, played_seconds):
        """Update play status for set id

        Writes played seconds and play count
        """

        # get time string
        date = time.strftime("%Y-%m-%d %H:%M")
        # get data
        self.sdbc.execute("SELECT time_played, play_count FROM sets WHERE id = ?", (set_id,))
        set_fetch = self.sdbc.fetchone()
        # update data
        if set_fetch:
            set_data = (date, played_seconds+set_fetch[0], set_fetch[1]+1, set_id)
            self.sdbc.execute(
                "UPDATE sets \
                 SET last_played = ?, time_played = ?, play_count = ? \
                 WHERE id = ?", (set_data))
        # new data
        else:
            set_data = (set_id, date, played_seconds, 1)
            self.sdbc.execute(
                "INSERT INTO sets (id, last_played, time_played, play_count) \
                 VALUES (?,?,?,?)", (set_data))
        self.sdb.commit()

    def get_latest_by_software(self, software_id):
        """Return id of latest played set for a software id"""

        sets = self.get_set_ids_for_software(software_id)

        select_statement = "SELECT id FROM sets WHERE id IN ({}) \
                            ORDER BY last_played DESC LIMIT 1".format(','.join(['?'] * len(sets)))
        self.sdbc.execute(select_statement, sets)
        set_id = self.sdbc.fetchone()
        if set_id:
            set_id = set_id[0]
        return set_id

    def define_filter(self, filter_lists):
        """define filter

        TODO
        - when list smaller then 50% of all do NOT IN = faster?
        - do we need a special field for all as the lists can grow with updates?
          or show new entries after update!
        - make this count always visible in filter list and keep actual, is in gui:
          simply call this more often (:
        """

        self.filter_join = []
        self.filter_where = []
        # swl
        if filter_lists['Softwarelists']:
            self.gdbc.execute("SELECT COUNT(id) FROM swl")
            swl_count = self.gdbc.fetchone()[0]
            if swl_count > len(filter_lists['Softwarelists']):
                self.filter_join.append("JOIN swl ON swl.id = sets.swllink_id")
                self.filter_where.append(
                    "swl.id IN ({})".format(','.join(filter_lists['Softwarelists'])))
            else:
                xbmc.log("UMSA dbmod define_filter: all swls, no filter used")
        # game categories, machines
        if filter_lists['Game Categories'] or filter_lists['Machine Categories']:
            self.gdbc.execute("SELECT COUNT(id) FROM category")
            cat_count = self.gdbc.fetchone()[0]
            xbmc.log("UMSA filter categories {}, {}".format(
                cat_count, len(filter_lists['Game Categories']+filter_lists['Machine Categories'])
            ))
            if cat_count > len(filter_lists['Game Categories']+filter_lists['Machine Categories']):
                self.filter_join.append("JOIN category ON category.id = sets.classification_id")
                self.filter_where.append("category.id IN ({})".format(
                    ','.join(filter_lists['Game Categories']+filter_lists['Machine Categories'])))
            else:
                xbmc.log("UMSA dbmod define_filter: all categories, no filter used")
        # players
        if filter_lists['Players']:
            self.gdbc.execute("SELECT COUNT(id) FROM nplayers")
            players_count = self.gdbc.fetchone()[0]
            xbmc.log("UMSA filter players {}, {}".format(
                players_count, len(filter_lists['Players'])
            ))
            if players_count > len(filter_lists['Players']):
                self.filter_join.append("JOIN nplayers ON nplayers.id = sets.nplayers_id")
                self.filter_where.append("nplayers.id IN ({})".format(
                    ','.join(filter_lists['Players'])))
            else:
                xbmc.log("UMSA dbmod define_filter: all players, no filter used")
        # years
        if filter_lists['Years']:
            self.gdbc.execute("SELECT COUNT(id) FROM year")
            year_count = self.gdbc.fetchone()[0]
            if year_count > len(filter_lists['Years']):
                self.filter_join.append("JOIN year ON year.id = sets.year_id")
                self.filter_where.append("year.id IN ({})".format(','.join(filter_lists['Years'])))
            else:
                xbmc.log("UMSA dbmod define_filter: all years, no filter used")
        # count
        filter_where = ''
        if self.filter_join and self.filter_where:
            filter_where = "WHERE sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
                " ".join(self.filter_join), " AND ".join(self.filter_where))
        select_statement = "SELECT COUNT (DISTINCT software.id) \
            FROM sets JOIN software ON software.id = sets.softwarelink_id {}".format(filter_where)
        self.gdbc.execute(select_statement)
        count = self.gdbc.fetchone()[0]
        self.gdbc.execute("SELECT COUNT (software.id) FROM software")
        all_count = self.gdbc.fetchone()[0]
        percent = int(round(count/float(all_count)*100))
        return "{} ({}%)".format(count, percent)

    def execute_statement(self, set_id=None, software_id=None, prevnext=None):
        """Execute prepared statement with filter settings

        TODO
        - rework var names
        - keep inital count when used with set_id in gui
          so no overwrite with prevnext
        - make number of listmenu entries settings.xml
        - more logic: when swl.name = "gameboy" then no need for swl filter! = faster
        """

        time_start = time.time()
        result_count = 0
        where = ""
        filter_join = ""
        filter_where = ""
        if self.filter_join and self.filter_where:
            filter_join = " ".join(self.filter_join)
            filter_where = " AND ".join(self.filter_where)
        # prepare joins and wheres from filters
        s_join, s_where = '', ''
        if self.use_filter and self.where:
            if self.join and self.join not in self.filter_join:
                s_join = "{} {}".format(self.join, filter_join)
            elif filter_join:
                s_join = filter_join
            if self.where and filter_where:
                s_where = "{} AND {}".format(self.where, filter_where)
            elif self.where:
                s_where = self.where
            elif filter_where:
                s_where = filter_where
            if s_join and s_where:
                where = "sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
                    s_join, s_where)
            # only for source
            elif self.where:
                where = self.where
        elif self.use_filter:
            if filter_join and filter_where:
                where = "sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
                    filter_join, filter_where)
        elif self.join and self.where:
            where = "sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
                self.join, self.where)
        else:
            xbmc.log("UMSA execute_statement: no join and where clause")
        # get software name
        if set_id:
            name_statement = "SELECT software.name FROM software \
                    JOIN sets ON software.id = sets.softwarelink_id \
                    WHERE sets.id = ?"
            self.gdbc.execute(name_statement, (set_id,))
            sname = self.gdbc.fetchone()[0]
        elif software_id:
            self.gdbc.execute(
                "SELECT software.name FROM software WHERE software.id = ?", (software_id,)
            )
            sname = self.gdbc.fetchone()[0]
        else:
            xbmc.log("UMSA dbmod execute_statement: no set or software id error")
        # add ordering
        if self.order == 'name':
            order = 'software.name'
        elif self.order == 'year':
            order = 'year.name, software.name'
        elif self.order == 'publisher':
            order = 'maker.name, software.name'
        else:
            self.order = 'software.name'
        time_rampup = time.time()

        # fetch
        slist = []
        while not slist:
            # normal, previous or next
            if not prevnext:
                if where:
                    i_where = "WHERE "+where
                else:
                    i_where = ""
                limit = ""
            elif prevnext == 'prev':
                if where:
                    i_where = 'WHERE software.name <= "{}" AND {}'.format(sname, where)
                else:
                    i_where = 'WHERE software.name <= "{}"'.format(sname)
                limit = "DESC LIMIT 100"
            elif prevnext == 'next':
                if where:
                    i_where = 'WHERE software.name >= "{}" AND {}'.format(sname, where)
                else:
                    i_where = 'WHERE software.name >= "{}"'.format(sname)
                limit = "ASC LIMIT 100"
            else:
                xbmc.log("UMSA execute_statement: prevnext error {}".format(prevnext))
            # fetch software list
            select_statement = "SELECT DISTINCT \
                    software.id, software.name, year.name as year, maker.name as maker \
                FROM sets \
                    JOIN software ON software.id = sets.softwarelink_id \
                    JOIN year ON year.id = software.year_id \
                    JOIN maker ON maker.id = software.developer_id \
                {} ORDER BY {} {}".format(i_where, order, limit)
            #xbmc.log("UMSA dbmod execute statement: {}".format(select_statement))
            self.gdbc.execute(select_statement)
            slist = self.gdbc.fetchall()
            # no results: try without filter
            if len(slist) == 0:
                xbmc.log("UMSA db fetch list: no result, retry without filters")
                if self.where:
                    where = "sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
                        self.join, self.where)
                else:
                    where = ""
        time_fetch = time.time()

        # get position and set prevnext
        if not prevnext:
            result_count = len(slist)
            # search for name
            # TODO rework
            count, pos = 0, 0
            for i in slist:
                count += 1
                if sname == i['name']:
                    pos = count
                    break
            # TODO do we need new_slist?
            if count < 50: # begin of list
                pos -= 1
                # TODO get rid of flag, try without new_slist
                flag = None
                if len(slist) > 100:
                    flag = True
                new_slist = slist[:count+50+(50-count)]
                if flag:
                    new_slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
            elif count > len(slist)-100: # end of list
                pos = pos-(len(slist)-100)
                new_slist = slist[count-(count-(len(slist)-100)):]
                new_slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
            else: # middle of list
                pos = 50
                new_slist = slist[count-50:count+50]
                new_slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
                new_slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
            slist = new_slist
        elif prevnext == 'next':
            pos = 1
            slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
            if len(slist) == 100:
                slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
        else: # prev
            pos = len(slist)
            slist.reverse()
            slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
            if len(slist) == 100:
                slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
        time_rest = time.time()
        xbmc.log('UMSA dbmod execute_statement: begin {:.0f}ms'.format(
            (time_rampup - time_start) * 1000))
        xbmc.log('UMSA dbmod:                   fetch {:.0f}ms'.format(
            (time_fetch - time_rampup) * 1000))
        xbmc.log('UMSA dbmod:                   pos   {:.0f}ms'.format(
            (time_rest - time_fetch) * 1000))
        xbmc.log('UMSA dbmod:                   all   {:.0f}ms'.format(
            (time_rest - time_start) * 1000))
        return slist, pos, result_count

    def get_by_software(self, set_id):
        """Return list of software"""

        self.join = ''
        self.where = ''
        return self.execute_statement(set_id)

    def get_software_for_source(self, set_id, source):
        """Return list of software based on MAME source file"""

        self.join = ''
        self.where = 'sets.source = "{}"'.format(source)
        return self.execute_statement(set_id)

    def get_by_cat(self, cat, set_id):
        """Return list of software based on category"""

        self.join = "JOIN category ON category.id = sets.classification_id"
        self.where = 'category.name = "{}"'.format(cat)
        return self.execute_statement(set_id)

    def get_by_year(self, year, set_id):
        """Return list of software based on year"""

        self.join = 'JOIN year ON year.id = sets.year_id'
        self.where = 'year.name = "{}"'.format(year)
        return self.execute_statement(set_id)

    def get_by_players(self, players, set_id):
        """Return list of software based on number of players"""

        self.join = 'JOIN nplayers ON nplayers.id = sets.nplayers_id'
        self.where = 'nplayers.name = "{}"'.format(players)
        return self.execute_statement(set_id)

    def get_by_maker(self, maker, set_id):
        """Return list of software based on maker"""

        self.join = 'JOIN maker ON maker.id = sets.publisher_id'
        self.where = 'maker.name = "{}"'.format(maker)
        return self.execute_statement(set_id)

    def get_by_swl(self, swl_name, set_id):
        """Return list of software based on softwarelist"""

        self.join = 'JOIN swl ON swl.id = sets.swllink_id'
        self.where = 'swl.name = "{}"'.format(swl_name)
        return self.execute_statement(set_id)

    def get_maker(self):
        """Return list of makers"""

        self.gdbc.execute("SELECT name as id, name FROM maker ORDER BY name")
        return self.gdbc.fetchall()

    def get_swl(self):
        """Return list of softwarelists"""

        self.gdbc.execute("SELECT name as id, description as name FROM swl ORDER BY name")
        return self.gdbc.fetchall()

    def get_source(self):
        """Return list of softwarelists"""

        self.gdbc.execute("SELECT DISTINCT source FROM sets ORDER BY source")
        return self.gdbc.fetchall()

    def get_year(self):
        """Return list of years"""

        self.gdbc.execute("SELECT name as id, name FROM year ORDER BY name")
        return self.gdbc.fetchall()

    def get_players(self):
        """Return list of players"""

        self.gdbc.execute("SELECT name as id, name FROM nplayers ORDER BY name")
        return self.gdbc.fetchall()

    def get_categories(self):
        """Return list of categories"""

        self.gdbc.execute("SELECT name as id, name FROM category ORDER BY name")
        return self.gdbc.fetchall()

    def get_last_played(self, order):
        """get_last_played"""

        results = []
        software_dict = {}

        # get status for sets
        self.sdbc.execute(
            "SELECT id, last_played, play_count, time_played FROM sets \
             ORDER BY {} DESC LIMIT 100".format(order))
        # get software info for sets from status.db
        for i in self.sdbc.fetchall():
            self.gdbc.execute(
                "SELECT software.id, software.name, year.name as year, maker.name as maker \
                 FROM software \
                    JOIN year ON software.year_id = year.id \
                    JOIN maker ON software.developer_id = maker.id \
                    JOIN sets ON software.id = sets.softwarelink_id \
                 WHERE sets.id = ?", (i['id'],))
            software = self.gdbc.fetchone()
            # put in dict to summarize sets
            if software['id'] in software_dict.keys():
                software_dict[software['id']]["play_count"] += i['play_count']
                software_dict[software['id']]["time_played"] += i['time_played']
                if software_dict[software['id']]["last_played"] < i['last_played']:
                    software_dict[software['id']]["last_played"] = i['last_played']
            else:
                software_dict[software['id']] = {
                    "time_played": i['time_played'],
                    "last_played": i['last_played'],
                    "play_count": i['play_count'],
                    "name": software['name'],
                    "year": software['year'],
                    "maker": software['maker'],
                }
        # sort dict after value in var order and create list for return
        for software_id, status in reversed(
                sorted(software_dict.items(), key=lambda t: t[1][order])):

            minute = divmod(status["time_played"], 60)[0]
            hour, minute = divmod(minute, 60)
            time_played = "%d:%02d" % (hour, minute)

            last_nice = self.make_time_nice(status['last_played'])

            if order == "time_played":
                last = '{}x, {}'.format(
                    status["play_count"],
                    last_nice,
                )
                first = time_played
            elif order == "play_count":
                last = '{}, {}'.format(
                    time_played,
                    last_nice,
                )
                first = '{}x'.format(status['play_count'])
            else:
                last = '{}, {}x'.format(
                    time_played,
                    status["play_count"],
                )
                first = last_nice

            name = "{} ({}, {})".format(status['name'], status['year'], status['maker'],)
            results.append({'id': software_id, 'name': name, 'year': first, 'maker': last,})

        return results, 0

    def get_parts_for_set_id(self, set_id):
        """Get parts for a set id

        sets can have more than one media
        like 2 floppies or 1 floppy and 1 hdd or cd-rom
        """

        self.gdbc.execute(
            "SELECT   p.name, pv.name, pv.disk \
             FROM     part_set pv, part p \
             WHERE    p.id = pv.part_id AND pv.variant_id = ? \
             ORDER BY p.name", (set_id,))
        return self.gdbc.fetchall()

    def get_disks(self, swl_name, set_name):
        """Return first disk from a given set and softwarelist"""

        self.gdbc.execute(
            "SELECT sets.id FROM sets \
                JOIN swl ON swl.id = sets.swllink_id \
             WHERE sets.name = ? AND swl.name = ?",
            (set_name, swl_name))
        set_id = self.gdbc.fetchone()
        if set_id:
            self.gdbc.execute("SELECT disk FROM part_set WHERE variant_id = ?", (set_id[0],))
            disks = self.gdbc.fetchall()
            if disks:
                return disks
        return None

    def create_cmdline(self, parts, devices, setname):
        """create command line to start a software list item in mame"""

        cmd_options = []
        first_device = None

        hit = False
        for device in devices:
            # split the interface
            # because interface="c64_cart,vic10_cart" for c128_cart and c64_cart
            for interface in device[1].split(','):
                for part in parts:
                    if interface == part[1]:
                        hit = True
                        cmd_options.extend(
                            [
                                '-{0}'.format(device[0]),
                                '{0}:{1}'.format(setname, part[0])
                            ]
                        )
                        # use device from first hit for snaps and states
                        if not first_device:
                            first_device = device[0]
                        parts.remove(part)
                        break
            # only pack one part into a device
            # TODO: make exception for x68000: -flop1 x -flop2 y
            if hit:
                break

        return cmd_options, first_device

    # create commandline options for mame
    def get_cmd_line_options(self, set_id, set_name, machine_name, swl_name):
        """Create command line options for MAME emulator run

        Based on id, name of set, and the names of machine and swl.
        """

        # get options for softwarelist
        ## this is manually set coz some swls need special options
        ## like a device in a slot so the machine supports hdds
        self.gdbc.execute(
            "SELECT options FROM swl WHERE name = ?", (swl_name,)
        )
        swlopt = self.gdbc.fetchone()
        # make swl_options a list
        if swlopt[0]:
            swl_options = swlopt[0].strip().split(' ')
        else:
            swl_options = None

        # get id for machine
        self.gdbc.execute(
            "SELECT v.id \
             FROM sets v, swl \
             WHERE v.swllink_id = swl.id AND swl.name = ? AND v.name = ?",
            ('mame', machine_name)
        )
        machine_id = self.gdbc.fetchone()

        # get devices supported by the machine
        self.gdbc.execute(
            "SELECT d.name, dv.name \
             FROM device_set dv, device d \
             WHERE d.id = dv.device_id AND dv.variant_id = ? \
             ORDER BY d.name", (machine_id[0],))
        _devices = self.gdbc.fetchall()

        # get all parts for the choosen set
        _part = self.get_parts_for_set_id(set_id)
        #xbmc.log("origsetid",set_id)
        #xbmc.log("origparts",_part)

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

        more_options = []
        if _cmd_options:
            # add additional manual swl options
            if swl_options:
                more_options += swl_options

            # add sharedfeat
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
                    xbmc.log("UMSA dbmod: get_cmd_line_options: set {}, swl {}".format(_set, _swl))
                    _setinfo = self.get_info_by_set_and_swl(_set, _swl)
                    xbmc.log("UMSA dbmod: get_cmd_line_options: setid {}".format(_setinfo))
                    _parts2 = self.get_parts_for_set_id(_setinfo['set_id'])
                    xbmc.log("UMSA dbmod: get_cmd_line_options: parts {}".format(_parts2))
                    _cmdopt = self.create_cmdline(list(_parts2), _devices, _set)[0]
                    more_options += _cmdopt
                # else add the requirement set as option
                # directly after machine name
                # hopefully most of the time mame will then
                # find the correct swl entry
                else:
                    more_options += [_set]

            # when we know the devices also set -statename
            cmd_options = [machine_name]+more_options+_cmd_options+[
                '-statename', '%g/%d_{0}'.format(first_device), ]

        # when we have no cmd_options then the machine needs a device
        # in a slot so it can support the media, thus we have no hit within
        # the devices and parts and therefore no cmd_options
        # little hack: normally we would need to get devices from mame
        # with the correct device in a slot: mame -slot xyz -lm
        elif swl_options:
            cmd_options = [machine_name] + swl_options + [set_name]
        # last exit is to just start mame with the machine and set as options
        else:
            cmd_options = [machine_name, set_name]
        # set snap dir to swl name
        cmd_options.extend(['-snapname', '{}/{}/%i'.format(swl_name, set_name)])

        return cmd_options

    def get_all_dbentries(self, cat):
        """Return select parameters based on filter categories.

        Gets a filter category.
        Returns a list of database tables and rows.
        """

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
            return None

        select_statement = "SELECT t.id, t.%s, count(distinct s.id) \
                            FROM %s t, software s, sets v \
                            WHERE t.id = v.%s_id and s.id = v.softwarelink_id %s \
                            GROUP BY t.id ORDER BY t.%s" % select_placeholders
        self.gdbc.execute(select_statement)

        # TODO: why does this not work
        # IndexError: tuple index out of range
        #self.gdbc.execute(
        #    "SELECT t.id, t.{}, count(distinct s.id) \
        #     FROM {} t, software s, sets v \
        #     WHERE t.id = v.{}_id and s.id = v.softwarelink_id {} \
        #     GROUP BY t.id ORDER BY t.{}".format(select_placeholders)
        #)

        return self.gdbc.fetchall()

    def search_single(self, search):
        """search single"""

        self.gdbc.execute(
            "SELECT DISTINCT software.id, software.name, year.name as year, maker.name as maker \
             FROM software \
                JOIN year ON software.year_id = year.id \
                JOIN maker ON software.developer_id = maker.id \
                JOIN sets ON software.id = sets.softwarelink_id \
             WHERE sets.gamename LIKE ? \
             ORDER BY software.name LIMIT 1", (search+'%',))
        return self.gdbc.fetchone()

    def get_artwork_by_software_id(self, software_id, artwork):
        """get artwork by software id

        fetch given artwork type and all machines for a software id

        TODO
        - an abbreviation for machine name would make text shorter
        - should check first for a snap of machine in software
        - first needs export of machine in software from umsa
        """

        # get all machines
        all_machines = []
        self.gdbc.execute(
            "SELECT gamename FROM sets WHERE sets.id IN \
             ( SELECT DISTINCT system_id FROM swl, sets \
               WHERE sets.softwarelink_id = ? AND sets.swllink_id = swl.id )",
            (software_id,)
        )
        for j in self.gdbc.fetchall():
            all_machines.append(j[0])

        # get set ids with artwork
        self.gdbc.execute(
            "SELECT sets.name as set_name, swl.name as swl_name, \
                   art_set.extension, art_set.path \
             FROM sets, swl, art_set \
             WHERE sets.softwarelink_id = ? \
             AND swl.id = sets.swllink_id \
             AND art_set.id = sets.id \
             AND art_set.type = ? \
             ORDER BY RANDOM() LIMIT 1",
            (software_id, artwork)
        )
        # TODO ^ check machine from software table first
        # TODO ^ get all and random one artwork?
        snap_info = self.gdbc.fetchone()

        result = None
        if not snap_info:
            result = ['', 1]
        else:
            result = ['{}/{}.{}'.format(
                snap_info['swl_name'], snap_info['set_name'],
                snap_info['extension']), snap_info['path']]
        result.append(', '.join(all_machines))

        return result

    def get_searchresults(self, search):
        """get search results

        TODO:
        - single word search: split by " ": v.gamename IN ('test', 'wrum')

             - remove s.name, problem with showing gamename when s.name is selected
             - use filters or present option to use filters

        LATER - show button for next/prev page
              - save last 10 search terms and make as a popup for search button incl new search
        """

        # count
        self.gdbc.execute(
            "SELECT COUNT(DISTINCT software.id) \
                FROM sets \
                    JOIN software ON software.id = sets.softwarelink_id \
             WHERE sets.gamename LIKE ?", ("%"+search+"%",))
        results_count = self.gdbc.fetchone()[0]
        # fetch
        self.gdbc.execute(
            "SELECT DISTINCT software.id, software.name, year.name as year, maker.name as maker \
                FROM software \
                    JOIN year ON year.id = software.year_id \
                    JOIN maker ON maker.id = software.developer_id \
                    JOIN sets ON sets.softwarelink_id = software.id \
                WHERE sets.gamename LIKE ? \
             ORDER BY software.name LIMIT 100", ("%"+search+"%",))
        results = self.gdbc.fetchall()
        count, pos = 0, 0
        for i in results:
            # check if search is in beginning of s.name and set pos
            if search.lower() == i[1][:len(search)].lower():
                pos = count
                break
            count += 1

        return results, pos, results_count

    def get_machine_name(self, machine_id):
        """Get name of machine from id"""

        self.gdbc.execute("SELECT name, gamename FROM sets WHERE id = ?", (machine_id,))
        machine = self.gdbc.fetchone()
        return machine[0], machine[1]

    def count_source(self, source):
        """Count all source files in MAME"""

        self.gdbc.execute("SELECT COUNT(DISTINCT software.id) FROM sets \
            JOIN software ON software.id = sets.softwarelink_id WHERE sets.source = ?", (source,))
        return self.gdbc.fetchone()[0]

    def count_machines_for_swl(self, swl_name):
        """Count all machines for 1 software list"""

        # TODO test and delete
        self.gdbc.execute(
            #"SELECT COUNT(DISTINCT sets.id) \
            #FROM sets, swl, swl_status ss \
            #WHERE swl.name = ? \
            #    AND swl.id = ss.swl_id \
            #    AND sets.id = ss.system_id",
            "SELECT COUNT(DISTINCT sets.id) FROM swl_status \
                JOIN sets ON sets.id = swl_status.system_id \
                JOIN swl ON swl.id = swl_status.swl_id \
             WHERE swl.name = ?", (swl_name,))
        return self.gdbc.fetchone()[0]

    def get_machines(self, swl_name, machine=None):
        "Get original and compatible machines for 1 software list"

        # TODO join
        self.gdbc.execute(
            "SELECT DISTINCT \
                s.id, s.name, s.gamename, s.detail, \
                y.name as year, m.name as maker, ss.status, ss.filtr \
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
        pos, count = 0, 0
        for db_result in self.gdbc.fetchall():
            machines.append(
                {
                    'id'       : db_result['id'],
                    'name'     : "{}, {}".format(db_result['gamename'], db_result['maker']),
                    'label2'   : db_result['gamename'],
                    'setname'  : db_result['name'],
                    'detail'   : db_result['detail'],
                    'fullname' : db_result['gamename'],
                    'status'   : db_result['status'],
                    'filter'   : db_result['filtr'],
                    'year'     : db_result['year'],
                    'maker'    : "{},{}".format(db_result['status'], db_result['filtr'])
                }
            )
            if machine == db_result['name']:
                pos = count
            count += 1

        return machines, pos

    def get_swl_id(self, swl_name):
        """get swl id

        TODO: unused
        """

        self.gdbc.execute(
            "SELECT id FROM swl WHERE name = ?", (swl_name,)
        )
        return self.gdbc.fetchone()[0]

    def get_set_name(self, set_id):
        """Returns set name from set id

        TODO: Only used by run_emulator, diff_emu: search for rom file in filesystem
        """

        if set_id:
            self.gdbc.execute("SELECT name FROM sets WHERE id = ?", (set_id,))
            return self.gdbc.fetchone()[0]
        return None

    def get_info_for_id(self, _id):
        """get info for id

        TODO: unused
        """

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
             ORDER BY y.name DESC", (_id,)
        )
        machines = self.gdbc.fetchall()
        return machines

    def get_sets_for_machine(self, software_id, machine_id):
        """Get sets for a machine

        TODO: unused

        Gets software and machine id
        Returns list of all sets and set is saved in database dictonary
        """

        # get_sets: get all sets for s.id and machine (can mean more than 1 swl)
        self.gdbc.execute(
            "SELECT \
                v.id, v.name, v.gamename, v.detail, v.source, \
                y.name as year, m.name as publisher, swl.name as swl_name, \
                v.display_type , v.display_rotation, c.name as category, \
                c.flag as category_is_machine \
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
            (software_id, machine_id)
        )

        return self.gdbc.fetchall()

    def get_best_machine_for_set(self, swl_name, detail, swl_machine_id):
        """Determine which machine to take for MAME emulation

        TODO
        - rework: no more list, use dict from get_machines !!!
        - but machine_id into return
        """

        # get originals, compatible machines
        machines = self.get_machines(swl_name)[0]

        # no machine found
        if len(machines) == 0:
            return None
        # only 1 machine
        if len(machines) == 1:
            return machines[0]
        # only 1 original
        if (machines[0]['status'] == "original" and
                machines[1]['status'] == "compatible"
           ):
            return machines[0]

        best_machine = None
        # check if swl_machine is in machines
        for machine in machines:
            if machine['id'] == swl_machine_id:
                best_machine = machine

        # no hit until now, set first machine
        if not best_machine:
            best_machine = machines[0]
        # exception for famicom_flop
        # TODO famicom should be disconnected in mame source
        if swl_name == "famicom_flop":
            best_machine = machines[1]

        # get country from detail
        #for c in reversed(sorted(COUNTRIES.keys())):
        for country_sorted in sorted(COUNTRIES.keys()):
            for country in COUNTRIES[country_sorted]:
                if country in detail.lower():
                    # check gamename of machines for country from detail
                    #xbmc.log("-- check machines for country %s" % (country,))
                    # first try actual best
                    for country2 in COUNTRIES[country_sorted]:
                        if country2 in best_machine['fullname'].lower():
                            #xbmc.log("-- use best machine")
                            return best_machine
                    # now check all machines
                    for machine in machines:
                        for country2 in COUNTRIES[country_sorted]:
                            if country2 in machine['fullname'].lower():
                                best_machine = machine
                                #xbmc.log("-- got machine %s over country" % (best_machine))
                                return best_machine
        return best_machine

    def get_all_for_software(self, software_id):
        """get all infos for software

        get all sets nicely sorted (last played, prefered history, year)
        includes a best machine to use for swl set

        TODO:
        - better document this function
        - have lists for each software with same name order by year
          connect at the end and add flag so gui can mark the other software with the same name
          also make search for software with same name a setting
        - include preferred country (select it or make it first in list?)
        - maybe dont order select by year, done later,
          order by name so usa, jap... are sorted correct

        all_sets.append is used instead of .extend
        so we have all_sets[software_with_same_name][sets] = {infos}
        and not all_sets[[software1],[software2]]
        """

        time1 = time.time()

        pos_machine = 0
        pos_set = 0
        all_sets = []

        # get all sets for software id
        self.gdbc.execute(
            "SELECT \
                sets.id, sets.name, sets.gamename, sets.detail, sets.source, \
                year.name as year, maker.name as maker, swl.name as swl, swl.system_id, \
                sets.display_type, sets.display_rotation, \
                category.name as category, category.flag as category_flag, \
                nplayers.name as nplayers, sets.cloneof_id \
             FROM sets \
             JOIN year ON sets.year_id = year.id \
             JOIN maker ON sets.publisher_id = maker.id \
             JOIN swl ON sets.swllink_id = swl.id \
             JOIN category ON sets.classification_id = category.id \
             JOIN nplayers ON sets.nplayers_id = nplayers.id \
             WHERE \
                sets.softwarelink_id = ? \
             ORDER BY \
                year.name, sets.cloneof_id, sets.gamename",
            (software_id,)
        )
        all_sets.append(self.gdbc.fetchall())

        # check if we have other software by this name
        # get software name
        self.gdbc.execute(
            "SELECT name FROM software WHERE id = ?", (software_id,)
        )
        software_name = self.gdbc.fetchone()[0]
        # get all software ids for software name
        self.gdbc.execute(
            "SELECT id FROM software WHERE name = ?", (software_name,)
        )
        for i in self.gdbc.fetchall():
            if software_id == i['id']: # is the original
                continue
            self.gdbc.execute(
                "SELECT \
                    sets.id, sets.name, sets.gamename, sets.detail, sets.source, \
                    year.name as year, maker.name as maker, swl.name as swl, swl.system_id, \
                    sets.display_type, sets.display_rotation, \
                    category.name as category, category.flag as category_flag, \
                    nplayers.name as nplayers, sets.cloneof_id \
                FROM sets \
                JOIN year ON sets.year_id = year.id \
                JOIN maker ON sets.publisher_id = maker.id \
                JOIN swl ON sets.swllink_id = swl.id \
                JOIN category ON sets.classification_id = category.id \
                JOIN nplayers ON sets.nplayers_id = nplayers.id \
                WHERE \
                    sets.softwarelink_id = ? \
                ORDER BY \
                    year.name, sets.cloneof_id, sets.gamename",
                (i['id'],)
            )
            all_sets.append(self.gdbc.fetchall())

        diff_machines = {}
        set_ids = []
        count = 1
        for diff_software in all_sets:
            for machine in diff_software:

                set_ids.append(str(machine['id']))
                resulting_machine = ''
                # TODO get status in one select like art and dat
                # get last_played
                last_played = self.get_status_for_set(machine['id'])

                if machine['system_id'] == 270257: # mame
                    # resulting_machine is the parent
                    if machine['cloneof_id']:
                        resulting_machine = machine['cloneof_id']
                    else:
                        resulting_machine = machine['id']
                    # resulting_machine = machine['category'] use category
                    best_machine = None
                    machine_name = 'mame'
                    if machine['category_flag']: # ismachine
                        machine_label = machine['category']
                    else:
                        # TODO handhelds are not arcade, but a game not a machine
                        machine_label = 'Arcade'
                else: # swl
                    # diff machine is swl machine
                    # TODO: to test used machine name from swl
                    resulting_machine = str(machine['system_id'])
                    # get best machine
                    best_machine = self.get_best_machine_for_set(
                        machine['swl'], machine['detail'], machine['system_id'])
                    if best_machine:
                        machine_name = best_machine['setname']
                        machine_label = best_machine['label2']
                    else:
                        self.gdbc.execute(
                            "SELECT name, gamename FROM sets WHERE id = ?",
                            (machine['system_id'],))
                        machine_name, machine_label = self.gdbc.fetchone()

                # create key in diff_machines
                if resulting_machine not in diff_machines:
                    diff_machines[resulting_machine] = {
                        'id'      : count,
                        'year'    : machine['year'],
                        'setlist' : []
                    }
                    count += 1
                # remember earliest year for later sort
                else:
                    if diff_machines[resulting_machine]['year'] > machine['year']:
                        diff_machines[resulting_machine]['year'] = machine['year']

                # TODO: what is really needed?
                #  swl machine is not needed?
                #  make last_played 3 entries here?
                diff_machines[resulting_machine]['setlist'].append({
                    'id': machine['id'],
                    'name': machine['name'],
                    'gamename': machine['gamename'],
                    'detail': machine['detail'],
                    'source': machine['source'],
                    'year': machine['year'],
                    'publisher': machine['maker'],
                    'swl_name': machine['swl'],
                    'swl_machine_id': machine['system_id'],
                    'machine_name': machine_name,
                    'machine_label': machine_label,
                    'display_type': machine['display_type'],
                    'display_rotation': machine['display_rotation'],
                    'category': machine['category'],
                    'nplayers': machine['nplayers'],
                    'clone': machine['cloneof_id'],
                    'is_machine': machine['category_flag'],
                    'last_played': last_played,
                })

        # create list to return
        return_list = []
        # sort by year
        for i in sorted(diff_machines.items(), key=lambda t: t[1]['year']):
            return_list.append(i[1]['setlist'])
        # get absolut latest played
        # TODO search for pref. country when not last played
        latest_set_id = self.get_latest_by_software(software_id)
        # find latest in return_list
        if latest_set_id:
            count1 = 0
            for i in return_list:
                count2 = 0
                for j in i:
                    if j['id'] == latest_set_id:
                        pos_machine = count1
                        pos_set = count2
                        break
                    count2 += 1
                count1 += 1
        all_dat = self.get_dat_for_sets(set_ids)
        all_art = self.get_artwork_for_sets(set_ids)
        time2 = time.time()
        xbmc.log("UMSA dbmod: get_all_for_software: time = {:.0f}ms".format((time2-time1)*1000.0))

        return return_list, pos_machine, pos_set, all_dat, all_art

    def get_info_by_set_and_swl(self, setname, swlname):
        """get info by set and swl"""

        self.gdbc.execute(
            "SELECT v.id, v.gamename, y.name, m.name, s.id \
             FROM software s, sets v, \
                  swl, year y, maker m \
             WHERE s.id = v.softwarelink_id AND v.swllink_id = swl.id \
                   AND y.id = v.year_id AND m.id = v.publisher_id \
                   AND v.name = ? AND swl.name = ?",
            (setname, swlname)
        )
        db_fetch = self.gdbc.fetchone()

        result = {
            'software_id'   : db_fetch[4],
            'set_id'        : db_fetch[0],
            'name'          : db_fetch[1],
            'year'          : db_fetch[2],
            'maker'         : db_fetch[3],
            'label'         : "{} - {}, {}".format(db_fetch[2], db_fetch[1], db_fetch[3]),
        }
        return result

    def get_info_by_filename(self, filename, dirname, progetto_path, media_folder):
        """get info by filename

        used by picture screensaver

        TODO: remove when screensaver module is finished
        """

        name = ''
        swl = None
        info = ''
        machinepic = None
        snapshot = None
        snaporientation = 'horizontal'

        #check if directory is softwarelist based
        self.gdbc.execute(
            "SELECT swl.id, v.name \
             FROM swl, sets v \
             WHERE swl.name = ? AND swl.system_id = v.id", (dirname,))
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
            snapshot = os.path.join(progetto_path, 'snap/snap', filename+'.png')
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
                  AND v.swllink_id = swl.id", (filename, swl_id[0])
        )
        result = self.gdbc.fetchone()

        # got no result in variants then try in machines
        # (should be obsolete as all mess machines are now in mame)
        # left for devices from mess until changed
        if not result:
            self.gdbc.execute(
                "SELECT s.name, y.name, m.name \
                 FROM sets s, year y, maker m \
                 WHERE s.name = ? AND s.year_id = y.id \
                       AND s.publisher_id = m.id ", (filename,))
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
            if result[6] in [90, 270]:
                snaporientation = "vertical"
            # set aspect ratio to keep for lcd, otherwise scale
            if result[5] and result[5] == "lcd":
                snaporientation = "keep"
            if result[4] in ("Electromechanical / Pinball", "Handheld Game"):
                snaporientation = "keep"
            if swl in ["gameboy", "vboy", "vectrex"]: # TODO: expand
                snaporientation = "keep"

            # TODO: duplicated from gui.py, select_id
            # make util function out of it
            if swl_id[1] == 'mame':
                machinepic = os.path.join(media_folder, 'arcade.png')
                if result[7] == 1: # classification is not a game
                    machinepic = os.path.join(
                        progetto_path,
                        'cabinets/cabinets',
                        swl_id[1]+'.png'
                    )
                elif result[4] == 'Electromechanical / Pinball':
                    machinepic = os.path.join(media_folder, "pinball.png")
                elif result[4] == 'Electromechanical / Reels':
                    machinepic = os.path.join(media_folder, "reels.png")
                else:
                    # use for mame/arcade swl or classifiaction flag = 0
                    machinepic = os.path.join(media_folder, "arcade.png")
            else:
                machinepic = os.path.join(
                    progetto_path,
                    'cabinets/cabinets',
                    swl_id[1] + '.png'
                )
            # mainly for result[7] == 1
            # some machines don't have a cab
            if not os.path.isfile(machinepic):
                machinepic = None

            # no snap when machine is a clone as only parents have a shot
            if not snapshot:
                white_machinepic = os.path.join(
                    progetto_path,
                    'snap',
                    dirname,
                    filename + '.png'
                )
                if os.path.isfile(white_machinepic):
                    snapshot = white_machinepic

        return name, swl, info, machinepic, snapshot, snaporientation
