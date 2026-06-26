import json, urllib.request, os
os.chdir(r'C:\Users\salut\sakyowon-ai')

env = {}
with open('.env') as f:
    for line in f:
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            env[k] = v

url_base = env['SUPABASE_URL']
key = env['SUPABASE_KEY']
headers = {'apikey': key, 'Authorization': f'Bearer {key}'}

def query(table, params=''):
    url = f'{url_base}/rest/v1/{table}?{params}'
    req = urllib.request.Request(url)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f'  [{table}] error: {e}')
        # try without params
        try:
            req2 = urllib.request.Request(f'{url_base}/rest/v1/{table}?limit=5')
            for k2, v2 in headers.items():
                req2.add_header(k2, v2)
            with urllib.request.urlopen(req2, timeout=10) as r2:
                data = json.loads(r2.read())
                if data:
                    print(f'  [{table}] columns: {list(data[0].keys())}')
                return data
        except Exception as e2:
            print(f'  [{table}] also failed: {e2}')
            return []

# First check what tables exist
print('=== TABLE CHECK ===')
readings = query('river_readings', 'limit=5')
species = query('species_observations', 'limit=500')
ehi = query('ehi_scores', 'select=river,ehi_score,grade,species_count&order=calculated_at.desc&limit=30')
alerts = query('invasive_alerts', 'limit=100')

print()
print(f'river_readings: {len(readings)} rows')
print(f'species_observations: {len(species)} rows')
print(f'ehi_scores: {len(ehi)} rows')
print(f'invasive_alerts: {len(alerts)} rows')

if species:
    rivers = {}
    unique = set()
    for s in species:
        r = s.get('river', '')
        if r:
            rivers.setdefault(r, []).append(s.get('taxon_name', ''))
        if s.get('taxon_name'):
            unique.add(s['taxon_name'])
    print(f'\nSpecies: {len(unique)} unique across {len(rivers)} rivers')
    for river in sorted(rivers.keys()):
        print(f'  {river}: {len(set(rivers[river]))} species')

if ehi:
    print('\nEHI scores:')
    seen = set()
    for e in ehi:
        r = e.get('river', '')
        if r and r not in seen:
            seen.add(r)
            print(f'  {r}: {e.get("grade","?")}({e.get("ehi_score",0)}) - {e.get("species_count",0)} species')
