"""
GRM U HRIBE — Flask API Strežnik
Zagotavlja REST API za spletno stran.
"""

import os
import json
import hashlib
import secrets
import time
from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_cors import CORS

from recommender import get_recommender

app = Flask(__name__)
CORS(app)

# ─── INICIALIZACIJA ────────────────────────────────────────────
print("Inicializiram GRM U HRIBE strežnik...")
recommender = get_recommender()
print("Strežnik pripravljen ✓")

# ─── UPORABNIKI (server-side) ──────────────────────────────────
# Uporabniška imena, hash gesel in profili shranjeni v users.json.
# Hash: sha256(salt + geslo), salt unikaten za vsakega uporabnika.
USERS_PATH = 'users.json'

def _nalozi_uporabnike():
    if os.path.exists(USERS_PATH):
        try:
            with open(USERS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f) or []
        except Exception:
            return []
    return []

def _shrani_uporabnike(users):
    try:
        with open(USERS_PATH, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"     users.json shranj. napaka: {e}")

def _hash_gesla(geslo, salt):
    """sha256(salt + geslo). Salt mora biti unikaten za vsakega userja."""
    return hashlib.sha256((salt + geslo).encode('utf-8')).hexdigest()


# ─── POMOŽNE FUNKCIJE ──────────────────────────────────────────
def napaka(sporocilo, koda=400):
    return jsonify({'napaka': sporocilo, 'uspeh': False}), koda

def uspeh(podatki):
    return jsonify({'podatki': podatki, 'uspeh': True})

def pridobi_user_id(data=None):
    """
    Identifikacija uporabnika za ocenjevanje. Prednost:
      1) 'user_id' v JSON body (prijavljeni / localStorage client_id)
      2) X-User-Id header
      3) X-Client-Id header
    """
    if data and isinstance(data, dict):
        uid = data.get('user_id') or data.get('client_id')
        if uid:
            return str(uid).strip()
    for h in ('X-User-Id', 'X-Client-Id'):
        v = request.headers.get(h)
        if v:
            return str(v).strip()
    return None


# ─── API ENDPOINTS ─────────────────────────────────────────────

@app.route('/api/priporocila', methods=['POST'])
def priporocila():
    """
    POST /api/priporocila
    Body: {
        tezavnost: 1-8,    # NOVO: 1=brez preference, 2=lahka, 3=lahko brezpotje,
                           # 4=delno zahtevna, 5=zahtevna, 6=zelo zahtevna,
                           # 7=izjemno zahtevna, 8=alpinistični vzpon
        gorovje: string,
        min_visina/max_visina: int,
        min_cas/max_cas: int,
        oznacenost: string,
        izkljuci: [int],    # opcijsko — za re-roll
        user_id: string,    # opcijsko — za prikaz "ali sem že ocenil?"
    }
    Vrne: top 9 priporočenih poti
    """
    data = request.get_json()
    if not data:
        return napaka('Manjkajo podatki profila')

    # Backward kompatibilnost: če pride star profil s fitness/izkusnje, ga pretvorimo
    if 'tezavnost' not in data and 'izkusnje' in data:
        izkusnje = str(data.get('izkusnje', 'srednja'))
        mapping_izk = {'zacetnik': 2, 'srednja': 4, 'zahtevni': 5,
                       'zelo_zahtevno': 6, 'alpinist': 8}
        data['tezavnost'] = mapping_izk.get(izkusnje, 4)

    user_profil = {
        'tezavnost':  int(data.get('tezavnost', 4)),
        'gorovje':    str(data.get('gorovje', 'vse')),
        'min_visina': int(data.get('min_visina', 0)) or 0,
        'max_visina': int(data.get('max_visina', 0)) or None,
        'min_cas':    int(data.get('min_cas', 0)) or 0,
        'max_cas':    int(data.get('max_cas', 0)) or None,
        'oznacenost': str(data.get('oznacenost', 'oznacena')),
        'min_pril':   int(data.get('min_pril', 0)),
        'max_pril':   int(data.get('max_pril', 100)),
    }

    izkljuci = data.get('izkljuci') or []
    try:
        izkljuci = [int(x) for x in izkljuci]
    except (TypeError, ValueError):
        izkljuci = []

    user_id = pridobi_user_id(data)

    try:
        poti = recommender.priporoči(user_profil, n=9, izkljuci=izkljuci, user_id=user_id)
        return uspeh({
            'poti':    poti,
            'profil':  user_profil,
            'skupaj':  len(poti),
            'izkljuceno': len(izkljuci),
        })
    except Exception as e:
        return napaka(f'Napaka pri priporočanju: {str(e)}', 500)


@app.route('/api/priporocila_vrhi', methods=['POST'])
def priporocila_vrhi():
    """
    POST /api/priporocila_vrhi
    Enaki parametri kot /api/priporocila.
    Vrne priporočene poti grupirane po vrhu, z vsemi potmi (ne samo 9).
    Vsak vrh ima: vrh, gorovje, best_score, st_poti, poti[]
    """
    data = request.get_json()
    if not data:
        return napaka('Manjkajo podatki profila')

    if 'tezavnost' not in data and 'izkusnje' in data:
        izkusnje = str(data.get('izkusnje', 'srednja'))
        mapping_izk = {'zacetnik': 2, 'srednja': 4, 'zahtevni': 5,
                       'zelo_zahtevno': 6, 'alpinist': 8}
        data['tezavnost'] = mapping_izk.get(izkusnje, 4)

    user_profil = {
        'tezavnost':  int(data.get('tezavnost', 4)),
        'gorovje':    str(data.get('gorovje', 'vse')),
        'min_visina': int(data.get('min_visina', 0)) or 0,
        'max_visina': int(data.get('max_visina', 0)) or None,
        'min_cas':    int(data.get('min_cas', 0)) or 0,
        'max_cas':    int(data.get('max_cas', 0)) or None,
        'oznacenost': str(data.get('oznacenost', 'oznacena')),
        'min_pril':   int(data.get('min_pril', 0)),
        'max_pril':   int(data.get('max_pril', 100)),
    }

    user_id = pridobi_user_id(data)

    try:
        # n=99999 = vse ujemajoče poti (hard filtri omejijo naravno)
        # Light verzija (brez opisov) je ~5MB za vse poti — sprejemljivo
        vse_poti = recommender.priporoči(user_profil, n=99999, izkljuci=[], user_id=user_id)
        skupaj_poti_najdenih = len(vse_poti)

        # Grupiramo po vrhu
        vrhi_dict = {}
        for pot in vse_poti:
            vrh = pot['vrh']
            if vrh not in vrhi_dict:
                vrhi_dict[vrh] = {
                    'vrh':        vrh,
                    'gorovje':    pot['gorovje'],
                    'best_score': pot.get('score', 0),
                    'st_poti':    0,
                    'visina_m':   pot.get('visina_m', 0),
                    '_pril_sum':  0,
                    '_pril_n':    0,
                    'min_cas':    pot.get('cas_min', 0),
                    'max_cas':    pot.get('cas_min', 0),
                    '_tezavnosti': set(),
                    'poti':       []
                }
            v = vrhi_dict[vrh]
            v['poti'].append(pot)
            v['st_poti'] += 1
            if pot.get('score', 0) > v['best_score']:
                v['best_score'] = pot['score']
            if pot.get('visina_m', 0) > v['visina_m']:
                v['visina_m'] = pot['visina_m']
            v['_pril_sum'] += pot.get('priljubljenost', 0)
            v['_pril_n']   += 1
            cas = pot.get('cas_min', 0)
            if cas > 0:
                if v['min_cas'] == 0 or cas < v['min_cas']:
                    v['min_cas'] = cas
                if cas > v['max_cas']:
                    v['max_cas'] = cas
            t = pot.get('tezavnost')
            if t:
                v['_tezavnosti'].add(t)

        # Razvrsti vrhe po best_score desc
        vrhi_seznam = sorted(vrhi_dict.values(), key=lambda v: v['best_score'], reverse=True)
        skupaj_najdeno = len(vrhi_seznam)

        # Normaliziraj score PRED paginacijo (da je top=100% konsistenten)
        if vrhi_seznam:
            max_score = max(v['best_score'] for v in vrhi_seznam) or 1
            for v in vrhi_seznam:
                v['raw_score'] = v['best_score']
                v['best_score'] = round(v['best_score'] / max_score * 100)

        # Paginacija: vrni PAGE_SIZE vrhov od offset naprej
        PAGE_SIZE = 50
        offset = int(data.get('offset', 0))
        stran = vrhi_seznam[offset:offset + PAGE_SIZE]

        # Znotraj vsake strani razvrsti poti + izračun stats
        for v in stran:
            v['poti'].sort(key=lambda p: p.get('score', 0), reverse=True)
            v['priljubljenost'] = round(v['_pril_sum'] / v['_pril_n']) if v['_pril_n'] > 0 else 0
            v['tezavnosti'] = sorted(v.pop('_tezavnosti'))
            del v['_pril_sum'], v['_pril_n']

        je_zadnja = (offset + PAGE_SIZE) >= skupaj_najdeno

        return uspeh({
            'vrhi':            stran,
            'skupaj_vrhov':    len(stran),
            'skupaj_najdenih': skupaj_najdeno,
            'offset':          offset,
            'page_size':       PAGE_SIZE,
            'je_zadnja':       je_zadnja,
            'skupaj_poti':     skupaj_poti_najdenih,
            'profil':          user_profil,
        })
    except Exception as e:
        return napaka(f'Napaka pri priporočanju vrhov: {str(e)}', 500)


@app.route('/api/ocena', methods=['POST'])
def ocena():
    """
    POST /api/ocena
    Body: { pot_id: int, ocena: 1-5, user_id: string }

    Vsak uporabnik lahko pot oceni le ENKRAT. user_id je obvezen.
    Če je user_id že oddal oceno za to pot, vrne 409 Conflict.
    """
    data = request.get_json() or {}
    try:
        pot_id = int(data.get('pot_id'))
        ocena  = float(data.get('ocena'))
    except (TypeError, ValueError):
        return napaka('Manjkata pot_id in ocena')

    if not (1 <= ocena <= 5):
        return napaka('Ocena mora biti med 1 in 5')

    user_id = pridobi_user_id(data)
    if not user_id:
        return napaka('user_id je obvezen', 400)

    # profil je opcijski — če obstaja, ga recommender zapomni za CF sosede
    profil = data.get('profil')
    if isinstance(profil, dict):
        if 'tezavnost' not in profil and 'izkusnje' in profil:
            izk = str(profil.get('izkusnje', 'srednja'))
            mapping_izk = {'zacetnik': 2, 'srednja': 4, 'zahtevni': 5,
                           'zelo_zahtevno': 6, 'alpinist': 8}
            profil['tezavnost'] = mapping_izk.get(izk, 4)
        profil = {
            'tezavnost':  int(profil.get('tezavnost', 4)),
            'gorovje':    str(profil.get('gorovje', 'vse')),
            'oznacenost': str(profil.get('oznacenost', 'oznacena')),
            'min_visina': int(profil.get('min_visina') or 0),
            'max_visina': int(profil.get('max_visina') or 0),
            'min_cas':    int(profil.get('min_cas') or 0),
            'max_cas':    int(profil.get('max_cas') or 0),
        }
    else:
        profil = None

    try:
        res = recommender.oceni_pot(pot_id, ocena, user_id=user_id, profil=profil)
        return uspeh(res)
    except PermissionError as e:
        prejsnja = recommender.je_ze_ocenil(pot_id, user_id)
        return jsonify({
            'napaka': str(e),
            'uspeh':  False,
            'ze_ocenjeno': True,
            'moja_ocena': prejsnja,
        }), 409
    except ValueError as e:
        return napaka(str(e), 400)
    except Exception as e:
        return napaka(f'Napaka pri shranjevanju ocene: {str(e)}', 500)


@app.route('/api/ocena_ustreznosti', methods=['POST'])
def ocena_ustreznosti():
    """
    POST /api/ocena_ustreznosti
    Body: {
        pot_id: int,
        ocena: 1-5,                # kako ustrezen je bil PREDLOG glede na profil
        profil: { fitness, izkusnje, oznacenost, gorovje },  # isti kot pri /api/priporocila
        user_id: string,
    }

    To je feedback na KVALITETO PRIPOROČILA (ne na pot samo po sebi).
    Vpliva na prihodnja priporočila za IST profil (±10%).
    """
    data = request.get_json() or {}
    try:
        pot_id = int(data.get('pot_id'))
        ocena  = float(data.get('ocena'))
    except (TypeError, ValueError):
        return napaka('Manjkata pot_id in ocena')

    if not (1 <= ocena <= 5):
        return napaka('Ocena mora biti med 1 in 5')

    profil = data.get('profil')
    if not isinstance(profil, dict):
        return napaka('Manjka profil', 400)

    # Normalizacija profila (backward kompat: če pride star fitness/izkusnje, ga pretvorimo)
    if 'tezavnost' not in profil and 'izkusnje' in profil:
        izkusnje = str(profil.get('izkusnje', 'srednja'))
        mapping_izk = {'zacetnik': 2, 'srednja': 4, 'zahtevni': 5,
                       'zelo_zahtevno': 6, 'alpinist': 8}
        profil['tezavnost'] = mapping_izk.get(izkusnje, 4)
    norm_profil = {
        'tezavnost':  int(profil.get('tezavnost', 4)),
        'gorovje':    str(profil.get('gorovje', 'vse')),
        'oznacenost': str(profil.get('oznacenost', 'oznacena')),
    }

    user_id = pridobi_user_id(data)
    if not user_id:
        return napaka('user_id je obvezen', 400)

    try:
        res = recommender.oceni_ustreznost(norm_profil, pot_id, ocena, user_id=user_id)
        return uspeh(res)
    except PermissionError as e:
        prejsnja = recommender.je_ze_ocenil_ustreznost(norm_profil, pot_id, user_id)
        return jsonify({
            'napaka': str(e),
            'uspeh':  False,
            'ze_ocenjeno': True,
            'moja_ocena': prejsnja,
        }), 409
    except ValueError as e:
        return napaka(str(e), 400)
    except Exception as e:
        return napaka(f'Napaka pri shranjevanju ocene: {str(e)}', 500)


@app.route('/api/iskanje', methods=['GET'])
def iskanje():
    query = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 20)), 50)

    if len(query) < 2:
        return napaka('Iskalni niz mora imeti vsaj 2 znaka')

    user_id = pridobi_user_id()

    try:
        poti = recommender.isci(query, limit=limit, user_id=user_id)
        return uspeh({'poti': poti, 'skupaj': len(poti), 'query': query})
    except Exception as e:
        return napaka(f'Napaka pri iskanju: {str(e)}', 500)


@app.route('/api/pot/<int:pot_id>', methods=['GET'])
def pot_detail(pot_id):
    user_id = pridobi_user_id()
    # opcijsko: profil v query params (za prikaz "moja ocena ustreznosti" na kartici)
    profil = None
    # Nov format: tezavnost (1-8). Star format (backward compat): fitness + izkusnje
    if request.args.get('tezavnost'):
        try:
            profil = {
                'tezavnost':  int(request.args.get('tezavnost', 4)),
                'gorovje':    str(request.args.get('gorovje', 'vse')),
                'oznacenost': str(request.args.get('oznacenost', 'oznacena')),
            }
        except (ValueError, TypeError):
            profil = None
    elif request.args.get('fitness') or request.args.get('izkusnje'):
        # Backward compat
        izk = str(request.args.get('izkusnje', 'srednja'))
        mapping = {'zacetnik': 2, 'srednja': 4, 'zahtevni': 5,
                   'zelo_zahtevno': 6, 'alpinist': 8}
        profil = {
            'tezavnost':  mapping.get(izk, 4),
            'gorovje':    str(request.args.get('gorovje', 'vse')),
            'oznacenost': str(request.args.get('oznacenost', 'oznacena')),
        }
    try:
        pot = recommender.get_pot(pot_id, user_id=user_id, profil=profil)
        if not pot:
            return napaka('Pot ni bila najdena', 404)
        return uspeh({'pot': pot})
    except Exception as e:
        return napaka(f'Napaka: {str(e)}', 500)


@app.route('/api/statistike', methods=['GET'])
def statistike():
    try:
        stats = recommender.statistike()
        return uspeh({'statistike': stats})
    except Exception as e:
        return napaka(f'Napaka: {str(e)}', 500)


@app.route('/api/filtri', methods=['GET'])
def filtri():
    df = recommender.df
    return uspeh({
        'gorovja': sorted(df['Gorovje'].dropna().unique().tolist()),
        'zahtevnosti': [
            {'vrednost': 2, 'label': 'Lahka'},
            {'vrednost': 4, 'label': 'Delno zahtevna'},
            {'vrednost': 5, 'label': 'Zahtevna'},
            {'vrednost': 6, 'label': 'Zelo zahtevna'},
            {'vrednost': 7, 'label': 'Izjemno zahtevna'},
        ],
        'oznacenosti': [
            {'vrednost': 'oznacena',  'label': 'Označena pot'},
            {'vrednost': 'mesano',    'label': 'Delno označena'},
            {'vrednost': 'brezpotje', 'label': 'Brezpotje'},
        ],
        'izkusnje': [
            {'vrednost': 'zacetnik',       'label': 'Začetnik'},
            {'vrednost': 'srednja',        'label': 'Srednji'},
            {'vrednost': 'zahtevni',       'label': 'Zahtevni'},
            {'vrednost': 'zelo_zahtevno',  'label': 'Zelo zahtevno'},
        ]
    })


@app.route('/api/uporabnik', methods=['GET'])
def uporabnik_self():
    """
    GET /api/uporabnik
    Vrne podatke o trenutnem uporabniku (preko X-User-Id headerja):
      - njegov profil
      - vse njegove ocene poti
      - vse njegove ocene ustreznosti
      - 10 najbližjih CF sosedov
    """
    user_id = pridobi_user_id()
    if not user_id:
        return napaka('user_id manjka — pošlji X-User-Id header', 400)
    try:
        return uspeh(recommender.podatki_uporabnika(user_id))
    except Exception as e:
        return napaka(f'Napaka: {str(e)}', 500)


@app.route('/api/registracija', methods=['POST'])
def registracija():
    """
    POST /api/registracija
    Body: { ime, uporabnik, geslo, avatar?, profil?: {...} }
    Vrne: { id, ime, uporabnik, avatar, profil }
    """
    import re
    data = request.get_json() or {}
    ime       = str(data.get('ime', '')).strip()
    uporabnik = str(data.get('uporabnik', '')).strip().lower()
    geslo     = str(data.get('geslo', ''))
    avatar    = str(data.get('avatar', ''))
    profil    = data.get('profil')

    if not ime or not uporabnik or len(geslo) < 8:
        return napaka('Izpolni ime, uporabniško ime in geslo (min. 8 znakov)', 400)
    if len(uporabnik) < 3:
        return napaka('Uporabniško ime mora imeti vsaj 3 znake', 400)
    if not re.match(r'^[a-z0-9_.-]+$', uporabnik):
        return napaka('Uporabniško ime sme vsebovati samo črke, števke, _ in -', 400)

    users = _nalozi_uporabnike()
    if any(u.get('uporabnik') == uporabnik for u in users):
        return napaka('To uporabniško ime že obstaja, izberi drugo', 409)

    salt = secrets.token_hex(16)
    new_id = int(time.time() * 1000)  # millis
    user = {
        'id':            new_id,
        'ime':           ime,
        'uporabnik':     uporabnik,
        'avatar':        avatar,
        'salt':          salt,
        'passwordHash':  _hash_gesla(geslo, salt),
        'profil':        profil if isinstance(profil, dict) else None,
        'createdAt':     int(time.time()),
    }
    users.append(user)
    _shrani_uporabnike(users)

    # Tudi v CF user_profili shranimo, da se profil takoj uporabi za sosede
    if isinstance(profil, dict):
        try:
            recommender._shrani_user_profile(f'user-{new_id}', profil)
        except Exception:
            pass

    # Vrni javno različico (brez hash-a in salt-a!)
    return uspeh({
        'id':        new_id,
        'ime':       ime,
        'uporabnik': uporabnik,
        'avatar':    avatar,
        'profil':    profil,
    })


@app.route('/api/prijava', methods=['POST'])
def prijava():
    """
    POST /api/prijava
    Body: { uporabnik, geslo }
    Vrne: { id, ime, uporabnik, avatar, profil }
    """
    data = request.get_json() or {}
    uporabnik = str(data.get('uporabnik', '')).strip().lower()
    geslo     = str(data.get('geslo', ''))

    if not uporabnik or not geslo:
        return napaka('Uporabniško ime in geslo sta obvezna', 400)

    users = _nalozi_uporabnike()
    user = next((u for u in users if u.get('uporabnik') == uporabnik), None)
    if not user:
        return napaka('Napačno uporabniško ime ali geslo', 401)

    if _hash_gesla(geslo, user['salt']) != user['passwordHash']:
        return napaka('Napačno uporabniško ime ali geslo', 401)

    return uspeh({
        'id':        user['id'],
        'ime':       user['ime'],
        'uporabnik': user['uporabnik'],
        'avatar':    user['avatar'],
        'profil':    user.get('profil'),
    })


@app.route('/api/cf_demo', methods=['GET'])
def cf_demo():
    """
    GET /api/cf_demo?scenarij=zacetnik|alpinist|primerjava

    Demonstrira, da CF dela: ustvari sintetične uporabnike, ki ocenjujejo poti,
    in pokaže priporočila za nove uporabnike z različnima profiloma.
    Rezultati se NE shranjujejo (ne posegamo v feedback.json).

    Vrnitev:
      - scenarij: kaj smo testirali
      - lahke_poti: 5 lahkih poti, ki jih "ocenijo" simulirani začetniki
      - zahtevne_poti: 5 zahtevnih, ki jih "ocenijo" alpinisti
      - novec_zacetnik: priporočila za novega začetnika (mora vrniti pretežno lahke)
      - novec_alpinist: priporočila za novega alpinista (mora vrniti pretežno zahtevne)
      - rezultat: ovrednotenje, ali CF dela
    """
    import copy
    # Ohranimo trenutno stanje feedbacka in user_profilov
    backup_fb     = copy.deepcopy(recommender.feedback)
    backup_prof   = copy.deepcopy(recommender.user_profili)

    try:
        # Rebuild "čisto stanje" za demo
        recommender.feedback     = {}
        recommender.user_profili = {}

        df = recommender.df
        lahke = df[(df['Visina_m'] < 400) & (df['Cas_min'] < 120)
                   & (df['Tezavnost_num'] == 2) & (df['Oznacenost'] == 'oznacena')]\
                  .nlargest(5, 'Priljubljenost')
        zahtevne = df[(df['Visina_m'] > 1500) & (df['Cas_min'] > 300)
                      & (df['Tezavnost_num'] >= 5)
                      & (df['Oznacenost'].isin(['oznacena','mesano']))]\
                     .nlargest(5, 'Priljubljenost')

        profil_zac = {'tezavnost': 2, 'oznacenost': 'oznacena', 'gorovje': 'vse'}
        profil_alp = {'tezavnost': 6, 'oznacenost': 'mesano',   'gorovje': 'vse'}

        # 8 začetnikov oceni vse lahke poti s 5★
        for i in range(8):
            uid = f"user-demo-zacetnik-{i}"
            for _, pot in lahke.iterrows():
                try:
                    recommender.oceni_pot(int(pot['id']), 5, user_id=uid, profil=profil_zac)
                except PermissionError:
                    pass
        # 8 alpinistov oceni vse zahtevne poti s 5★
        for i in range(8):
            uid = f"user-demo-alpinist-{i}"
            for _, pot in zahtevne.iterrows():
                try:
                    recommender.oceni_pot(int(pot['id']), 5, user_id=uid, profil=profil_alp)
                except PermissionError:
                    pass

        # Priporočila za novega
        priporocila_zac = recommender.priporoči(profil_zac, n=7, user_id='demo-novec-zacetnik')
        priporocila_alp = recommender.priporoči(profil_alp, n=7, user_id='demo-novec-alpinist')

        lahke_ids    = set(int(p) for p in lahke['id'])
        zahtevne_ids = set(int(p) for p in zahtevne['id'])

        ujemanje_zac = sum(1 for p in priporocila_zac if p['id'] in lahke_ids)
        ujemanje_alp = sum(1 for p in priporocila_alp if p['id'] in zahtevne_ids)

        cf_dela = ujemanje_zac >= 3 and ujemanje_alp >= 3

        return uspeh({
            'razlaga': (
                "Test pokaže, da Collaborative Filtering deluje pravilno. "
                "Ustvarili smo 8 'simuliranih začetnikov' (fitness=1) in 8 'simuliranih alpinistov' "
                "(fitness=5). Vsaka skupina je z 5★ ocenila svojih 5 značilnih poti. "
                "Nato smo vprašali AI za priporočila za dva NOVA uporabnika: enega z začetniškim profilom "
                "in drugega z alpinističnim. Če AI dela, mora začetnik dobiti pretežno lahke poti "
                "(ki so jih ocenili sosedje-začetniki), alpinist pa zahtevne."
            ),
            'lahke_poti': [{'id': int(r['id']), 'pot': str(r['Pot']), 'visina_m': int(r['Visina_m']),
                           'cas_min': int(r['Cas_min']), 'tezavnost_num': int(r['Tezavnost_num'])}
                          for _, r in lahke.iterrows()],
            'zahtevne_poti': [{'id': int(r['id']), 'pot': str(r['Pot']), 'visina_m': int(r['Visina_m']),
                              'cas_min': int(r['Cas_min']), 'tezavnost_num': int(r['Tezavnost_num'])}
                             for _, r in zahtevne.iterrows()],
            'novec_zacetnik': {
                'profil': profil_zac,
                'priporocila': [{'id': p['id'], 'pot': p['pot'], 'visina_m': p['visina_m'],
                                'cas_min': p['cas_min'], 'tezavnost_num': p['tezavnost_num'],
                                'score': p['score'], 'iz_lahkih': p['id'] in lahke_ids,
                                'cf_aktiven': bool(p.get('cf_info',{}).get('aktiven'))}
                               for p in priporocila_zac],
                'ujemanje_z_lahkimi': f"{ujemanje_zac}/{len(priporocila_zac)}",
            },
            'novec_alpinist': {
                'profil': profil_alp,
                'priporocila': [{'id': p['id'], 'pot': p['pot'], 'visina_m': p['visina_m'],
                                'cas_min': p['cas_min'], 'tezavnost_num': p['tezavnost_num'],
                                'score': p['score'], 'iz_zahtevnih': p['id'] in zahtevne_ids,
                                'cf_aktiven': bool(p.get('cf_info',{}).get('aktiven'))}
                               for p in priporocila_alp],
                'ujemanje_z_zahtevnimi': f"{ujemanje_alp}/{len(priporocila_alp)}",
            },
            'rezultat': {
                'cf_dela': cf_dela,
                'sporocilo': (
                    " AI deluje pravilno: vrnil je razlikovana priporočila za različne profile."
                    if cf_dela else
                    " Rezultat dvomljiv: priporočila niso jasno razdeljena."
                ),
            }
        })
    finally:
        # OBNOVI prvotno stanje (kritično — sicer demo užge produkcijske podatke)
        recommender.feedback     = backup_fb
        recommender.user_profili = backup_prof
        try:
            recommender._shrani_feedback()
            recommender._shrani_json('user_profili.json', backup_prof)
        except Exception:
            pass


ADMIN_GESLO = 'grm2026'  # spremeni to v produkciji!

@app.route('/api/admin/uporabniki', methods=['POST'])
def admin_uporabniki():
    """
    POST /api/admin/uporabniki
    Body: { admin_geslo: "..." }
    Vrne seznam vseh registriranih uporabnikov (brez hash-ov!).

    Za debug in pregled — kdor pozna admin geslo, vidi kdo se je registriral.
    """
    data = request.get_json() or {}
    if str(data.get('admin_geslo', '')) != ADMIN_GESLO:
        return napaka('Napačno admin geslo', 401)

    users = _nalozi_uporabnike()
    # Vrni samo varne podatke (brez salt-a in hash-a)
    return uspeh({
        'st_uporabnikov': len(users),
        'uporabniki': [
            {
                'id':         u.get('id'),
                'ime':        u.get('ime'),
                'uporabnik':  u.get('uporabnik'),
                'avatar':     u.get('avatar'),
                'profil':     u.get('profil'),
                'createdAt':  u.get('createdAt'),
                'ima_geslo':  bool(u.get('passwordHash')),  # potrjuje da ima hash, ne razkrije
            }
            for u in users
        ],
    })


@app.route('/api/zdravje', methods=['GET'])
def zdravje():
    return uspeh({
        'status': 'OK',
        'model':  'User-based Collaborative Filtering (evklidska razdalja)',
        'poti':   len(recommender.df) if recommender.df is not None else 0,
        'uporabnikov':    len(recommender.user_profili),
        'feedback_poti':  len(recommender.feedback),
        'ustreznost':     len(recommender.ustreznost),
    })


# ─── SPLETNA STRAN ─────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


if __name__ == '__main__':
    print("\n  GRM U HRIBE API strežnik")
    print("   URL: http://localhost:5000")
    print("   API: http://localhost:5000/api/zdravje\n")
    app.run(debug=False, host='0.0.0.0', port=5000)
