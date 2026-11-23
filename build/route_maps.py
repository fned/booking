#!/usr/bin/env python3
"""Route maps for the Runs tab, from OC Transpo's static GTFS.

Same approach as the whereisbus site (scripts/build-gtfs.js): download the
GTFS zip, read routes, trips and shapes, and store each path as a Google
encoded polyline so the page downloads only the route it shows.

For every route (by its public number, e.g. "24") and direction it keeps the
path most trips use, plus other paths that carry a fair share of the trips
(short-turns, branches). Each path gets its headsign and stops.

The result is saved to data/route-maps.json (committed, so a failed download
keeps the last good maps) and written as site/routes/<route>.json by build.py.

Run on its own:  python3 build/route_maps.py [GTFSExport.zip]
"""
import csv, io, json, os, sys, time, urllib.request, zipfile
from collections import Counter, defaultdict

GTFS_URL = os.environ.get('GTFS_URL',
    'https://oct-gtfs-emasagcnfmcgeham.z01.azurefd.net/public-access/GTFSExport.zip')
MAX_AGE_DAYS = 6          # OC Transpo republishes about weekly
VARIANT_SHARE = 0.12      # keep other paths used by at least 12% of a direction's trips
MAX_VARIANTS = 3          # per direction, besides the main path


def encode_polyline(points):
    """Google encoded polyline, precision 5 (same as whereisbus)."""
    out = []; plat = plon = 0; first = True
    def enc(v):
        v = ~(v << 1) if v < 0 else v << 1
        s = ''
        while v >= 0x20:
            s += chr((0x20 | (v & 0x1f)) + 63); v >>= 5
        return s + chr(v + 63)
    for lat, lon in points:
        a, b = round(lat * 1e5), round(lon * 1e5)
        if not first and a == plat and b == plon: continue
        out.append(enc(a - plat) + enc(b - plon)); plat, plon = a, b; first = False
    return ''.join(out)


def rows(z, name):
    try:
        f = z.open(name)
    except KeyError:
        return
    with io.TextIOWrapper(f, encoding='utf-8-sig', newline='') as t:
        for r in csv.DictReader(t):
            yield {k.strip(): (v or '').strip() for k, v in r.items() if k}


def title(s):
    """'LAVAL / LAURIER' -> 'Laval / Laurier' (stop names are upper case in the feed)."""
    if not s or not s.isupper(): return s
    small = {'DE', 'DU', 'DES', 'LA', 'LE', 'ET', 'AND', 'OF'}
    out = []
    for i, w in enumerate(s.split(' ')):
        lw = w.capitalize() if not (i and w in small) else w.lower()
        lw = '-'.join(p.capitalize() for p in lw.split('-')) if '-' in w else lw
        out.append(lw)
    return ' '.join(out).replace("L' ", "L'").replace("D' ", "D'")


def build(zip_bytes):
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    routes = {}
    for r in rows(z, 'routes.txt'):
        routes[r['route_id']] = {'n': r.get('route_short_name') or r.get('route_long_name') or r['route_id'],
                                 'name': r.get('route_long_name', ''), 'color': r.get('route_color', '')}
    # trips per (route number, direction, shape)
    use = defaultdict(Counter); rep = {}; head = defaultdict(Counter)
    for t in rows(z, 'trips.txt'):
        ro = routes.get(t['route_id']); sh = t.get('shape_id')
        if not ro or not sh: continue
        key = (ro['n'], t.get('direction_id') or '0')
        use[key][sh] += 1
        head[(key, sh)][t.get('trip_headsign', '')] += 1
        rep.setdefault((key, sh), t['trip_id'])
    keep = {}  # (key, shape) -> rank in direction
    for key, c in use.items():
        tot = sum(c.values()); ranked = c.most_common()
        keep[(key, ranked[0][0])] = 0
        for i, (sh, n) in enumerate(ranked[1:1 + MAX_VARIANTS], 1):
            if n / tot >= VARIANT_SHARE: keep[(key, sh)] = i
    want_shapes = {sh for _, sh in keep}
    pts = defaultdict(list)
    for r in rows(z, 'shapes.txt'):
        if r['shape_id'] in want_shapes:
            try: pts[r['shape_id']].append((float(r['shape_pt_sequence'] or 0), float(r['shape_pt_lat']), float(r['shape_pt_lon'])))
            except ValueError: pass
    # stops of one representative trip per kept path
    trip_of = {rep[k]: k for k in keep}
    seq = defaultdict(list)
    for r in rows(z, 'stop_times.txt'):
        if r['trip_id'] in trip_of:
            seq[r['trip_id']].append((int(r.get('stop_sequence') or 0), r['stop_id']))
    need = {s for v in seq.values() for _, s in v}
    stops = {}
    for s in rows(z, 'stops.txt'):
        if s['stop_id'] in need:
            try: stops[s['stop_id']] = (title(s.get('stop_name', '')), round(float(s['stop_lat']), 5), round(float(s['stop_lon']), 5), s.get('stop_code', ''))
            except ValueError: pass
    out = {}
    meta = {ro['n']: ro for ro in routes.values()}
    for (key, sh), rank in sorted(keep.items(), key=lambda kv: (kv[0][0], kv[1])):
        n, d = key
        p = sorted(pts.get(sh, []))
        if len(p) < 2: continue
        st = []
        for _, sid in sorted(seq.get(rep[(key, sh)], [])):
            if sid in stops: st.append(list(stops[sid]))
        r = out.setdefault(n, {'route': n, 'name': meta[n]['name'], 'color': meta[n]['color'], 'paths': []})
        enc = encode_polyline([(a, b) for _, a, b in p])
        dup = next((x for x in r['paths'] if x['p'] == enc), None)
        if dup: dup['trips'] += use[key][sh]; continue  # same path under another shape id
        r['paths'].append({'dir': int(d) if d.isdigit() else 0, 'main': rank == 0,
                           'to': head[(key, sh)].most_common(1)[0][0], 'trips': use[key][sh],
                           'p': enc, 'stops': st})
    info = next(rows(z, 'feed_info.txt'), {}) or {}
    return {'version': info.get('feed_version', ''), 'start': info.get('feed_start_date', ''),
            'end': info.get('feed_end_date', ''), 'built': int(time.time()), 'routes': out}


def download():
    req = urllib.request.Request(GTFS_URL, headers={'User-Agent': 'open-shifts-build'})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def refresh(path, force=False, src=None):
    """Update the saved route maps when they are a week old. Never raises:
    on any failure the saved maps (if any) are kept. Returns the data or None."""
    old = None
    if os.path.exists(path):
        try: old = json.load(open(path, encoding='utf8'))
        except Exception: old = None
    if old and not force and not src and time.time() - old.get('built', 0) < MAX_AGE_DAYS * 86400:
        print('Route maps       kept (GTFS %s, %d routes)' % (old.get('version'), len(old['routes'])))
        return old
    try:
        data = build(open(src, 'rb').read() if src else download())
        if not data['routes']: raise ValueError('no routes with paths in the GTFS')
        if old and old.get('version') == data['version'] and old.get('routes') == data['routes']:
            print('Route maps       unchanged (GTFS %s)' % data['version'])  # don't re-commit the same file
            return old
        json.dump(data, open(path, 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        print('Route maps       %d routes from GTFS %s' % (len(data['routes']), data['version']))
        return data
    except Exception as e:
        print('Route maps       could not update (%s); %s' % (e, 'keeping the saved ones' if old else 'the Map buttons will say so'))
        return old


def write_site(data, site_dir):
    d = os.path.join(site_dir, 'routes'); os.makedirs(d, exist_ok=True)
    for n, r in data['routes'].items():
        r = dict(r, gtfs=data['version'])
        safe = ''.join(ch for ch in n if ch.isalnum() or ch in '-_')
        if safe: json.dump(r, open(os.path.join(d, safe + '.json'), 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    refresh(os.path.join(root, 'data', 'route-maps.json'), force=True, src=sys.argv[1] if len(sys.argv) > 1 else None)
