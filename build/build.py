#!/usr/bin/env python3
"""Rebuild the Open Shifts page from the booking report PDFs in reports/.

For each kind of report (Daily, Weekend, XMAS, March Break, New Years,
Vacation Tracker) the newest PDF in reports/ is used. Kinds with no PDF keep
the figures already saved in data/state.json. Writes site/index.html and
updates data/state.json and data/routes.json.

Needs Python 3 and pdftotext (poppler-utils). No other packages.
"""
import json, os, re, subprocess, sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)

SHEETS = [  # name, hasDay, hasOpen, hasPay
    ('Daily Update', False, False, True),
    ('Weekend Trip', True, True, False),
    ('XMAS Week', False, False, True),
    ('March Break Week', False, False, True),
    ('New Years Week', False, False, True),
]
SHORT = {'Daily Update': 'Daily', 'Weekend Trip': 'Weekend', 'XMAS Week': 'XMAS',
         'March Break Week': 'March Break', 'New Years Week': 'New Years'}

def tm(t): return int(t[:2]) * 60 + int(t[3:])
def hm(m): return '%02d:%02d' % (m // 60, m % 60)
def norm(s): return re.sub(r'\s+', ' ', s.strip()).replace("'", '\u2019')

def pdftext(path):
    return subprocess.run(['pdftotext', '-layout', path, '-'], check=True,
                          capture_output=True, text=True).stdout.replace('\f', '\n')

def kind_of(text):
    head = '\n'.join(text.split('\n')[:15])
    if 'Vacation Tracker' in head: return 'vac'
    if 'Christmas Week' in head: return 'XMAS Week'
    if 'March Break Week' in head: return 'March Break Week'
    if 'New Years Week' in head: return 'New Years Week'
    if re.search(r'Work\s+(Saturday|Sunday)', text): return 'Weekend Trip'
    if 'Daily Open Work' in text: return 'Daily Update'
    return None

def stamp_of(text):
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})', text)
    return datetime(int(m[3]), int(m[1]), int(m[2]), int(m[4]), int(m[5])) if m else None

def git_time(path):
    try:
        out = subprocess.run(['git', 'log', '-1', '--format=%ct', '--', path], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip()
        return int(out) if out else 0
    except Exception:
        return 0

# ---------------- shift report parser ----------------
RUN = re.compile(r'^\s*(?:(\d+)\s+)?(\d\w*-\d\w*)\s+(.*?)\s*(\d\d:\d\d)\s+(\d\d:\d\d)\s+(.*?)\s*(\d\d:\d\d)(?:\s+(\d\d:\d\d))?\s*$')
RUN2 = re.compile(r'^\s*(\d\w*-\d\w*)\s+(.*?)\s*(\d\d:\d\d)\s+(\d\d:\d\d)\s+(\S.*?)\s*$')
TOT = re.compile(r'^\s*(\d\d:\d\d)\s+(\d\d:\d\d)\s*$')

def parse_shifts(text, weekend):
    out, warn = [], []
    sec = None; day = ''; cur = None; labels = None; pend = None; lastrun = None
    def close():
        nonlocal cur
        if cur:
            if not cur['runs']: warn.append('shift %s has no runs' % cur['s'])
            out.append(cur)
        cur = None
    for ln, raw in enumerate(text.split('\n'), 1):
        line = raw.rstrip(); st = line.strip()
        if not st: continue
        toks = st.split()
        if re.match(r'^\d+/\d+/\d{4}', st): continue
        if 'Work' in st or 'Trippers' in st or 'Report' in st or 'Week' in st:
            if 'Odd Work' in st: sec = 'Odd Work'
            elif 'Relief Work' in st: sec = 'Relief Work'
            elif 'AM Biddable' in st: sec = 'AM Trippers'
            elif 'PM Biddable' in st: sec = 'PM Trippers'
            if 'Saturday' in st: day = 'Saturday'
            if 'Sunday' in st: day = 'Sunday'
            lastrun = None; continue
        if st.startswith(('Shift', 'Limit', 'General Spare', 'Holiday Spare')): continue
        if all(re.match(r'^(SAT|SUN)\d$', t) for t in toks):
            labels = [(m.group(), m.start()) for m in re.finditer(r'(SAT|SUN)\d', line)]; lastrun = None; continue
        m = RUN.match(line)
        if m:
            sh, run, onl, on, off, offl, plat, pay = m.groups()
            if sh is not None:  # tripper: shift number on the run line
                close()
                if pend is None: warn.append('line %d: tripper without header' % ln); pend = {'booked': False}
                cur = {'s': sh, 'sec': sec, 'runs': [], 'booked': pend['booked'], 'day': '', 'open': '', 'tot': plat, 'pay': pay or plat}
                pend = None
            if cur is None: warn.append('line %d: run without shift' % ln); continue
            cur['runs'].append([run, None, norm(onl), on, off, norm(offl), '', plat]); lastrun = cur['runs'][-1]; continue
        m2 = RUN2.match(line)
        if m2 and cur is not None:  # off location too long: plat wrapped to next line
            run, onl, on, off, offl = m2.groups()
            cur['runs'].append([run, None, norm(onl), on, off, norm(offl), '', None]); lastrun = cur['runs'][-1]; continue
        if lastrun is not None and lastrun[7] is None and re.match(r'^\d\d:\d\d$', st):
            lastrun[7] = st; continue
        if lastrun is not None and lastrun[5] == '' and re.match(r'^[A-Za-z]', st) and not re.search(r'\d\d:\d\d', st):
            lastrun[5] = norm(st); continue
        if lastrun is not None and re.match(r'^[\dA-Za-z,]+$', st) and lastrun[1] is None:
            lastrun[1] = st; lastrun = None; continue
        lastrun = None
        m = TOT.match(line)
        if m:
            if cur is None: warn.append('line %d: total without shift' % ln); continue
            cur['tot'], cur['pay'] = m.groups(); close(); continue
        if toks[0].isdigit() and all(t in ('Daily', 'XXXX') for t in toks[1:]):
            close()
            if weekend:
                if labels is None: warn.append('line %d: no SAT/SUN labels' % ln); labels = []
                booked = {min(labels, key=lambda l: abs(l[1] - x.start()))[0] for x in re.finditer('XXXX', line)} if labels else set()
                opn = [l[0] for l in labels if l[0] not in booked]
                cur = {'s': toks[0], 'sec': sec, 'runs': [], 'booked': not opn, 'day': day, 'open': ', '.join(opn)}
            else:
                cur = {'s': toks[0], 'sec': sec, 'runs': [], 'booked': 'XXXX' in toks, 'day': '', 'open': ''}
            continue
        if all(t in ('Daily', 'XXXX') for t in toks):
            close(); pend = {'booked': 'XXXX' in toks}; continue
        warn.append('line %d not understood: %s' % (ln, st[:80]))
    close()
    return out, warn

def parse_spares(text):
    rows = []
    for l in text.split('\n')[:15]:
        m = re.match(r'^\s*(General Spares?|Holiday Spare)(?: place holder)?\s+(\d+)\s+(\d+)\s+(\d+)\s*$', l)
        if m:
            lim, bk, av = int(m[2]), int(m[3]), int(m[4])
            if lim > 0:
                rows.append(['General spares' if m[1].startswith('General') else 'Holiday spare', lim, bk, av])
    return rows

def parse_vac(text):
    rows = []
    for l in text.split('\n'):
        m = re.match(r'^(Week \d+)\s+(.*?)\s{2,}(\d+)\s+(\d+)\s+(\d+)\s*$', l)
        if m:
            dates = m[2].replace('Janurary', 'January').replace('Apr ', 'April ')
            rows.append([m[1], dates, int(m[3]), int(m[4]), int(m[5])])
    if not rows: raise ValueError('no weeks found in Vacation Tracker')
    tot = [sum(r[i] for r in rows) for i in (2, 3, 4)]
    return {'tot': tot, 'rows': rows}

HOLIDAY = ('XMAS Week', 'March Break Week', 'New Years Week')
_GUIDE = None
def guide_order(run, on, off):
    """Routes in driving order from the Reduced Week run guide, or None."""
    global _GUIDE
    if _GUIDE is None:
        try: _GUIDE = json.load(open(P('data', 'reduced-week-guide.json'), encoding='utf8'))['runs']
        except Exception: _GUIDE = {}
    trips = _GUIDE.get(run)
    if not trips: return None
    a = tm(on); b = tm(off)
    if b <= a: b += 1440
    return [rt for _, rt, t, e in trips if t < b - 3 and e > a + 8] or None

def build_sheet(name, has_day, has_open, has_pay, parsed, routes, stats):
    def split(s): return [x.strip() for x in s.split(',') if x.strip()]
    seen = set(); shifts = []
    for s in parsed:
        if s['booked']: continue
        sn = s['s'].lstrip('0') or '0'
        key = (sn, s['day'], s['runs'][0][0], s['runs'][0][3])
        if key in seen: continue
        seen.add(key); runs = []
        for j, r in enumerate(s['runs']):
            if r[1] is None or r[7] is None or not r[2] or not r[5]:
                raise ValueError('%s shift %s run %s is incomplete' % (name, sn, r[0]))
            k = '|'.join([name, r[0], r[2], r[3], r[4], r[5]])
            pdf = split(r[1]); known = routes.get(k)
            g = guide_order(r[0], r[3], r[4]) if name in HOLIDAY else None
            if known is not None and sorted(set(split(known))) == sorted(set(pdf)):
                order = known
            elif g and sorted(set(g)) == sorted(set(pdf)):
                order = ', '.join(g); routes[k] = order
            else:  # new run: keep the report's list (sorted, no repeats)
                order = ', '.join(pdf); routes[k] = order; stats['new_runs'] += 1
            gap = '' if j == 0 else hm((tm(r[3]) - tm(s['runs'][j - 1][4])) % 1440)
            runs.append([r[0], order, r[2], r[3], r[4], r[5], gap, r[7]])
        o = {'s': sn, 'sec': s['sec'], 'tot': s['tot'], 'sp': hm((tm(runs[-1][4]) - tm(runs[0][3])) % 1440),
             'runs': runs, 'day': s['day'], 'open': s['open']}
        if has_pay: o['pay'] = s['pay']
        shifts.append(o)
    return {'name': name, 'hasDay': has_day, 'hasOpen': has_open, 'hasPay': has_pay, 'shifts': shifts}

def label(dt):
    h = dt.hour % 12 or 12
    return '%s %d (%d %s)' % (dt.strftime('%B'), dt.day, h, 'AM' if dt.hour < 12 else 'PM')

# ---------- Route lines for My Work (from OC Transpo GTFS) ----------
GTFS_ZIP = os.environ.get('GTFS_ZIP', '/tmp/gtfs.zip')

def _enc_poly(pts):
    out = []; plat = plng = 0
    for lat, lng in pts:
        ilat, ilng = int(round(lat * 1e5)), int(round(lng * 1e5))
        for d in (ilat - plat, ilng - plng):
            v = ~(d << 1) if d < 0 else d << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63)); v >>= 5
            out.append(chr(v + 63))
        plat, plng = ilat, ilng
    return ''.join(out)

def _simplify(pts, tol_m=6.0):
    import math
    if len(pts) < 3: return pts
    k = 111320.0; c = math.cos(math.radians(pts[0][0]))
    xy = [(p[1] * k * c, p[0] * k) for p in pts]
    keep = [False] * len(pts); keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = xy[a]; bx, by = xy[b]; dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy
        best, bi = -1, -1
        for i in range(a + 1, b):
            px, py = xy[i]
            if L2 == 0: d = math.hypot(px - ax, py - ay)
            else:
                t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > best: best, bi = d, i
        if best > tol_m:
            keep[bi] = True; stack += [(a, bi), (bi, b)]
    return [p for p, kp in zip(pts, keep) if kp]

def _my_routes(page):
    m = re.search(r'const MINE=(\{.*?\});\n', page)
    if not m: return []
    mine = json.loads(m.group(1)); out = []
    for sh in mine.get('shifts', {}).values():
        for r in sh.get('runs', []):
            for v in str(r[1]).split(','):
                v = v.strip()
                if v and v not in out: out.append(v)
    return out

def add_route_shapes(page):
    """Embed the main shape(s) of each booked route as encoded polylines in `const SHAPES={};`.
    Uses the GTFS zip downloaded by the workflow; falls back to data/shapes.json from an earlier build."""
    import csv, io, zipfile
    if 'const SHAPES={};' not in page: return page
    routes = _my_routes(page)
    cache_p = P('data', 'shapes.json')
    cache = json.load(open(cache_p, encoding='utf8')) if os.path.exists(cache_p) else {}
    shapes = {}
    if os.path.exists(GTFS_ZIP):
        try:
            z = zipfile.ZipFile(GTFS_ZIP)
            def rows(name):
                return csv.DictReader(io.TextIOWrapper(z.open(name), encoding='utf-8-sig'))
            rid = {}
            for r in rows('routes.txt'):
                n = (r.get('route_short_name') or '').strip()
                if n in routes: rid.setdefault(r['route_id'], n)
            cnt = {}; heads = {}
            for t in rows('trips.txt'):
                n = rid.get(t['route_id'])
                if n and t.get('shape_id'):
                    key = (n, t.get('direction_id') or '0', t['shape_id'])
                    cnt[key] = cnt.get(key, 0) + 1
                    h = (t.get('trip_headsign') or '').strip()
                    if h:
                        hc = heads.setdefault(key, {}); hc[h] = hc.get(h, 0) + 1
            best = {}
            for (n, d, sid), c in cnt.items():
                if c > best.get((n, d), ('', -1))[1]: best[(n, d)] = (sid, c)
            want = {}; head_of = {}
            for (n, d), (sid, c) in best.items():
                want.setdefault(sid, []).append(n)
                hc = heads.get((n, d, sid), {})
                head_of[(n, sid)] = max(hc, key=hc.get) if hc else ''
            pts = {}
            for r in rows('shapes.txt'):
                sid = r['shape_id']
                if sid in want:
                    pts.setdefault(sid, []).append((int(r['shape_pt_sequence']), float(r['shape_pt_lat']), float(r['shape_pt_lon'])))
            for sid, lst in pts.items():
                lst.sort(); enc = _enc_poly(_simplify([(a, b) for _, a, b in lst]))
                for n in want[sid]: shapes.setdefault(n, []).append({'to': head_of.get((n, sid), ''), 'p': enc})
            print('Route lines from GTFS: %d of %d routes' % (len(shapes), len(routes)))
            for n in shapes: cache[n] = shapes[n]
            json.dump(cache, open(cache_p, 'w', encoding='utf8'), separators=(',', ':'), sort_keys=True)
        except Exception as e:
            print('GTFS route lines skipped:', e, file=sys.stderr)
    final = {n: (shapes.get(n) or cache.get(n)) for n in routes if shapes.get(n) or cache.get(n)}
    missing = [n for n in routes if n not in final]
    if missing: print('No route line for:', ', '.join(missing))
    return page.replace('const SHAPES={};', 'const SHAPES=' + json.dumps(final, separators=(',', ':')) + ';', 1)


def main():
    state = json.load(open(P('data', 'state.json'), encoding='utf8'))
    routes = json.load(open(P('data', 'routes.json'), encoding='utf8'))
    # pick the newest PDF of each kind
    best = {}
    rep = P('reports')
    for fn in sorted(os.listdir(rep)) if os.path.isdir(rep) else []:
        if not fn.lower().endswith('.pdf'): continue
        path = os.path.join(rep, fn)
        try:
            text = pdftext(path)
        except Exception:
            print('SKIP %s: could not read this PDF' % fn); continue
        kind = kind_of(text)
        if kind is None:
            print('SKIP %s: not a booking report or vacation tracker' % fn); continue
        stamp = stamp_of(text)
        nums = tuple(int(x) for x in re.findall(r'\d+', fn))
        rank = (stamp.timestamp() if stamp else 0, git_time(path), nums)
        if kind not in best or rank > best[kind][0]:
            best[kind] = (rank, fn, text, stamp)
    errors = []
    for name, has_day, has_open, has_pay in SHEETS:
        if name not in best: print('%-17s kept (%s)' % (name, state['sheets'][name]['source'])); continue
        _, fn, text, stamp = best[name]
        try:
            parsed, warn = parse_shifts(text, has_day)
            if warn: raise ValueError('; '.join(warn[:5]))
            stats = {'new_runs': 0}
            sheet = build_sheet(name, has_day, has_open, has_pay, parsed, routes, stats)
            if not sheet['shifts']: raise ValueError('no open shifts found')
        except Exception as e:
            errors.append('%s (%s): %s' % (name, fn, e)); continue
        state['sheets'][name] = {'asof': stamp.strftime('%Y-%m-%d %H:%M') if stamp else '', 'source': fn,
                                 'sheet': sheet, 'spare': parse_spares(text)}
        print('%-17s %4d open shifts from %s%s' % (name, len(sheet['shifts']), fn,
              ' (%d new runs, routes in report order)' % stats['new_runs'] if stats['new_runs'] else ''))
    if 'vac' in best:
        try:
            state['vac'] = {'source': best['vac'][1], 'data': parse_vac(best['vac'][2])}
            print('Vacation          %d remaining from %s' % (state['vac']['data']['tot'][2], best['vac'][1]))
        except Exception as e:
            errors.append('Vacation (%s): %s' % (best['vac'][1], e))
    if errors:
        print('\nBUILD STOPPED. The live site was not changed.\n' + '\n'.join(errors), file=sys.stderr)
        sys.exit(1)
    # as-of line
    labs = {}
    for name, *_ in SHEETS:
        a = state['sheets'][name]['asof']
        labs[name] = label(datetime.strptime(a, '%Y-%m-%d %H:%M')) if a else 'unknown date'
    if len(set(labs.values())) == 1:
        asof = next(iter(labs.values()))
    else:
        asof = '; '.join('%s %s' % (SHORT[n], l) for n, l in labs.items())
    data_js = '\n'.join([
        'const DATA=' + json.dumps([state['sheets'][n]['sheet'] for n, *_ in SHEETS], ensure_ascii=False, separators=(',', ':')) + ';',
        open(P('build', 'stations.js'), encoding='utf8').read().strip(),
        'const DAYOFF=' + json.dumps(state['dayoff']['data'], ensure_ascii=False, separators=(',', ':')) + ';',
        'const VAC=' + json.dumps(state['vac']['data'], ensure_ascii=False, separators=(',', ':')) + ';',
        'const SPARE=' + json.dumps({n: state['sheets'][n]['spare'] for n, *_ in SHEETS if state['sheets'][n]['spare']}, ensure_ascii=False) + ';',
        'const MINE=' + (json.dumps(json.load(open(P('data', 'my-work.json'), encoding='utf8')), ensure_ascii=False, separators=(',', ':'))
                         if os.path.exists(P('data', 'my-work.json')) else 'null') + ';',
    ])
    tpl = open(P('build', 'template.html'), encoding='utf8').read()
    body = (tpl.replace('/*__DATA__*/', data_js, 1).replace('__ASOF__', asof, 1)
               .replace('__DAYOFF_ASOF__', state['dayoff']['asof'], 1))
    head = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta name="robots" content="noindex,nofollow">'
            '<style>:root{color-scheme:light;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);'
            'padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}'
            '[hidden]{display:none!important}</style></head><body>\n')
    os.makedirs(P('site'), exist_ok=True)
    open(P('site', 'index.html'), 'w', encoding='utf8').write(head + body + '\n</body></html>\n')
    # Extra ready-made pages (e.g. My Work): build/my-work.html -> site/my-work.html
    extra = P('build', 'my-work.html')
    if os.path.exists(extra):
        page = open(extra, encoding='utf8').read()
        page = add_route_shapes(page)
        open(P('site', 'my-work.html'), 'w', encoding='utf8').write(page)
        print('Built site/my-work.html')
    json.dump(state, open(P('data', 'state.json'), 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(routes, open(P('data', 'routes.json'), 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    print('\nBuilt site/index.html, data as of %s' % asof)

if __name__ == '__main__':
    main()
