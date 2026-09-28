"""Documented device links and layouts. Never changes monitoring dependencies."""
import math
import sqlite3

VIEWS = ('dependencies', 'physical')
ICONS = ('device', 'server', 'switch', 'router', 'firewall', 'accesspoint', 'printer', 'storage', 'cloud')


def label(value):
    if not isinstance(value, str) or len(value)>120 or any(ord(c)<32 for c in value):
        raise ValueError('Bezeichnung: höchstens 120 Zeichen ohne Steuerzeichen.')
    return value.strip()


class ConnectionStore:
    def init_connections(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS device_links(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
              target_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
              kind TEXT NOT NULL CHECK(kind IN ('cable','wireless')),
              label TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 1,
              CHECK(source_id<target_id),UNIQUE(source_id,target_id,kind,label));
            CREATE INDEX IF NOT EXISTS device_links_target ON device_links(target_id);
            CREATE TABLE IF NOT EXISTS device_map_positions(
              view TEXT NOT NULL CHECK(view IN ('dependencies','physical')),
              device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
              x REAL NOT NULL,y REAL NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
              PRIMARY KEY(view,device_id));
            CREATE TABLE IF NOT EXISTS device_map_icons(
              device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
              icon TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
            ''')

    def connection_state(self):
        return dict(connection_links=self.rows('SELECT * FROM device_links ORDER BY id'),
                    connection_positions=self.rows('SELECT * FROM device_map_positions ORDER BY view,device_id'),
                    connection_icons=self.rows('SELECT * FROM device_map_icons ORDER BY device_id'))

    def save_connection(self, data):
        from .core import integer
        source,target=sorted(integer(data.get(k),1,2147483647,'Gerät') for k in ('source_id','target_id'))
        if source==target: raise ValueError('Zwei unterschiedliche Geräte auswählen.')
        kind=data.get('kind')
        if kind not in ('cable','wireless'): raise ValueError('Kabel oder WLAN auswählen.')
        text=label(data.get('label',''))
        ident=integer(data['id'],1,2147483647,'Verbindung') if data.get('id') else None
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT count(*) FROM devices WHERE id IN (?,?)',(source,target)).fetchone()[0]!=2:
                    raise ValueError('Ein ausgewähltes Gerät existiert nicht mehr. Ansicht neu laden.')
                if ident:
                    revision=integer(data.get('revision'),1,2147483647,'Stand der Verbindung')
                    if not db.execute('UPDATE device_links SET source_id=?,target_id=?,kind=?,label=?,revision=revision+1 WHERE id=? AND revision=?',
                                      (source,target,kind,text,ident,revision)).rowcount:
                        raise ValueError('Die Verbindung wurde inzwischen geändert oder gelöscht. Neu öffnen.')
                else:
                    ident=db.execute('INSERT INTO device_links(source_id,target_id,kind,label) VALUES(?,?,?,?)',
                                     (source,target,kind,text)).lastrowid
                return dict(db.execute('SELECT * FROM device_links WHERE id=?',(ident,)).fetchone())
        except sqlite3.IntegrityError:
            raise ValueError('Diese Verbindung mit derselben Art und Bezeichnung ist bereits eingetragen.')

    def delete_connection(self, data):
        from .core import integer
        ident=integer(data.get('id'),1,2147483647,'Verbindung')
        revision=integer(data.get('revision'),1,2147483647,'Stand der Verbindung')
        with self.connect() as db:
            if not db.execute('DELETE FROM device_links WHERE id=? AND revision=?',(ident,revision)).rowcount:
                raise ValueError('Die Verbindung wurde inzwischen geändert oder gelöscht. Neu öffnen.')
        return dict(ok=True)

    def save_connection_layout(self, data):
        from .core import integer
        values=data.get('positions')
        if not isinstance(values,list) or not 1<=len(values)<=4000:
            raise ValueError('Zwischen 1 und 4.000 Gerätepositionen je Speichervorgang übergeben.')
        normalized=[];seen=set()
        for row in values:
            if not isinstance(row,dict) or row.get('view') not in VIEWS: raise ValueError('Ungültige Grafikansicht.')
            did=integer(row.get('device_id'),1,2147483647,'Gerät');key=(row['view'],did)
            if key in seen: raise ValueError('Eine Geräteposition wurde doppelt übergeben.')
            seen.add(key)
            coords=[]
            for field in ('x','y'):
                v=row.get(field)
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>1000000:
                    raise ValueError('Ungültige Geräteposition.')
                coords.append(round(v,2))
            normalized.append((*key,*coords,integer(row.get('revision',0),0,2147483647,'Stand der Anordnung')))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for view,did,x,y,revision in normalized:
                if not db.execute('SELECT 1 FROM devices WHERE id=?',(did,)).fetchone():
                    raise ValueError('Ein verschobenes Gerät wurde gelöscht. Änderungen verwerfen und neu anordnen.')
                current=db.execute('SELECT revision FROM device_map_positions WHERE view=? AND device_id=?',(view,did)).fetchone()
                if (current['revision'] if current else 0)!=revision:
                    raise ValueError('Die Anordnung wurde inzwischen anders gespeichert. Änderungen verwerfen und erneut anordnen.')
                db.execute('''INSERT INTO device_map_positions(view,device_id,x,y) VALUES(?,?,?,?)
                    ON CONFLICT(view,device_id) DO UPDATE SET x=excluded.x,y=excluded.y,revision=device_map_positions.revision+1''',(view,did,x,y))
        return self.connection_state()

    def save_connection_icon(self, data):
        from .core import integer
        did=integer(data.get('device_id'),1,2147483647,'Gerät')
        icon=data.get('icon');revision=integer(data.get('revision',0),0,2147483647,'Stand des Symbols')
        if icon not in ICONS: raise ValueError('Ein angebotenes Gerätesymbol auswählen.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM devices WHERE id=?',(did,)).fetchone(): raise ValueError('Gerät nicht mehr vorhanden.')
            old=db.execute('SELECT revision FROM device_map_icons WHERE device_id=?',(did,)).fetchone()
            if (old['revision'] if old else 0)!=revision: raise ValueError('Das Symbol wurde inzwischen geändert. Ansicht neu laden.')
            db.execute('''INSERT INTO device_map_icons(device_id,icon) VALUES(?,?) ON CONFLICT(device_id)
                DO UPDATE SET icon=excluded.icon,revision=device_map_icons.revision+1''',(did,icon))
            return dict(db.execute('SELECT * FROM device_map_icons WHERE device_id=?',(did,)).fetchone())
