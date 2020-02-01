# -*- coding: utf-8 -*-
"""Module for umsa.info sqlite3 database

TODO:
 - rework execute_statement
 - optimize logic for filters
"""

import os
from sys import version_info
import time
import sqlite3
# TODO: get rid of xbmc dependency
import xbmc # for logging
import xbmcvfs # TODO
#import operator # only for sorting by values of a dict instead keys # not working in py3

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
        self.table = ''
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
        self.gdb.row_factory = sqlite3.Row
        self.gdb.text_factory = str # PY2
        self.sdbc = self.sdb.cursor()

        # defines filter with self.filter_tables, self.filter_where
        if filter_lists:
            self.define_filter(filter_lists)

        # - db layout:
        #
        #    #table software: id, last played set id (or name,swl), < maybe not needed, see below
        #    table variant: id, last played timestamp, time played, play count, options
        #     - makes it difficult to gather info for software:
        #       get info for all sets
        #       but set with lastest played timestamp = set to choose = no need for software table
        #
        #    table favorites: id, set id, fav_id
        #    table fav_lists: id, name
        #
        #    table emus: id, name, exe, working dir, extract zip/7z/chd
        #      (means build rom from xml when more than one file)
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
                options        TEXT,
                emu_id         INT
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

    def open_db(self, db_path):
        """open database

        run after new download of umsa.db
        """

        # connect to umsa db
        self.gdb = sqlite3.connect(os.path.join(db_path, "umsa.db"))
        self.gdb.row_factory = sqlite3.Row
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
        # extension = filename extension, progettosnaps always uses png
        #             but scrapping and projectmess also have jpg
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

        all_sets = {}
        try:
            gdb = sqlite3.connect(os.path.join(db_path, "umsa.db"))
        except sqlite3.OperationalError:
            return
        gdb.row_factory = sqlite3.Row
        gdbc = gdb.cursor()
        gdbc.execute("SELECT sets.id, sets.name, swl.name as swl \
                      FROM sets INNER JOIN swl ON sets.swllink_id=swl.id")
        for i in gdbc.fetchall():
            all_sets["{}:{}".format(i['swl'], i['name'])] = i['id']
        gdbc.close()

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

                self.scan_dat(fobj, all_sets, datfile, dbc)
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

    def scan_dat(self, fobj, all_sets, datfile, dbc):
        """scan dat"""

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
                        continue
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
                        'START:',
                        'SETUP:',
                        'GAMEPLAY:',
                        'PLAY INSTRUCTIONS:',)):

                    tag = line[:-1].lower().capitalize()
                    if tag == 'Play instructions':
                        tag = 'Play Inst.'
                    elif tag == 'Wip':
                        tag = 'WIP'
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
            for swl in swls.keys():
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
                    # TODO: dont scan icons, not needed
                    if art_type == 'icons':
                        continue
                    self.scan_what = "{0}/{1}".format(swl, art_type)
                    if swl == 'mame':
                        unused, files = xbmcvfs.listdir(
                            os.path.join(path, art_type, art_type))
                    else:
                        unused, files = xbmcvfs.listdir(
                            os.path.join(path, art_type, swl))
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
        """get artwork for one set"""

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

    def define_filter(self, filter_lists):
        """define filter

        TODO: dont append when all are selected
              do we need a special field for all as the lists can grow with updates?
        """

        self.filter_tables = []
        self.filter_where = []

        # make a string with enough ?,?,? as in the lists
        if filter_lists['Softwarelists']:
            self.filter_tables.append("swl")
            self.filter_where.append(
                "swl.id IN ({}) AND swl.id = sets.swllink_id" .format(
                    ','.join(filter_lists['Softwarelists'])
                )
            )

        if filter_lists['Game Categories'] or filter_lists['Machine Categories']:
            self.filter_tables.append("category cat")
            self.filter_where.append(
                "cat.id IN ( %s ) and cat.id = sets.classification_id" % (
                    ','.join(filter_lists['Game Categories']
                             + filter_lists['Machine Categories']
                            )
                    )
            )

        if filter_lists['Players']:
            self.filter_tables.append("nplayers np")
            self.filter_where.append(
                "np.id IN ( %s ) AND np.id = sets.nplayers_id" % (
                    ','.join(filter_lists['Players'])
                )
            )

        if filter_lists['Years']:
            self.filter_tables.append("year y")
            self.filter_where.append(
                "y.id IN ( %s ) AND y.id = sets.year_id" % (
                    ','.join(filter_lists['Years'])
                )
            )

        # TODO: make this count always visible in filter list and keep actual
        # TODO: also make percentage against count of all software
        # count
        self.gdbc.execute("SELECT COUNT (DISTINCT software.id) \
                           FROM {} \
                           WHERE {} \
                           ORDER BY RANDOM() LIMIT 1" .format(
                               ",".join(["software", "sets"] + self.filter_tables),
                               " AND ".join(
                                   ["software.id = sets.softwarelink_id"] + self.filter_where),))
        return self.gdbc.fetchone()[0]

    def get_random_id(self):
        """get a random id"""

        select_statement = "SELECT DISTINCT s.id \
                            FROM {} \
                            WHERE {} \
                            ORDER BY RANDOM() LIMIT 1".format(
                                ",".join(["software s", "sets"] + self.filter_tables),
                                " AND ".join(["s.id = sets.softwarelink_id"] + self.filter_where),
                            )

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
                         FROM {} WHERE {} \
                         ORDER BY RANDOM() LIMIT 1".format(
                             ','.join(["sets", "art_set"] + self.filter_tables),
                             ' AND '.join(
                                 ["type IN ({})".format("'"+"','".join(art_types)+"'"),
                                  "sets.id = art_set.id"] + self.filter_where
                             )
                         )
            self.gdbc.execute(statement)
            rand_art = self.gdbc.fetchone()
        # and without filter if we haven't found anything
        if not rand_art:
            statement = "SELECT sets.id, art_set.extension, art_set.path, art_set.type \
                        FROM sets, art_set \
                        WHERE type IN ({}) AND sets.id = art_set.id \
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

    def make_time_nice(self, timestamp):
        """Return a nice time string from a timestamp"""

        minute, seconds = divmod(
            int(time.time() - time.mktime(time.strptime(timestamp, "%Y-%m-%d %H:%M"))), 60
        )
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

        minute, seconds = divmod(i[2], 60)
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

    def get_all_emulators(self):
        """Return all different emulators

        Returns a dictonary with the name as key, rest as values.
        """

        self.sdbc.execute("SELECT id, name, exe, dir, zip FROM emu ORDER BY name")
        emus = {}
        for i in self.sdbc.fetchall():
            emus[i[1]] = {
                'id'    : i[0],
                'exe'   : i[2],
                'dir'   : i[3],
                'zip'   : i[4]
            }
        return emus

    def get_emulator(self, source=None, swl_name=None):
        """Returns different emulators based on source or swl_name

        Returns dictonary with name as key, rest as values.
        """

        if source:
            self.sdbc.execute(
                "SELECT e.name, e.exe, e.dir, e.zip \
                 FROM emu e, emu_conn ec \
                 WHERE ec.source = ? AND ec.emu_id = e.id \
                 ORDER BY e.name", (source,)
            )
        else:
            self.sdbc.execute(
                "SELECT e.name, e.exe, e.dir, e.zip \
                 FROM emu e, emu_conn ec \
                 WHERE ec.swl = ? AND ec.emu_id = e.id \
                 ORDER BY e.name", (swl_name,)
            )

        emus = {}
        for i in self.sdbc.fetchall():
            emus[i[0]] = {'exe': i[1], 'dir': i[2], 'zip': i[3]}
        return emus

    def save_emulator(self, name, exe, working_dir, zip_support, source=None, swl_name=None):
        """Save different emulator to database and also connect it"""

        self.sdbc.execute(
            "INSERT INTO emu (name, exe, dir, zip) VALUES (?,?,?,?)",
            (name, exe, working_dir, zip_support)
        )
        self.sdb.commit()
        emu_id = self.sdbc.lastrowid
        return self.connect_emulator(emu_id, source=source, swl_name=swl_name)

    def connect_emulator(self, emu_id, source=None, swl_name=None):
        """Connect emulator to source or softwarelist"""

        if source:
            self.sdbc.execute(
                "INSERT INTO emu_conn (emu_id, source) VALUES (?, ?)", (emu_id, source)
            )
            self.sdb.commit()
        elif swl_name:
            self.sdbc.execute(
                "INSERT INTO emu_conn (emu_id, swl) VALUES (?, ?)", (emu_id, swl_name)
            )
            self.sdb.commit()

    def write_options(self, set_id, options):
        """Write options"""

        self.sdbc.execute(
            "UPDATE sets SET options = ? WHERE id = ?", (set_id, options)
        )
        self.sdb.commit()

    def write_status_after_play(self, set_id, played_seconds):
        """Write play status to set

        (played seconds and how many times started)
        """

        date = time.strftime("%Y-%m-%d %H:%M")

        self.sdbc.execute(
            "SELECT time_played, play_count FROM sets WHERE id = ?", (set_id,)
        )
        set_fetch = self.sdbc.fetchone()

        # update data
        if set_fetch:
            set_data = (date, played_seconds+set_fetch[0], set_fetch[1]+1, set_id)
            self.sdbc.execute(
                "UPDATE sets \
                 SET last_played = ?, time_played = ?, play_count = ? \
                 WHERE id = ?", (set_data)
            )
        # new data
        else:
            set_data = (set_id, date, played_seconds, 1)
            self.sdbc.execute(
                "INSERT INTO sets (id, last_played, time_played, play_count) \
                 VALUES (?,?,?,?)", (set_data)
            )

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

    def get_prevnext_software(self, sid, prev_or_next):
        """Execute prepared statement for the previous or next entries

        Returns a software list.
        """

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

        # TODO !!! duplicate from execute_statement
        # only thing to take care of is direction !!!

        # build tables and where clause
        if self.use_filter:
            tables = ','.join(
                ["software s", "sets"] + self.filter_tables
            )
            where = " AND ".join(
                ["s.id = sets.softwarelink_id"] + self.filter_where
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
                   FROM {} \
                   WHERE y.id = s.year_id AND m.id = s.developer_id \
                   AND s.name {} ? AND {} ORDER BY {} {} LIMIT 100".format(
                       tables, snd, where, order, direction
                   )
        xbmc.log("UMSA dbmod get_prevnext_software: execute statement\n{}".format(execute))
        self.gdbc.execute(execute, (sname,))
        slist = self.gdbc.fetchall()

        if prev_or_next == 'prev':
            pos = len(slist)
            software_list = reversed(slist)
        else:
            pos = 0
            software_list = slist

        results = []
        if (prev_or_next == 'next'
                or (prev_or_next == 'prev' and len(slist) == 100)):
            results.append({'id': 'prev', 'name': 'PREVIOUS', 'year': '<<<', 'maker': '<<<',})
            pos += 1
        for i in software_list:
            results.append({'id': i[1], 'name': i[0], 'year': i[2], 'maker': i[3],})
        if (prev_or_next == 'prev'
                or (prev_or_next == 'next' and len(slist) == 100)):
            results.append({'id': 'next', 'name': 'NEXT', 'year': '>>>', 'maker': '>>>',})
            pos -= 1

        return results, pos

    def execute_statement(self, set_id):
        """Execute prepared statement with filter settings

        TODO:
        ! optimize: remove count, only show next 100, not prev 50
        - optimize2: rewritte sql for filters, needs join
        - directly get a dictonary from database
        - get times for everything
        - extend logging
        """

        #time1 = time.time()
        # build tables and where clause
        if self.use_filter:
            tables = ','.join(
                ["software s", "sets"] + self.filter_tables
            )
            where = " AND ".join(self.filter_where + ["s.id = sets.softwarelink_id"])
        else:
            tables = "software s, sets"
            where = "s.id = sets.softwarelink_id"

        # add self.table and self.where
        if self.table:
            if self.table not in tables:
                tables += ", " + self.table
        if self.where:
            where += " AND " + self.where

        # count overall
        count_statement = 'SELECT COUNT(DISTINCT s.id) FROM {} WHERE {}'.format(
            tables, where
        )
        self.gdbc.execute(count_statement)
        result_count = self.gdbc.fetchone()[0]
        xbmc.log("UMSA: dbmod: execute_statement, count = {}".format(result_count))

        #if result_count == 0:
        #    # try without filter
        #    tables = "software s, sets"
        #    where = "s.id = sets.softwarelink_id"
        #
        #    # add self.table and self.where
        #    if self.table:
        #        if self.table not in tables:
        #            tables += ", " + self.table
        #    if self.where:
        #        where += " AND " + self.where
        #
        #    # count overall
        #    count_statement = 'SELECT COUNT(DISTINCT s.id) \
        #         FROM %s WHERE %s' % (tables, where)
        #    self.gdbc.execute(count_statement)
        #    result_count = self.gdbc.fetchone()[0]
        #    xbmc.log("UMSA: dbmod: execute_statement, count wo filters = {}".format(result_count))

        # get software name from set id
        #self.gdbc.execute(
        #    "SELECT s.name \
        #     FROM software s, sets \
        #     WHERE sets.id = ? \
        #     AND s.id = sets.softwarelink_id", (set_id,)
        #)
        #sname = self.gdbc.fetchone()[0]
        self.gdbc.execute(
            "SELECT software.name FROM software \
                JOIN sets ON software.id = sets.softwarelink_id \
                WHERE sets.id = ?", (set_id,))
        sname = self.gdbc.fetchone()[0]

        #time4 = time.time()
        #xbmc.log("UMSA: dbmod: execute_statement, count time: {:.0f}ms".format((time4-time1)*1000))

        # add tables year, maker when not already in
        if "year y" not in tables:
            tables += ", year y"
        if "maker m" not in tables:
            tables += ", maker m"

        # add ordering
        if self.order == 'name':
            order = 's.name'
        elif self.order == 'year':
            order = 'y.name, s.name'
        elif self.order == 'publisher':
            order = 'm.name, s.name'
        else:
            self.order = 's.name'

        # get previous 50
        #prev_statement = 'SELECT DISTINCT s.name \
        #     FROM %s \
        #     WHERE y.id = s.year_id AND m.id = s.developer_id \
        #           AND s.name <= ? AND %s \
        #     ORDER BY %s DESC LIMIT 50' % (tables, where, order)
        ##xbmc.log("UMSA: dbmod: prev_statement {}".format(prev_statement))
        #self.gdbc.execute(prev_statement, (sname,))
        #prev = self.gdbc.fetchall()
        #time5 = time.time()
        #xbmc.log('UMSA: dbmod: get previous 50: {:.0f}ms'.format((time5 - time4) * 1000))

        # get the software list
        #fetch_statement = "SELECT DISTINCT \
        #                       s.name as name, s.id as id, y.name as year, m.name as maker \
        #                   FROM {} WHERE y.id = s.year_id AND m.id = s.developer_id \
        #                   AND s.name >= ? AND {} ORDER BY {} ASC LIMIT 100".format(
        #                       tables, where, order
        #                   )
        fetch_statement = "SELECT DISTINCT \
                               s.name as name, s.id as id, y.name as year, m.name as maker \
                           FROM {} WHERE y.id = s.year_id AND m.id = s.developer_id \
                           AND s.name >= (SELECT name FROM software \
                               WHERE name <= ? ORDER BY name DESC LIMIT 50, 1) \
                                   AND {} ORDER BY {} ASC LIMIT 100".format(tables, where, order)
        #xbmc.log("UMSA: get swl statement: {}".format(fetch_statement))
        #self.gdbc.execute(fetch_statement, (prev[-1][0],))
        self.gdbc.execute(fetch_statement, (sname,))
        slist = self.gdbc.fetchall()
        #time6 = time.time()
        #xbmc.log('UMSA: dbmod: get final 100: {:.0f}ms'.format((time6 - time5) * 1000))

        # set prev and next in list
        slist.insert(0, {'id': "prev", 'name': "PREV", 'year': "<<<", 'maker': '<<<'})
        slist.append({'id': "next", 'name': "NEXT", 'year': ">>>", 'maker': '>>>'})

        # create dict for return, get pos, set prev/next
        #d = []
        pos = 0
        count = 0
        #if len(prev) == 50:
        #    d.append({'id': 'prev', 'name': 'PREVIOUS', 'year': '<<<', 'maker': '<<<',})
        #    count += 1
        for i in slist:
        #    d.append({"id": i[1], 'name': i[0], 'year': i[2], 'maker' : i[3],})
            if sname == i['name']:
                pos = count
            count += 1
        #if len(slist) == 100:
        #    d.append({'id': 'next', 'name': 'NEXT', 'year': '>>>', 'maker': '>>>'})

        #time7 = time.time()
        #xbmc.log('UMSA dbmod: build dict for return: {:.0f}ms'.format((time7 - time6) * 1000))

        #return d, pos, result_count
        return slist, pos, result_count

    def get_by_software(self, set_id):
        """Return list of software"""

        self.table = ''
        self.where = ''
        return self.execute_statement(set_id)

    def get_software_for_source(self, set_id, source):
        """Return list of software based on MAME source file"""

        self.table = ''
        self.where = 'sets.source = "%s"' % (source,)
        return self.execute_statement(set_id)

    def get_by_cat(self, cat, set_id):
        """Return list of software based on category"""

        self.table = 'category cat'
        self.where = 'cat.name = "{}" AND cat.id = sets.classification_id'.format(cat,)
        return self.execute_statement(set_id)

    def get_by_year(self, year, set_id):
        """Return list of software based on year"""

        self.gdbc.execute("SELECT id FROM year WHERE name = ?", (year,))
        year_id = self.gdbc.fetchone()[0]

        self.table = 'year y'
        self.where = 'sets.id in (SELECT sets.id FROM sets, year y \
                      WHERE y.id = {} AND y.id = sets.year_id)'.format(year_id)
        return self.execute_statement(set_id)

    def get_by_maker(self, maker, set_id):
        """Return list of software based on maker"""

        self.gdbc.execute("SELECT id FROM maker WHERE name = ?", (maker,))
        maker_id = self.gdbc.fetchone()[0]

        self.table = 'maker m'
        self.where = 'sets.id in (SELECT sets.id FROM sets, maker m \
                      WHERE m.id = {} AND m.id = sets.publisher_id)'.format(maker_id)
        return self.execute_statement(set_id)

    def get_by_swl(self, swl_name, set_id):
        """Return list of software based on softwarelist"""

        self.gdbc.execute("SELECT id FROM swl WHERE name = ?", (swl_name,))
        swl_id = self.gdbc.fetchone()[0]

        self.table = "swl"
        self.where = "swl.id = {} AND swl.id = sets.swllink_id".format(swl_id)

        return self.execute_statement(set_id)

    def get_last_played(self, order):
        """get_last_played"""

        results = []
        software_dict = {}

        # get status for sets
        self.sdbc.execute(
            "SELECT id, last_played, play_count, time_played FROM sets \
             ORDER BY %s DESC LIMIT 100" % (order)
        )

        # get software info for sets from status.db
        for i in self.sdbc.fetchall():
            self.gdbc.execute(
                "SELECT software.id, software.name, year.name as year, maker.name as maker \
                 FROM software \
                 JOIN year ON software.year_id = year.id \
                 JOIN maker ON software.developer_id = maker.id \
                 JOIN sets ON software.id = sets.softwarelink_id \
                 WHERE sets.id = ?", (i['id'],)
            )
            software = self.gdbc.fetchone()

            # put in dict to summarize sets
            if software['id'] in software_dict.keys():
                software_dict[software[1]]["play_count"] += i['play_count']
                software_dict[software[1]]["time_played"] += i['time_played']
                if software_dict[software[1]]["last_played"] < i['last_played']:
                    software_dict[software[1]]["last_played"] = i['last_played']
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

            minute, seconds = divmod(status["time_played"], 60)
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
        """get parts for a set id

        sets can have more than one media
        like 2 floppies or 1 floppy and 1 hdd or cd-rom
        """

        self.gdbc.execute(
            "SELECT   p.name, pv.name, pv.disk \
             FROM     part_set pv, part p \
             WHERE    p.id = pv.part_id AND pv.variant_id = ? \
             ORDER BY p.name", (set_id,)
        )
        return self.gdbc.fetchall()

    def get_disk(self, swl_name, set_name):
        """get disk"""

        self.gdbc.execute(
            "SELECT sets.id FROM sets, swl \
             WHERE sets.name = ? AND swl.name = ? AND swl.id = sets.swllink_id",
            (set_name, swl_name)
        )
        set_id = self.gdbc.fetchone()

        self.gdbc.execute(
            "SELECT     p.disk \
             FROM       part_set p \
             WHERE      p.variant_id = ?", (set_id[0],)
        )
        disk = self.gdbc.fetchone()

        return disk[0]

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
                    _cmdopt, unused = self.create_cmdline(
                        list(_parts2), _devices, _set
                    )
                    more_options += _cmdopt
                # else add the requirement set as option
                # directly after machine name
                # hopefully most of the time mame will then
                # find the correct swl entry
                else:
                    more_options += [_set]

            # when we know the devices also set -snapname and -statename
            cmd_options = [machine_name]+more_options+_cmd_options+[
                '-snapname',
                '%g/%d_{0}/%i'.format(first_device),
                '-statename',
                '%g/%d_{0}'.format(first_device),
            ]

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

        return cmd_options

    def get_all_dbentries(self, cat):
        """Return select parameters based on filter categories

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
            "SELECT DISTINCT s.id, s.name, year.name as year, maker.name as maker \
             FROM software s \
             JOIN year ON s.year_id = year.id \
             JOIN maker ON s.developer_id = maker.id \
             JOIN sets ON s.id = sets.softwarelink_id \
             WHERE sets.gamename LIKE ? \
             ORDER BY s.name LIMIT 1", (search+'%',)
        )
        #search_results = self.gdbc.fetchone()
        #if search_results:
        #    ret = {'id': search_results['id'],
        #           'name': search_results['name'],
        #           'year': search_results['year'],
        #           'maker': search_results['maker'],}
        #else:
        #    ret = {'id': 0, 'name': '( {} )'.format(search), 'year': '', 'maker': '',}
        return self.gdbc.fetchone()

    def get_artwork_by_software_id(self, software_id, artwork):
        """get artwork by software id

        fetch given artwork type and all machines for a software id

        TODO: an abbreviation for machine name would make text shorter

        # TODO: should check first for a snap of machine in software
        # first needs export of machine in software from umsa
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

        count, pos, result = 0, None, []
        for i in self.gdbc.fetchall():
            result.append({'id': i[0], 'name': i[1], 'year': i[2], 'maker': i[3],})

            # check if search is in beginning of s.name and set pos
            if search.lower() == i[1][:len(search)].lower() and not pos:
                pos = count
            count += 1
        if not pos:
            pos = 0

        # if results_count > 100:
        #     result.append({'id' : 'next', 'name' : '>>> NEXT'})

        # xbmc.log("search pos, c: {}, {}".format(str(pos), str(c)))
        return result, pos, results_count

    def get_machine_name(self, machine_id):
        """Get name of machine from id"""

        self.gdbc.execute("SELECT m.name, m.gamename FROM sets m WHERE m.id = ?", (machine_id,))
        machine = self.gdbc.fetchone()
        return machine[0], machine[1]

    def count_source(self, source):
        """Count all source files in MAME"""

        self.gdbc.execute("SELECT COUNT(*) FROM sets WHERE source = ?", (source,))
        return self.gdbc.fetchone()[0]

    def count_machines_for_swl(self, swl_name):
        """Count all machines for 1 software list"""

        self.gdbc.execute(
            "SELECT COUNT(DISTINCT sets.id) \
            FROM sets, swl, swl_status ss \
            WHERE swl.name = ? \
                AND swl.id = ss.swl_id \
                AND sets.id = ss.system_id",
            (swl_name,)
        )
        return self.gdbc.fetchone()[0]

    def get_machines(self, swl_name, machine=None):
        "Get original and compatible machines for 1 software list"

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

        self.gdbc.execute("SELECT name FROM sets WHERE id = ?", (set_id,))
        return self.gdbc.fetchone()[0]

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
        """get best machine for set"""

        best_machine = None

        # get originals, compatible machines
        machines, unused = self.get_machines(swl_name)

        if len(machines) == 0:
            pass # no machine found
        elif len(machines) == 1:
            best_machine = machines[0]
        # check if only 1 original
        elif (machines[0]['status'] == "original"
              and machines[1]['status'] == "compatible"):
            best_machine = machines[0]
        else:
            # check if swl_machine is in machines
            for machine in machines:
                #xbmc.log("{}".format(machine))
                if machine['id'] == swl_machine_id:
                    best_machine = machine
                    #xbmc.log( "-- yeah, got {} from db".format(best_machine,))
            # no hit until now, set first machine
            if not best_machine:
                best_machine = machines[0]
                #xbmc.log("-- ok, damn, setting the first entry %s" % (best_machine))
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

        # get all sets nicely sorted (last played, prefered history, year)
        # includes a best machine to use for swl set

        # TODO:
        # - include preferred country (select it or make it first in list?)

        # - get also types of artwork for each set
        # - get the dat entries for each set
        """

        time1 = time.time()

        #xbmc.log("get_all_for_software")
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
        #self.gdbc.execute(
        #    "SELECT \
        #        v.id, v.name, v.gamename, v.detail, v.source, \
        #        y.name, m.name, swl.name, swl.system_id, \
        #        v.display_type, v.display_rotation, c.name, c.flag, \
        #        np.name, v.cloneof_id \
        #        FROM \
        #        sets v, swl, \
        #        year y, maker m, \
        #        category c, nplayers np \
        #        WHERE \
        #        v.softwarelink_id = ? \
        #        AND v.year_id = y.id \
        #        AND v.publisher_id = m.id \
        #        AND c.id = v.classification_id \
        #        AND np.id = v.nplayers_id \
        #        AND v.swllink_id = swl.id \
        #        ORDER BY \
        #        y.name, v.cloneof_id, v.gamename",
        #    (software_id,)
        #)
        all_sets.append(self.gdbc.fetchall())

        # TODO: make optional with settings
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
        for i in self.gdbc.fetchall():
            #xbmc.log("-- %s - %s" % (software_id, i[0]))
            if software_id == i[0]:
                continue
            #xbmc.log("-- oh look, different software with the same name")
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
                JOIN nplayers ON sets.nplayers_id \
                WHERE \
                    sets.softwarelink_id = ? \
                ORDER BY \
                    year.name, sets.cloneof_id, sets.gamename",
                (i[0],)
            )
            #self.gdbc.execute(
            #    "SELECT \
            #        v.id, v.name, v.gamename, v.detail, v.source, \
            #        y.name, m.name, swl.name, swl.system_id, \
            #        v.display_type, v.display_rotation, c.name, c.flag, \
            #        np.name, v.cloneof_id \
            #     FROM \
            #        sets v, swl, \
            #        year y, maker m, \
            #        category c, nplayers np \
            #     WHERE \
            #        v.softwarelink_id = ? \
            #        AND v.year_id = y.id \
            #        AND v.publisher_id = m.id \
            #        AND c.id = v.classification_id \
            #        AND np.id = v.nplayers_id \
            #        AND v.swllink_id = swl.id \
            #     ORDER BY \
            #        y.name, v.cloneof_id, v.gamename",
            #    (i[0],)
            #)
            all_sets.append(self.gdbc.fetchall())

        diff_machines = {}
        set_ids = []
        count = 1
        for diff_machine in all_sets:
            for machine in diff_machine:

                set_ids.append(str(machine[0]))
                resulting_machine = ''

                # TODO get status in one select like art and dat
                # get last_played
                last_played = self.get_status_for_set(machine[0])
                #xbmc.log("last played", last_played)

                # get artwork
                #aw = self.get_artwork_for_set(machine[0])

                # get dat entries
                #dat = self.get_dat_for_set(machine[0])

                if machine[8] == 270257: # machine mame
                    # resulting_machine is the parent
                    if machine[14]:
                        resulting_machine = machine[14]
                    else:
                        resulting_machine = machine[0]
                    # resulting_machine = machine[11] use category
                    best_machine = None
                    machine_name = 'mame'
                    if machine[12]: # ismachine
                        machine_label = machine[11]
                    else:
                        machine_label = 'Arcade'
                else: # swl
                    # diff machine is swl machine
                    resulting_machine = str(machine[8]) # TODO: to test used machine name from swl
                    # get best machine
                    best_machine = self.get_best_machine_for_set(machine[7], machine[3], machine[8])
                    #xbmc.log("best machine:", best_machine)
                    if best_machine:
                        machine_name = best_machine['setname']
                        machine_label = best_machine['label2']
                    else:
                        self.gdbc.execute(
                            "SELECT name, gamename \
                             FROM sets \
                             WHERE id = ?", (machine[8],)
                        )
                        machine_name, machine_label = self.gdbc.fetchone()
                        #x = self.gdbc.fetchone()
                        #machine_name = x[0]
                        #machine_label = x[1] #[:len(x[1]) - len(x[2])].strip() # remove detail

                # TODO: check for machine from software
                # and set first otherwise problem
                # when more machines with earliest year

                # create key in diff_machines
                if resulting_machine not in diff_machines:
                    diff_machines[resulting_machine] = {
                        'id'      : count,
                        'setlist' : []
                    }
                    count += 1

                # TODO: what is really needed?
                # swl machine is not needed?
                # make last_played 3 entries here?

                diff_machines[resulting_machine]['setlist'].append(
                    {
                        'id'                    : machine[0],
                        'name'                  : machine[1],
                        'gamename'              : machine[2],
                        'detail'                : machine[3],
                        'source'                : machine[4],
                        'year'                  : machine[5],
                        'publisher'             : machine[6],
                        'swl_name'              : machine[7],
                        'swl_machine_id'        : machine[8],
                        'machine_name'          : machine_name,
                        'machine_label'         : machine_label,
                        'display_type'          : machine[9],
                        'display_rotation'      : machine[10],
                        'category'              : machine[11],
                        'nplayers'              : machine[13],
                        'clone'                 : machine[14],
                        'is_machine'            : machine[12],
                        'last_played'           : last_played,
                        #'artwork'               : aw,
                        #'dat'                   : dat,
                    }
                )

        # create list to return
        return_list = []
        # sort seems to work for sorting by id

        # TODO: seems to be a general sorting problem with
        # sorted(var.items()) for example with donkey kong
        #py3 problem sorted_x = sorted(diff_machines.items(), key=operator.itemgetter(1))
        #for i in sorted_x:
        for i in diff_machines.items():
            return_list.append(i[1]['setlist'])

        # get absolut latest played
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

        # TODO: gamename is complete setname, do i want it without detail?

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
