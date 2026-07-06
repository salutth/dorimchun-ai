import json
import urllib.request
import urllib.error

SUPABASE_URL = 'https://luczuisihsskyhhqgviy.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx1Y3p1aXNpaHNza3loaHFndml5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI5ODEyOTMsImV4cCI6MjA5ODU1NzI5M30.0OUvdrYVWMnwGpE8vq6EeW-cMI9cZ2bw8ShMwrJARuU'

RIVERS_LARGE = ['도림천','안양천','중랑천','탄천','청계천','양재천','홍제천']
RIVERS_MED = ['불광천','우이천','방학천','정릉천','성북천','반포천','여의천']
RIVERS_SMALL = ['묵동천','전농천','월계천','봉원천','녹번천','세곡천','내부천']
ALL_RIVERS = RIVERS_LARGE + RIVERS_MED + RIVERS_SMALL

def make_records(taxon, common, rivers, invasive=False, inat_id=None):
    records = []
    for r in rivers:
        rec = {
            'taxon_name': taxon,
            'common_name': common,
            'river': r,
            'observer': '문헌자료',
            'observed_at': '2026-07-06T00:00:00Z',
            'is_invasive': invasive,
        }
        if inat_id:
            rec['inaturalist_id'] = inat_id
        records.append(rec)
    return records

# ============================================================
# FISH (어류) ~28 new species
# ============================================================
FISH = [
    ('Carassius auratus', '붕어', RIVERS_LARGE + RIVERS_MED[:3], False, 53363),
    ('Pseudorasbora parva', '참붕어', RIVERS_LARGE + ['불광천','우이천'], False, 94781),
    ('Misgurnus anguillicaudatus', '미꾸라지', RIVERS_LARGE + RIVERS_MED[:4], False, 94911),
    ('Silurus asotus', '메기', ['안양천','중랑천','탄천','양재천','도림천'], False, 94738),
    ('Rhynchocypris oxycephalus', '버들치', ['중랑천','탄천','양재천','우이천','방학천'], False, 320839),
    ('Zacco temminkii', '갈겨니', ['안양천','중랑천','탄천','양재천','청계천'], False, 94779),
    ('Pseudogobio esocinus', '모래무지', ['안양천','중랑천','탄천','도림천'], False, 320456),
    ('Pungtungia herzi', '돌고기', ['중랑천','탄천','양재천','우이천'], False, 320523),
    ('Hemibarbus longirostris', '참마자', ['안양천','중랑천','탄천'], False, 320443),
    ('Microphysogobio yaluensis', '돌마자', ['중랑천','탄천','양재천'], False, 320463),
    ('Coreoleuciscus splendidus', '쉬리', ['중랑천','탄천','우이천'], False, 320471),
    ('Coreoperca herzi', '꺽지', ['중랑천','탄천','양재천'], False, 320531),
    ('Odontobutis platycephala', '동사리', ['중랑천','탄천','안양천'], False, 320534),
    ('Rhinogobius brunneus', '밀어', RIVERS_LARGE[:5], False, 94855),
    ('Hemibarbus labeo', '누치', ['안양천','중랑천','탄천','청계천','도림천'], False, 320441),
    ('Acheilognathus lanceolatus', '납자루', ['중랑천','탄천','양재천','안양천'], False, 320407),
    ('Rhodeus uyekii', '각시붕어', ['중랑천','탄천','양재천'], False, 320420),
    ('Acheilognathus yamatsutae', '줄납자루', ['중랑천','탄천'], False, 320411),
    ('Acheilognathus signifer', '묵납자루', ['중랑천','탄천','양재천'], False, 320409),
    ('Acheilognathus gracilis', '가시납지리', ['중랑천','탄천'], False, 320408),
    ('Acheilognathus macropterus', '큰납지리', ['안양천','중랑천','탄천'], False, 320410),
    ('Rhodeus ocellatus', '흰줄납줄개', ['중랑천','탄천','안양천','양재천'], False, 94757),
    ('Siniperca scherzeri', '쏘가리', ['중랑천','탄천'], False, 320530),
    ('Carassius cuvieri', '떡붕어', ['안양천','중랑천','탄천','도림천'], False, 94700),
    ('Squalidus gracilis', '긴몰개', ['중랑천','탄천','안양천'], False, 320488),
    ('Iksookimia koreensis', '참종개', ['중랑천','탄천','양재천'], False, 320502),
    ('Cobitis lutheri', '점줄종개', ['중랑천','탄천'], False, 320504),
    ('Micropterus salmoides', '배스', RIVERS_LARGE + RIVERS_MED[:3], True, 49318),
    ('Lepomis macrochirus', '블루길', RIVERS_LARGE + RIVERS_MED[:3], True, 49326),
]

# ============================================================
# BIRDS (조류) ~38 new species
# ============================================================
BIRDS = [
    ('Egretta garzetta', '쇠백로', RIVERS_LARGE + RIVERS_MED[:4], False, 4956),
    ('Ardea intermedia', '중백로', ['안양천','중랑천','탄천','양재천','여의천'], False, 4948),
    ('Anas poecilorhyncha', '흰뺨검둥오리', RIVERS_LARGE + RIVERS_MED[:3], False, 6930),
    ('Mergus merganser', '비오리', ['안양천','중랑천','탄천','청계천'], False, 6962),
    ('Aix galericulata', '원앙', ['중랑천','청계천','양재천','우이천','방학천'], False, 7104),
    ('Fulica atra', '물닭', ['안양천','중랑천','탄천','양재천'], False, 4721),
    ('Gallinula chloropus', '쇠물닭', ['안양천','중랑천','탄천','양재천','도림천'], False, 4712),
    ('Charadrius placidus', '흰목물떼새', ['안양천','중랑천','탄천','도림천'], False, 145059),
    ('Charadrius dubius', '꼬마물떼새', ['안양천','중랑천','탄천','양재천'], False, 4833),
    ('Motacilla alba', '알락할미새', ALL_RIVERS[:12], False, 13507),
    ('Motacilla cinerea', '노랑할미새', RIVERS_LARGE + RIVERS_MED[:4], False, 13515),
    ('Motacilla alba lugens', '백할미새', RIVERS_LARGE + RIVERS_MED[:3], False, 13507),
    ('Hirundo rustica', '제비', RIVERS_LARGE + RIVERS_MED[:5], False, 14850),
    ('Cecropis daurica', '귀제비', ['안양천','중랑천','탄천','양재천','도림천'], False, 204604),
    ('Aegithalos caudatus', '오목눈이', RIVERS_LARGE + RIVERS_MED[:4], False, 14868),
    ('Zosterops japonicus', '동박새', ['양재천','우이천','방학천','정릉천','봉원천'], False, 13408),
    ('Oriolus chinensis', '꾀꼬리', ['양재천','우이천','방학천','중랑천'], False, 13392),
    ('Falco tinnunculus', '황조롱이', ['안양천','중랑천','탄천','양재천','여의천'], False, 4676),
    ('Buteo buteo', '말똥가리', ['안양천','중랑천','탄천'], False, 5060),
    ('Accipiter gentilis', '참매', ['중랑천','탄천','양재천'], False, 5034),
    ('Accipiter soloensis', '붉은배새매', ['중랑천','양재천','우이천'], False, 5038),
    ('Alcedo atthis', '물총새', RIVERS_LARGE + RIVERS_MED[:5], False, 20572),
    ('Halcyon coromanda', '호반새', ['중랑천','양재천','우이천','방학천'], False, 20584),
    ('Sittiparus varius', '곤줄박이', ['양재천','우이천','방학천','정릉천'], False, 793693),
    ('Acrocephalus orientalis', '개개비', ['안양천','중랑천','탄천','양재천','도림천'], False, 14983),
    ('Paradoxornis webbianus', '붉은머리오목눈이', RIVERS_LARGE + RIVERS_MED[:4], False, 144786),
    ('Luscinia sibilans', '울새', ['양재천','우이천','방학천','봉원천'], False, 10225),
    ('Turdus pallidus', '흰배지빠귀', ['양재천','우이천','방학천','정릉천','중랑천'], False, 12253),
    ('Emberiza elegans', '노랑턱멧새', ['양재천','우이천','방학천','정릉천'], False, 13634),
    ('Chloris sinica', '방울새', RIVERS_LARGE + RIVERS_MED[:3], False, 144850),
    ('Ninox japonica', '솔부엉이', ['양재천','우이천','방학천'], False, 20457),
    ('Cuculus canorus', '뻐꾸기', ['양재천','우이천','방학천','중랑천'], False, 6872),
    ('Eurystomus orientalis', '파랑새', ['양재천','우이천','중랑천'], False, 20569),
    ('Garrulus glandarius', '어치', ['양재천','우이천','방학천','정릉천','봉원천'], False, 12500),
    ('Corvus corone', '까마귀', RIVERS_LARGE + RIVERS_MED[:3], False, 204267),
    ('Dendrocopos kizuki', '쇠딱다구리', ['양재천','우이천','방학천','정릉천','봉원천'], False, 18222),
    ('Dendrocopos major', '오색딱다구리', ['양재천','우이천','방학천','중랑천','봉원천'], False, 18208),
    ('Troglodytes troglodytes', '굴뚝새', ['양재천','우이천','방학천','정릉천'], False, 9087),
]

# ============================================================
# BENTHIC / AQUATIC INVERTEBRATES (저서생물류) ~14종
# ============================================================
BENTHIC = [
    ('Chironomidae', '깔따구', ALL_RIVERS[:14], False, 50608),
    ('Tubifex tubifex', '실지렁이', ALL_RIVERS[:12], False, 60620),
    ('Ephemeroptera', '하루살이', RIVERS_LARGE + RIVERS_MED[:5], False, 47916),
    ('Dugesia japonica', '플라나리아', ['중랑천','탄천','양재천','우이천','청계천'], False, 81833),
    ('Physa acuta', '물달팽이', ALL_RIVERS[:12], False, 50286),
    ('Semisulcospira libertina', '다슬기', ['중랑천','탄천','양재천','우이천','청계천','안양천'], False, 429729),
    ('Plecoptera', '강도래', ['중랑천','탄천','양재천','우이천'], False, 47792),
    ('Trichoptera', '날도래', ['중랑천','탄천','양재천','우이천','청계천'], False, 48011),
    ('Cybister japonicus', '물방개', ['안양천','중랑천','탄천','양재천','도림천'], False, 154802),
    ('Ranatra chinensis', '장구애비', ['안양천','중랑천','도림천','양재천'], False, 250285),
    ('Aquarius paludum', '소금쟁이', ALL_RIVERS[:14], False, 322783),
    ('Appasus japonicus', '물자라', ['안양천','중랑천','탄천','도림천'], False, 368088),
    ('Anax parthenope', '왕잠자리', RIVERS_LARGE + RIVERS_MED[:4], False, 97599),
    ('Ephemera strigata', '개똥하루살이', ['중랑천','탄천','양재천','우이천'], False, 507001),
]

# ============================================================
# REPTILES (파충류) ~5종
# ============================================================
REPTILES = [
    ('Takydromus wolteri', '줄장지뱀', ['양재천','우이천','방학천','중랑천','탄천'], False, 36124),
    ('Scincella vandenburghi', '도마뱀', ['양재천','우이천','방학천','정릉천'], False, 113655),
    ('Rhabdophis tigrinus', '유혈목이', ['양재천','중랑천','탄천','우이천'], False, 29283),
    ('Oocatochus rufodorsatus', '무자치', ['중랑천','탄천','양재천'], False, 567382),
    ('Elaphe dione', '누룩뱀', ['양재천','우이천','방학천'], False, 29197),
]

# ============================================================
# INVASIVE SPECIES (교란종) — additional
# ============================================================
INVASIVE = [
    ('Trachemys scripta elegans', '붉은귀거북', RIVERS_LARGE + RIVERS_MED[:4], True, 39637),
    ('Lithobates catesbeianus', '황소개구리', ['안양천','중랑천','탄천','양재천','도림천','불광천'], True, 65979),
    ('Ambrosia artemisiifolia', '돼지풀', ALL_RIVERS[:14], True, 52873),
    ('Sicyos angulatus', '가시박', RIVERS_LARGE + RIVERS_MED[:4], True, 78613),
    ('Aster pilosus', '미국쑥부쟁이', ALL_RIVERS[:12], True, 56891),
    ('Ambrosia trifida', '단풍잎돼지풀', RIVERS_LARGE + RIVERS_MED[:3], True, 52877),
    ('Solidago altissima', '양미역취', RIVERS_LARGE + RIVERS_MED[:4], True, 56880),
    ('Paspalum distichum', '물참새피', RIVERS_LARGE + ['불광천','우이천'], True, 166181),
]

ALL_SPECIES = FISH + BIRDS + BENTHIC + REPTILES + INVASIVE

all_records = []
for taxon, common, rivers, invasive, inat_id in ALL_SPECIES:
    all_records.extend(make_records(taxon, common, rivers, invasive, inat_id))

print(f"Total new records: {len(all_records)}")
print(f"  Fish: {sum(len(r) for _,_,r,_,_ in FISH)} records ({len(FISH)} species)")
print(f"  Birds: {sum(len(r) for _,_,r,_,_ in BIRDS)} records ({len(BIRDS)} species)")
print(f"  Benthic: {sum(len(r) for _,_,r,_,_ in BENTHIC)} records ({len(BENTHIC)} species)")
print(f"  Reptiles: {sum(len(r) for _,_,r,_,_ in REPTILES)} records ({len(REPTILES)} species)")
print(f"  Invasive: {sum(len(r) for _,_,r,_,_ in INVASIVE)} records ({len(INVASIVE)} species)")

BATCH_SIZE = 50
success = 0
fail = 0

for i in range(0, len(all_records), BATCH_SIZE):
    batch = all_records[i:i+BATCH_SIZE]
    data = json.dumps(batch).encode('utf-8')
    req = urllib.request.Request(
        f'{SUPABASE_URL}/rest/v1/species_observations',
        data=data,
        headers={
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json',
            'Prefer': 'return=minimal',
        },
        method='POST'
    )
    try:
        resp = urllib.request.urlopen(req)
        success += len(batch)
        print(f"  Batch {i//BATCH_SIZE + 1}: {len(batch)} records inserted (total: {success})")
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        fail += len(batch)
        print(f"  Batch {i//BATCH_SIZE + 1}: FAILED ({e.code}) - {body[:200]}")

print(f"\nDone: {success} inserted, {fail} failed")
