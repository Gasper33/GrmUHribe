"""
GRM U HRIBE — User-based Collaborative Filtering

AI del aplikacije: priporočila temeljijo na USER-BASED COLLABORATIVE FILTERING.
Algoritem je namerno enostaven (brez matričnih razcepov, brez sklearn):

  1. Vsak uporabnik ima profil (fitness, izkušnje, označenost, regija).
  2. Uporabniki ocenjujejo poti (1-5★).
  3. Ko priporočamo, NAJPREJ najdemo K uporabnikov z najbolj podobnim profilom:
     uporabimo EVKLIDSKO RAZDALJO med numeričnimi značilkami.
     Zavržemo sosede z razdaljo > 1.0 (preveč drugačen profil).
  4. Ocena vsake poti = tehtano povprečje ocen teh sosedov, kjer je
     utež = exp(-3 · razdalja). To pomeni, da BLIŽNJI sosedje eksponentno
     več vplivajo, daljni pa skoraj nič.
  5. Če je sosedov premalo (cold start, < 3), dopolnimo s priljubljenostjo
     + rahli fit bonus za idealno višino glede na fitness.
  6. Trdi filtri (max višina / čas / označenost) se uporabijo na množico poti
     PRED CF rangiranjem, kar je hitreje in enostavneje.

Za razliko od prejšnje hevristike (ročne uteži + ignoriran Random Forest),
tukaj dejansko odgovarjamo na vprašanje: "kaj so ljudje s podobnim profilom
imeli radi?"
"""

import os
import re
import json
import math
import pandas as pd
import warnings
warnings.filterwarnings('ignore')


# ─── KONSTANTE ────────────────────────────────────────────────
EXCEL_CANDIDATES = [
    'grm_u_hribe_baza_podatkov.xlsx',
    'grm_u_hribe_ORANGE.xlsx',
]
FEEDBACK_PATH            = 'feedback.json'
FEEDBACK_USTREZNOST_PATH = 'feedback_ustreznost.json'
USER_PROFIL_PATH         = 'user_profili.json'   # NOVO: profili uporabnikov

# CF parametri
K_SOSEDOV      = 20     # kolikor najbližjih sosedov upoštevamo
MIN_SOSEDOV_CF = 3      # manj kot toliko -> cold start (fallback)

# Konvencija za user_id:
#   "user-<id>"  → prijavljen registriran uporabnik (lahko ocenjuje, šteje za CF)
#   "anon-<uid>" → gost (NE more ocenjevati, dobi priporočila iz CF prijavljenih)
def je_prijavljen(user_id):
    return bool(user_id) and str(user_id).startswith('user-')

# Kodiranje diskretnih vrednosti v numerične za evklidsko razdaljo
IZKUSNJE_KODA = {
    'zacetnik':       1,
    'srednja':        2,
    'zahtevni':       3,
    'zelo_zahtevno':  4,
    'alpinist':       4,   # vzvratna združljivost
}
OZNACENOST_KODA = {
    'oznacena':  1,   # najbolj "varno"
    'mesano':    2,
    'brezpotje': 3,   # najbolj "divje"
}


class GrmUHribeRecommender:
    """
    User-based CF priporočilni sistem.
    """

    def __init__(self):
        self.df = None
        self._naložen = False
        self.feedback    = self._nalozi_json(FEEDBACK_PATH, {})
        self.ustreznost  = self._nalozi_json(FEEDBACK_USTREZNOST_PATH, {})
        self.user_profili = self._nalozi_json(USER_PROFIL_PATH, {})

    # ─── GENERIČNA JSON PERSISTENCA ───────────────────────────
    @staticmethod
    def _nalozi_json(path, privzeto):
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f) or privzeto
            except Exception as e:
                print(f"     {path} nalog. napaka: {e}")
        return privzeto

    @staticmethod
    def _shrani_json(path, data):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"     {path} shranj. napaka: {e}")

    def _shrani_feedback(self):
        self._shrani_json(FEEDBACK_PATH, {str(k): v for k, v in self.feedback.items()})

    def _shrani_ustreznost(self):
        self._shrani_json(FEEDBACK_USTREZNOST_PATH, self.ustreznost)

    def _shrani_user_profile(self, user_id, profil):
        """Zapomni si zadnji znan profil za tega uporabnika.
        SAMO za prijavljene — gostov profile ne shranjujemo (so prehodnih)."""
        if not je_prijavljen(user_id):
            return
        self.user_profili[str(user_id)] = self._normaliziraj_profil(profil)
        self._shrani_json(USER_PROFIL_PATH, self.user_profili)

    # ─── NORMALIZACIJA IN VEKTORIZACIJA PROFILA ───────────────
    @staticmethod
    def _normaliziraj_profil(profil):
        """
        Profil ima zdaj samo 'tezavnost' (1-8) namesto ločenih fitness + izkusnje.

        Backward kompat: če pride star profil s 'fitness' ali 'izkusnje',
        ga mappiram na težavnost.
        """
        # Zaznaj nove vs. stare profile
        if 'tezavnost' in profil:
            tez = int(profil.get('tezavnost', 3))
        else:
            # Mapping iz starega profila (fitness 1-5, izkusnje začetnik..zelo_zahtevno)
            izk = str(profil.get('izkusnje', 'srednja'))
            mapping_izk = {'zacetnik': 2, 'srednja': 4, 'zahtevni': 5, 'zelo_zahtevno': 6, 'alpinist': 8}
            tez = mapping_izk.get(izk, 4)

        # Omeji v range 1-8
        tez = max(1, min(8, tez))

        return {
            'tezavnost':  tez,
            'oznacenost': str(profil.get('oznacenost', 'oznacena')),
            'gorovje':    str(profil.get('gorovje', 'vse')).strip() or 'vse',
            'min_visina': int(profil.get('min_visina') or 0),
            'max_visina': int(profil.get('max_visina') or 0),
            'min_cas':    int(profil.get('min_cas') or 0),
            'max_cas':    int(profil.get('max_cas') or 0),
            'min_pril':   int(profil.get('min_pril') or 0),
            'max_pril':   int(profil.get('max_pril') or 100),
        }

    @staticmethod
    def _profil_v_vektor(p):
        """
        Pretvori profil v numerični vektor za evklidsko razdaljo.
        Vse komponente so normalizirane na [0, 1], da nobena preveč ne dominira.

        Komponente (4D):
          [0] težavnost   1..8     -> 0..1
          [1] označenost  1..3     -> 0..1
          [2] max višina  0..2500  -> 0..1
          [3] max čas     0..720   -> 0..1
        Regija (gorovje) NI v vektorju — preveč je diskretna.
        """
        p = GrmUHribeRecommender._normaliziraj_profil(p)
        max_vis = min(p['max_visina'], 2500) if p['max_visina'] > 0 else 2500
        max_cas = min(p['max_cas'], 720)     if p['max_cas']    > 0 else 720
        return [
            (p['tezavnost'] - 1) / 7.0,
            (OZNACENOST_KODA.get(p['oznacenost'], 1) - 1) / 2.0,
            max_vis / 2500.0,
            max_cas / 720.0,
        ]

    @staticmethod
    def _evklidska_razdalja(v1, v2):
        """Klasična evklidska razdalja, ročno (brez numpy/sklearn)."""
        s = 0.0
        for a, b in zip(v1, v2):
            s += (a - b) ** 2
        return math.sqrt(s)

    # ─── NAJDI K-NAJBLIŽJIH SOSEDOV ───────────────────────────
    def _najdi_sosede(self, profil, k=K_SOSEDOV, max_razdalja=1.0):
        """
        Vrne seznam [(user_id, razdalja, utež), ...] najbližjih uporabnikov.

        Utež uporablja EKSPONENTNO PADANJE: w = exp(-3 * razdalja)
        S tem daleč sosedje skoraj ne vplivajo (pri d=1.0 je w≈0.05,
        pri d=0 pa w=1.0). To je ključno: začetniku se priporočila tvorijo
        pretežno iz ocen DRUGIH ZAČETNIKOV, ne alpinistov.

        Zavrnemo tudi sosede z razdaljo > max_razdalja (privzeto 1.0 — to je
        približno razlika "fitness 1 vs fitness 5").

        Bonus: če ima sosed isto regijo kot vprašanec, razdaljo zmanjšamo za 0.2.
        """
        v_ja = self._profil_v_vektor(profil)
        moja_regija = self._normaliziraj_profil(profil)['gorovje']

        razdalje = []
        for uid, p_drugi in self.user_profili.items():
            # KRITIČNO: CF temelji SAMO na prijavljenih uporabnikih.
            # Gosti (anon-*) ne morejo ocenjevati, torej ne smejo biti sosedje.
            if not je_prijavljen(uid):
                continue
            v_drug = self._profil_v_vektor(p_drugi)
            d = self._evklidska_razdalja(v_ja, v_drug)
            if p_drugi.get('gorovje') == moja_regija and moja_regija != 'vse':
                d = max(0, d - 0.2)
            if d > max_razdalja:
                continue
            razdalje.append((uid, d))

        razdalje.sort(key=lambda x: x[1])
        top = razdalje[:k]
        # Eksponentno padajoča utež: bližje = eksponentno več teže
        return [(uid, d, math.exp(-3.0 * d)) for uid, d in top]

    # ─── GLAVNA CF METODA: SCORE ZA POT ───────────────────────
    def _cf_score_poti(self, pot_id, sosedje, profil=None):
        """
        Tehtana ocena poti med sosedi — združi dve vrsti ocen:
          - feedback (splošna ocena poti, 60% teže)
          - ustreznost (ali je bila pot ustrezna za ta profil, 40% teže)

        Če ima pot samo eno vrsto ocene, uporabi samo to.
        Če nobena ni na voljo, vrne (None, 0).
        Score normaliziran na [0, 1]: 1 = vsi sosedje dali 5★.
        """
        def _izracunaj(ratings_dict):
            """Tehtano povprečje ocen sosedov iz danega slovarja."""
            stevec = 0.0; imenovalec = 0.0; n = 0
            for uid, _d, utez in sosedje:
                if uid in ratings_dict:
                    stevec    += utez * float(ratings_dict[uid])
                    imenovalec += utez
                    n += 1
            if imenovalec == 0:
                return None, 0
            return (stevec / imenovalec - 1.0) / 4.0, n  # norm 0..1

        # 1) Splošna ocena poti
        rec_fb = self.feedback.get(int(pot_id)) or self.feedback.get(str(pot_id))
        fb_score, fb_n = _izracunaj(rec_fb['ratings']) if rec_fb and rec_fb.get('ratings') else (None, 0)

        # 2) Ocena ustreznosti (per-profil)
        ust_score, ust_n = None, 0
        if profil is not None:
            pkey = self._profil_key(profil)
            rec_ust = self.ustreznost.get(pkey, {}).get(str(int(pot_id)))
            if rec_ust and rec_ust.get('ratings'):
                ust_score, ust_n = _izracunaj(rec_ust['ratings'])

        # 3) Združi — tehtano povprečje (60% feedback, 40% ustreznost)
        if fb_score is not None and ust_score is not None:
            score = 0.60 * fb_score + 0.40 * ust_score
            n = max(fb_n, ust_n)
        elif fb_score is not None:
            score = fb_score
            n = fb_n
        elif ust_score is not None:
            score = ust_score
            n = ust_n
        else:
            return None, 0

        return score, n

    # ─── FEEDBACK METODE (isto kot prej) ──────────────────────
    def oceni_pot(self, pot_id, ocena, user_id=None, profil=None):
        """
        Oddaj oceno poti. Vsak uporabnik lahko pot oceni le ENKRAT.
        SAMO PRIJAVLJENI lahko ocenjujejo (user_id mora začeti z 'user-').
        Če je profil podan, si ga tudi zapomnimo za CF.
        """
        try:
            pot_id = int(pot_id); ocena = float(ocena)
        except (TypeError, ValueError):
            raise ValueError("pot_id mora biti int, ocena število")
        if not (1 <= ocena <= 5):
            raise ValueError("Ocena mora biti med 1 in 5")
        if not user_id:
            raise ValueError("user_id je obvezen")
        if not je_prijavljen(user_id):
            raise PermissionError(
                "Za ocenjevanje se moraš prijaviti. "
                "Anonimni gosti lahko prejemajo priporočila, ne pa ocenjujejo."
            )
        user_id = str(user_id).strip()

        rec = self.feedback.get(pot_id) or self.feedback.get(str(pot_id))
        if not rec:
            rec = {'sum': 0.0, 'n': 0, 'ratings': {}}
        if 'ratings' not in rec or not isinstance(rec['ratings'], dict):
            rec['ratings'] = {}

        # Če je ocena že obstajala → posodobi (odštej staro, prišteji novo)
        # Če je nova → poveča n
        stara_ocena = rec['ratings'].get(user_id)
        if stara_ocena is not None:
            # Sprememba obstoječe ocene
            rec['sum'] = float(rec.get('sum', 0.0)) - float(stara_ocena) + ocena
            # n ostane enak
        else:
            # Nova ocena
            rec['sum'] = float(rec.get('sum', 0.0)) + ocena
            rec['n']   = int(rec.get('n', 0)) + 1
        rec['ratings'][user_id] = ocena
        self.feedback[pot_id] = rec
        self._shrani_feedback()

        # Posodobi user profil (za boljše CF sosede v prihodnje)
        if profil:
            self._shrani_user_profile(user_id, profil)

        return {
            'pot_id':        pot_id,
            'ocena':         ocena,
            'povprecje':     round(rec['sum'] / rec['n'], 2),
            'stevilo_ocen':  rec['n'],
            'bila_sprememba': stara_ocena is not None,
        }

    def je_ze_ocenil(self, pot_id, user_id):
        if not user_id:
            return None
        rec = self.feedback.get(int(pot_id)) or self.feedback.get(str(pot_id))
        if not rec:
            return None
        ratings = rec.get('ratings', {}) if isinstance(rec.get('ratings'), dict) else {}
        val = ratings.get(str(user_id).strip())
        return float(val) if val is not None else None

    # Ustreznost predloga (ostane kot pomožni signal)
    @staticmethod
    def _profil_key(profil):
        p = GrmUHribeRecommender._normaliziraj_profil(profil)
        return f"t{p['tezavnost']}|{p['oznacenost']}|{p['gorovje']}"

    def oceni_ustreznost(self, profil, pot_id, ocena, user_id=None):
        try:
            pot_id = int(pot_id); ocena = float(ocena)
        except (TypeError, ValueError):
            raise ValueError("pot_id mora biti int, ocena število")
        if not (1 <= ocena <= 5):
            raise ValueError("Ocena mora biti med 1 in 5")
        if not user_id:
            raise ValueError("user_id je obvezen")
        if not je_prijavljen(user_id):
            raise PermissionError(
                "Za ocenjevanje ustreznosti se moraš prijaviti."
            )

        user_id = str(user_id).strip()
        pkey = self._profil_key(profil)
        po_profilu = self.ustreznost.setdefault(pkey, {})
        rec = po_profilu.get(str(pot_id), {'sum': 0.0, 'n': 0, 'ratings': {}})
        if 'ratings' not in rec or not isinstance(rec['ratings'], dict):
            rec['ratings'] = {}

        if user_id in rec['ratings']:
            prejsnja = rec['ratings'][user_id]
            raise PermissionError(
                f"Ta predlog si že ocenil z {prejsnja}★ za tvoj profil."
            )

        stara_ust = rec['ratings'].get(user_id)
        if stara_ust is not None:
            rec['sum'] = float(rec.get('sum', 0.0)) - float(stara_ust) + ocena
        else:
            rec['sum'] = float(rec.get('sum', 0.0)) + ocena
            rec['n']   = int(rec.get('n', 0)) + 1
        rec['ratings'][user_id] = ocena
        po_profilu[str(pot_id)] = rec
        self._shrani_ustreznost()

        self._shrani_user_profile(user_id, profil)

        return {
            'pot_id':        pot_id,
            'ocena':         ocena,
            'profil_key':    pkey,
            'povprecje':     round(rec['sum'] / rec['n'], 2),
            'stevilo_ocen':  rec['n'],
            'bila_sprememba': stara_ust is not None,
        }

    def je_ze_ocenil_ustreznost(self, profil, pot_id, user_id):
        if not user_id:
            return None
        pkey = self._profil_key(profil)
        rec = self.ustreznost.get(pkey, {}).get(str(int(pot_id)))
        if not rec:
            return None
        ratings = rec.get('ratings', {}) if isinstance(rec.get('ratings'), dict) else {}
        val = ratings.get(str(user_id).strip())
        return float(val) if val is not None else None

    # ─── PODATKI O UPORABNIKU (za stran "Moj profil") ─────────
    def podatki_uporabnika(self, user_id):
        """
        Vrne vse, kar imamo shranjeno o uporabniku (za prikaz na "Moj profil"):
          - njegov zadnji znan profil
          - vse poti, ki jih je ocenil (z oceno + podatki o poti)
          - vse ocene ustreznosti predlogov
          - 10 najbližjih CF sosedov (anonimno z user_id stringom + njihov profil)
        """
        if not self._naložen:
            raise RuntimeError("Model ni naložen.")
        uid = str(user_id).strip()

        # 1) profil — beremo DIREKTNO Z DISKA, ne iz memorije.
        # Memorija (self.user_profili) se posodablja ob vsakem iskanju (za CF),
        # disk pa samo ob ocenjevanju/registraciji. Profil na disku = pravi profil.
        profili_na_disku = self._nalozi_json(USER_PROFIL_PATH, {})
        profil = profili_na_disku.get(uid)

        # 2) ocene poti
        ocene_poti = []
        for pot_id, rec in self.feedback.items():
            if not isinstance(rec, dict):
                continue
            ratings = rec.get('ratings', {})
            if not isinstance(ratings, dict) or uid not in ratings:
                continue
            row_df = self.df[self.df['id'] == int(pot_id)]
            if row_df.empty:
                continue
            row = row_df.iloc[0]
            povp = round(rec['sum']/rec['n'], 2) if rec.get('n') else None
            ocene_poti.append({
                'pot_id':         int(pot_id),
                'pot':            str(row['Pot']),
                'vrh':            str(row['Vrh']),
                'gorovje':        str(row['Gorovje']),
                'visina_m':       int(row['Visina_m']),
                'cas_min':        int(row['Cas_min']),
                'tezavnost_num':  int(row['Tezavnost_num']),
                'moja_ocena':     float(ratings[uid]),
                'povprecje_vseh': povp,
                'stevilo_ocen':   rec.get('n', 0),
            })
        ocene_poti.sort(key=lambda x: -x['moja_ocena'])

        # 3) ocene ustreznosti
        ocene_ustreznosti = []
        for pkey, po_profilu in self.ustreznost.items():
            if not isinstance(po_profilu, dict):
                continue
            for pot_id, rec in po_profilu.items():
                ratings = rec.get('ratings', {}) if isinstance(rec, dict) else {}
                if not isinstance(ratings, dict) or uid not in ratings:
                    continue
                row_df = self.df[self.df['id'] == int(pot_id)]
                if row_df.empty:
                    continue
                row = row_df.iloc[0]
                ocene_ustreznosti.append({
                    'pot_id':     int(pot_id),
                    'pot':        str(row['Pot']),
                    'vrh':        str(row['Vrh']),
                    'profil_key': pkey,
                    'moja_ocena': float(ratings[uid]),
                })
        ocene_ustreznosti.sort(key=lambda x: -x['moja_ocena'])

        # 4) CF sosedje (samo če imamo profil)
        sosedje = []
        if profil:
            pom = self.user_profili
            self.user_profili = {k: v for k, v in pom.items() if k != uid}
            try:
                top_sosedje = self._najdi_sosede(profil, k=10)
            finally:
                self.user_profili = pom
            for soused_uid, d, w in top_sosedje:
                sp = self.user_profili.get(soused_uid, {})
                sosedje.append({
                    'user_id':    soused_uid,
                    'razdalja':   round(d, 3),
                    'utez':       round(w, 3),
                    'fitness':    sp.get('fitness'),
                    'izkusnje':   sp.get('izkusnje'),
                    'oznacenost': sp.get('oznacenost'),
                    'gorovje':    sp.get('gorovje'),
                })

        return {
            'user_id':           uid,
            'prijavljen':        je_prijavljen(uid),
            'profil':            profil,
            'ocene_poti':        ocene_poti,
            'ocene_ustreznosti': ocene_ustreznosti,
            'sosedje':           sosedje,
            'st_sosedov':        len(sosedje),
            'st_ocen_poti':      len(ocene_poti),
            'st_ocen_ustreznosti': len(ocene_ustreznosti),
        }

    # ─── NALAGANJE BAZE POTI ──────────────────────────────────
    @staticmethod
    def _parse_visina(s):
        m = re.search(r'(\d+)', str(s))
        return int(m.group(1)) if m else 0

    @staticmethod
    def _parse_cas(s):
        s = str(s).lower()
        h = re.search(r'(\d+)\s*h', s)
        m = re.search(r'(\d+)\s*min', s)
        mins = (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)
        return mins if mins > 0 else 60

    @staticmethod
    def _parse_priljub(s):
        m = re.search(r'(\d+)', str(s))
        return int(m.group(1)) if m else 50

    @staticmethod
    def _parse_zahtevnost(s):
        """
        Mapping zahtevnosti iz hribi.net na (tezavnost_num, oznacenost).

        Lestvica tezavnosti (1-9):
          1 = ni podatka
          2 = lahka označena pot / lahka neoznačena steza
          3 = lahko brezpotje
          4 = delno zahtevna označena/neoznačena pot
          5 = zahtevna označena/neoznačena pot/steza / zahtevno brezpotje
          6 = zelo zahtevna označena/neoznačena pot/steza / zelo zahtevno brezpotje
          7 = izjemno zahtevna označena pot
          8 = alpinistični vzpon

        Označenost (3 kategorije):
          'oznacena'  = označena pot
          'mesano'    = neoznačena steza/pot
          'brezpotje' = brezpotje
        """
        s_full = str(s).lower().strip()
        # Vzemi prvi del (pred vejico) — to je glavna kategorija
        s = s_full.split(',')[0].strip()

        # ── TEŽAVNOST ──
        if 'alpinis' in s:
            teza = 8
        elif 'izjemno zahtev' in s:
            teza = 7
        elif 'zelo zahtev' in s:
            teza = 6
        elif 'zahtev' in s and 'delno' not in s:
            teza = 5
        elif 'delno zahtev' in s:
            teza = 4
        elif 'lahk' in s and 'brez' in s:
            teza = 3
        elif 'lahk' in s:
            teza = 2
        elif 'ni podatk' in s or s == '' or s == 'nan':
            teza = 1
        else:
            teza = 3

        # ── OZNAČENOST ──
        if 'brezpotj' in s:
            oz = 'brezpotje'
        elif 'neoznač' in s or 'neoznac' in s:
            oz = 'mesano'
        elif 'označen' in s or 'oznacen' in s:
            oz = 'oznacena'
        else:
            oz = 'mesano'
        return teza, oz

    def nalozi(self):
        excel_path = None
        for cand in EXCEL_CANDIDATES:
            if os.path.exists(cand):
                excel_path = cand
                break
        if excel_path is None:
            raise FileNotFoundError("Ne najdem Excel baze.")

        print(f"  Nalagam bazo poti iz {excel_path}...")
        df = self._nalozi_excel_auto(excel_path)
        self.df = self._pocisti(df)
        print(f"   Naloženih {len(self.df)} poti")
        print(f"    CF sistem:")
        print(f"      • {len(self.user_profili)} uporabniških profilov")
        print(f"      • {len(self.feedback)} poti s feedback ocenami")
        print(f"      • {len(self.ustreznost)} profil-ključev za ustreznost")
        self._naložen = True
        return self

    def _nalozi_excel_auto(self, path):
        for h in (0, 1):
            try:
                df = pd.read_excel(path, header=h)
                if {'Gorovje', 'Vrh', 'Pot'}.issubset(set(df.columns)):
                    return df
            except Exception:
                continue
        return pd.read_excel(path, header=0)

    def _pocisti(self, df):
        df = df.copy()

        if 'Visina_m' not in df.columns:
            df['Visina_m'] = df['Visina'].apply(self._parse_visina) if 'Visina' in df.columns else 1000
        df['Visina_m'] = pd.to_numeric(df['Visina_m'], errors='coerce').fillna(1000).astype(int)

        if 'Cas_min' not in df.columns:
            df['Cas_min'] = df['Cas'].apply(self._parse_cas) if 'Cas' in df.columns else 120
        df['Cas_min'] = pd.to_numeric(df['Cas_min'], errors='coerce').fillna(120).astype(int)

        if df['Priljubljenost'].dtype == object:
            df['Priljubljenost'] = df['Priljubljenost'].apply(self._parse_priljub)
        df['Priljubljenost'] = pd.to_numeric(df['Priljubljenost'], errors='coerce').fillna(50).astype(int)

        if 'Zahtevnost' in df.columns:
            zo = df['Zahtevnost'].astype(str)
        elif 'Zahtevnost_orig' in df.columns:
            zo = df['Zahtevnost_orig'].astype(str)
        else:
            zo = pd.Series([''] * len(df))
        df['Zahtevnost_orig'] = zo

        if 'Tezavnost_num' not in df.columns or 'Oznacenost' not in df.columns:
            parsed = zo.apply(self._parse_zahtevnost)
            df['Tezavnost_num'] = [p[0] for p in parsed]
            df['Oznacenost']    = [p[1] for p in parsed]
        df['Tezavnost_num'] = pd.to_numeric(df['Tezavnost_num'], errors='coerce').fillna(3).astype(int)

        def norm_oz(o):
            o = str(o).lower().strip()
            if 'brezpotj' in o: return 'brezpotje'
            if 'neoznač' in o or 'neoznac' in o: return 'mesano'
            if 'označen' in o or 'oznacen' in o: return 'oznacena'
            if o in ('oznacena','mesano','brezpotje'): return o
            return 'mesano'
        df['Oznacenost'] = df['Oznacenost'].apply(norm_oz)

        df['Gorovje'] = df['Gorovje'].fillna('').astype(str).str.strip()

        if 'Opis_Poti' not in df.columns: df['Opis_Poti'] = ''
        if 'Dostop_do_Izhodisca' not in df.columns:
            df['Dostop_do_Izhodisca'] = df['Dostop'] if 'Dostop' in df.columns else ''
        df['Opis_Poti']           = df['Opis_Poti'].fillna('').astype(str)
        df['Dostop_do_Izhodisca'] = df['Dostop_do_Izhodisca'].fillna('').astype(str)

        # Novi stolpci iz hribi.net scraper-ja (lahko manjkajo v stari bazi)
        for c in ('Visinska_razlika', 'Visinska_razlika_po_poti', 'Oprema_poletje', 'Oprema_zima'):
            if c not in df.columns: df[c] = ''
            df[c] = df[c].fillna('').astype(str)

        for c in ('Pot','Vrh'):
            if c not in df.columns: df[c] = ''
            df[c] = df[c].fillna('').astype(str)

        df = df.dropna(subset=['Visina_m','Cas_min','Tezavnost_num']).reset_index(drop=True)
        df['id'] = df.index
        return df

    # ─── GLAVNA METODA: priporoči ─────────────────────────────
    def priporoči(self, user_profil, n=9, izkljuci=None, user_id=None, shrani_profil=False):
        """
        Priporoči n poti glede na CF:
          1. Poišči K najbližjih sosedov (evklidska razdalja med profili).
          2. Rangi poti po povprečni tehtani oceni teh sosedov.
          3. Cold start fallback: če sosedov ni dovolj, kombiniramo s priljubljenostjo.
          4. Hard filtri (max_visina, max_cas, označenost, izkluci) se uporabijo na koncu.

        Tudi trenutni user si zapomnimo — tako se naše priporočilo za njega
        izboljšuje čez čas.
        """
        if not self._naložen:
            raise RuntimeError("Model ni naložen.")

        izkljuci = set(int(x) for x in (izkljuci or []))
        norm = self._normaliziraj_profil(user_profil)

        # Profil shranimo v memorijo (za CF sosede) vedno,
        # na disk (user_profili.json) pa SAMO ob eksplicitnem dejanju (ocenjevanje).
        # Sicer bi vsako brskanje po filtri prepisalo "pravi" shranjen profil.
        if user_id and je_prijavljen(user_id):
            self.user_profili[str(user_id)] = self._normaliziraj_profil(user_profil)
            if shrani_profil:
                self._shrani_json(USER_PROFIL_PATH, self.user_profili)

        # ── 1) POIŠČI SOSEDE ──
        # pri iskanju izpustimo samega sebe
        vsi_profili = {uid: p for uid, p in self.user_profili.items()
                       if uid != str(user_id or '')}
        if vsi_profili:
            # zamašim temporarily self.user_profili zato, ker _najdi_sosede ga bere
            pom = self.user_profili
            self.user_profili = vsi_profili
            sosedje = self._najdi_sosede(user_profil, k=K_SOSEDOV)
            self.user_profili = pom
        else:
            sosedje = []

        # ── 2) TRDI FILTRI (PRED rangiranje, da CF ne dela po nepotrebnem) ──
        max_hm  = norm['max_visina'] or 2900
        max_cas = norm['max_cas'] or 720
        min_hm  = norm['min_visina']
        min_cas = norm['min_cas']
        oznacenost_pref = norm['oznacenost']
        zelena_reg = norm['gorovje']
        tezavnost_pref = norm['tezavnost']

        mask = pd.Series([True] * len(self.df))
        mask &= self.df['Visina_m'] <= max_hm * 1.10
        mask &= self.df['Cas_min']  <= max_cas * 1.15
        if min_hm > 0:
            mask &= self.df['Visina_m'] >= min_hm
        if min_cas > 0:
            mask &= self.df['Cas_min']  >= min_cas

        # Težavnost — strogo: če uporabnik izbere točno težavnost (ne "brez preference"=1),
        # filtriramo SAMO na izbrano težavnost (eksaktno ujemanje, brez razpona)
        if tezavnost_pref > 1:
            mask &= self.df['Tezavnost_num'] == tezavnost_pref

        # Označenost — strogo ujemanje:
        #   'vse'       → brez filtra (vse poti)
        #   'oznacena'  → samo označene poti
        #   'mesano'    → samo delno označene (mesano)
        #   'brezpotje' → samo brezpotje
        if oznacenost_pref == 'oznacena':
            mask &= self.df['Oznacenost'] == 'oznacena'
        elif oznacenost_pref == 'mesano':
            mask &= self.df['Oznacenost'] == 'mesano'
        elif oznacenost_pref == 'brezpotje':
            mask &= self.df['Oznacenost'] == 'brezpotje'
        # 'vse' = brez filtra

        # Regija — STROGO
        if zelena_reg and zelena_reg != 'vse':
            mask &= self.df['Gorovje'].str.contains(zelena_reg, case=False, na=False, regex=False)

        # Priljubljenost — filter po min/max %
        min_pril = norm.get('min_pril', 0)
        max_pril = norm.get('max_pril', 100)
        if min_pril > 0:
            mask &= self.df['Priljubljenost'] >= min_pril
        if max_pril < 100:
            mask &= self.df['Priljubljenost'] <= max_pril

        if izkljuci:
            mask &= ~self.df['id'].isin(izkljuci)

        filtrirano = self.df[mask].copy()

        # FALLBACK STRATEGIJA — STROGO upoštevamo hard filter (višina, čas, označenost, težavnost).
        # Boljše je vrniti manj rezultatov ali ponovljene, kot pa neustrezne.
        if izkljuci and len(filtrirano) < n:
            # Re-roll: ponovi že prikazane (NE sprosti hard filtrov)
            mask_strict = pd.Series([True] * len(self.df))
            mask_strict &= self.df['Visina_m'] <= max_hm * 1.10
            mask_strict &= self.df['Cas_min']  <= max_cas * 1.15
            if min_hm > 0:  mask_strict &= self.df['Visina_m'] >= min_hm
            if min_cas > 0: mask_strict &= self.df['Cas_min']  >= min_cas
            if tezavnost_pref > 1:
                mask_strict &= self.df['Tezavnost_num'] == tezavnost_pref
            if oznacenost_pref == 'oznacena':
                mask_strict &= self.df['Oznacenost'] == 'oznacena'
            elif oznacenost_pref == 'mesano':
                mask_strict &= self.df['Oznacenost'] == 'mesano'
            elif oznacenost_pref == 'brezpotje':
                mask_strict &= self.df['Oznacenost'] == 'brezpotje'
            if zelena_reg and zelena_reg != 'vse':
                mask_strict &= self.df['Gorovje'].str.contains(zelena_reg, case=False, na=False, regex=False)
            filtrirano = self.df[mask_strict].copy()

        # Pri prvem klicu (brez izkljuci): če v bazi res ni nič, vrni manj (prazno).
        # Frontend pokaže "Razširi filter, ni ujemanj". NE sprostimo, da uporabnik
        # ne dobi neustreznih poti.

        # ── 3) IZRAČUNAJ CF SCORE ZA VSAKO POT ──
        dovolj_sosedov = len(sosedje) >= MIN_SOSEDOV_CF

        scores = []
        n_sosed_ocenili = []
        ima_cf_signal = []

        # Idealna višina po težavnosti (za popularity baseline)
        idealna_hm = {1: 800, 2: 500, 3: 800, 4: 1000,
                      5: 1500, 6: 2000, 7: 2400, 8: 2600}.get(norm['tezavnost'], 1000)

        for _, row in filtrirano.iterrows():
            pot_id = int(row['id'])

            # ── POPULARITY BASELINE ──
            # = priljubljenost + ujemanje višine s profilom
            pril_norm = float(row['Priljubljenost']) / 100.0
            hm_diff = abs(float(row['Visina_m']) - idealna_hm) / 2900.0
            popularity_score = 0.70 * pril_norm + 0.30 * max(0, 1 - hm_diff)

            # ── CF SIGNAL ──
            if dovolj_sosedov:
                cf, n_sos = self._cf_score_poti(pot_id, sosedje, profil=user_profil)
            else:
                cf, n_sos = None, 0

            if cf is not None and n_sos > 0:
                # CF score je v [0, 1] (0 = vsi sosedje 1*, 1 = vsi 5*).
                # Centriramo okrog 0.5 (= povprečen 3*) → [-1, +1]:
                #   5* → cf_centered = +1 (max bonus)
                #   3* → cf_centered =  0 (brez vpliva)
                #   1* → cf_centered = -1 (max kazen)
                cf_centered = (cf - 0.5) * 2

                # Confidence: rast s številom sosedov, max pri 5+.
                confidence = min(1.0, n_sos / 5.0)

                # CF lahko premakne score za ±0.60 (večji vpliv kot baseline 0.40)
                # Tako 5* ocena vedno premaga neoceneno popularno pot.
                cf_delta = 0.60 * cf_centered * confidence

                # Baseline (popularity) ima maks 0.40
                # CF doda ±0.60 → razpon [-0.20, 1.00]
                score = 0.40 * popularity_score + cf_delta
                # clamp na [0, 1]
                score = max(0.0, min(1.0, score))
                ima_cf_signal.append(True)
            else:
                # Brez CF signala — samo baseline (max 0.40)
                # Tako poti brez ocen NE morejo prekositi pozitivno ocenjenih,
                # in pozitivne ocene NE morejo prekositi negativnih.
                score = 0.40 * popularity_score
                ima_cf_signal.append(False)

            scores.append(score)
            n_sosed_ocenili.append(n_sos)

        filtrirano['_score'] = scores
        filtrirano['_n_sos'] = n_sosed_ocenili
        filtrirano['_cf_on'] = ima_cf_signal

        # ── 4) TOP N ──
        top = filtrirano.nlargest(n, '_score')
        return [self._pot_v_json(row, score=float(row['_score']),
                                  user_id=user_id, profil=user_profil,
                                  n_sosedov=int(row['_n_sos']),
                                  cf_aktiven=bool(row['_cf_on']),
                                  skupaj_sosedov=len(sosedje),
                                  light=True)
                for _, row in top.iterrows()]

    # ─── ISKANJE / DETAJLI ────────────────────────────────────
    def isci(self, query, limit=20, user_id=None):
        if not self._naložen:
            raise RuntimeError("Model ni naložen.")
        q = query.lower().strip()
        mask = (
            self.df['Pot'].str.lower().str.contains(q, na=False, regex=False) |
            self.df['Vrh'].str.lower().str.contains(q, na=False, regex=False) |
            self.df['Gorovje'].str.lower().str.contains(q, na=False, regex=False)
        )
        return [self._pot_v_json(row, user_id=user_id, light=True)
                for _, row in self.df[mask].head(limit).iterrows()]

    def get_pot(self, pot_id, user_id=None, profil=None):
        if not self._naložen:
            raise RuntimeError("Model ni naložen.")
        row = self.df[self.df['id'] == pot_id]
        if row.empty:
            return None
        return self._pot_v_json(row.iloc[0], user_id=user_id, profil=profil)

    # ─── PRETVORNIK ───────────────────────────────────────────
    def _pot_v_json(self, row, score=None, user_id=None, profil=None,
                    n_sosedov=0, cf_aktiven=False, skupaj_sosedov=0, light=False):
        oz_label = {
            'oznacena':'Označena pot','mesano':'Delno označena','brezpotje':'Brezpotje'
        }.get(str(row['Oznacenost']), str(row['Oznacenost']))
        teza_label = {
            1:'Ni podatka',
            2:'Lahka',3:'Lahko brezpotje',4:'Delno zahtevna',5:'Zahtevna',
            6:'Zelo zahtevna',7:'Izjemno zahtevna',8:'Alpinistični vzpon'
        }.get(int(float(row['Tezavnost_num'])), 'Neznano')

        pot_id = int(row['id'])
        rec = self.feedback.get(pot_id) or self.feedback.get(str(pot_id))
        moja_ocena = self.je_ze_ocenil(pot_id, user_id) if user_id else None
        user_rating = {
            'povprecje':    round(rec['sum']/rec['n'], 2) if rec and rec['n'] else None,
            'stevilo_ocen': rec['n'] if rec else 0,
            'moja_ocena':   moja_ocena,
            'ze_ocenjeno':  moja_ocena is not None,
        }

        ustreznost_info = None
        if profil is not None:
            moja_ust = self.je_ze_ocenil_ustreznost(profil, pot_id, user_id) if user_id else None
            rec_ust = self.ustreznost.get(self._profil_key(profil), {}).get(str(pot_id))
            ustreznost_info = {
                'povprecje':    round(rec_ust['sum']/rec_ust['n'],2) if rec_ust and rec_ust.get('n') else None,
                'stevilo_ocen': rec_ust['n'] if rec_ust else 0,
                'moja_ocena':   moja_ust,
                'ze_ocenjeno':  moja_ust is not None,
            }

        data = {
            'id':             pot_id,
            'pot':            str(row['Pot']),
            'vrh':            str(row['Vrh']),
            'gorovje':        str(row['Gorovje']),
            'visina_m':       int(float(row['Visina_m'])),
            'cas_min':        int(float(row['Cas_min'])),
            'priljubljenost': int(float(row['Priljubljenost'])),
            'tezavnost':      teza_label,
            'tezavnost_num':  int(float(row['Tezavnost_num'])),
            'oznacenost':     oz_label,
            'oznacenost_raw': str(row['Oznacenost']),
            'visinska_razlika':     str(row.get('Visinska_razlika','')).strip(),
            'visinska_razlika_pot': str(row.get('Visinska_razlika_po_poti','')).strip(),
            'oprema_poletje':       str(row.get('Oprema_poletje','')).strip() or 'ni priporočil',
            'oprema_zima':          str(row.get('Oprema_zima','')).strip() or 'ni priporočil',
            'user_rating':    user_rating,
            'ustreznost':     ustreznost_info,
        }

        # Velika polja (opis, dostop) dodamo samo če NI light verzija.
        # V light verziji (npr. za seznam priporočil) jih izpustimo, da
        # zmanjšamo velikost JSON odgovora (lahko gre tudi v 30 MB pri 7947 poteh).
        if not light:
            data['zahtevnost_orig'] = str(row.get('Zahtevnost_orig', ''))
            data['opis']            = str(row.get('Opis_Poti', ''))
            data['dostop']          = str(row.get('Dostop_do_Izhodisca', ''))

        if score is not None:
            score_pct = min(100, max(0, int(score * 100)))
            data['score']       = score_pct
            data['score_label'] = self._score_label(score_pct)
            # CF razlaga — vedno (majhen overhead, koristna za debug)
            data['cf_info'] = {
                'aktiven':           bool(cf_aktiven),
                'n_sosedov_ocenili': int(n_sosedov),
                'skupaj_sosedov':    int(skupaj_sosedov),
                'nacin':             'collaborative' if cf_aktiven else 'cold_start_popularity',
            }
        return data

    @staticmethod
    def _score_label(score):
        if score >= 80: return 'Odlično ujemanje'
        if score >= 65: return 'Dobro ujemanje'
        if score >= 50: return 'Delno ujemanje'
        return 'Slabo ujemanje'

    # ─── STATISTIKE ───────────────────────────────────────────
    def statistike(self):
        if not self._naložen:
            return {}
        return {
            'skupaj_poti': int(len(self.df)),
            'gorovja':     int(self.df['Gorovje'].nunique()),
            'vrhi':        int(self.df['Vrh'].nunique()),
            'avg_visina':  int(self.df['Visina_m'].mean()),
            'avg_cas_min': int(self.df['Cas_min'].mean()),
            'avg_priljub': int(self.df['Priljubljenost'].mean()),
            'zahtevnosti': {
                'lahka':          int((self.df['Tezavnost_num']==2).sum()),
                'delno_zahtevna': int((self.df['Tezavnost_num']==4).sum()),
                'zahtevna':       int((self.df['Tezavnost_num']==5).sum()),
                'zelo_zahtevna':  int((self.df['Tezavnost_num']==6).sum()),
                'izjemno':        int((self.df['Tezavnost_num']==7).sum()),
            },
            'oznacenosti': {
                'oznacena':  int((self.df['Oznacenost']=='oznacena').sum()),
                'mesano':    int((self.df['Oznacenost']=='mesano').sum()),
                'brezpotje': int((self.df['Oznacenost']=='brezpotje').sum()),
            },
            'cf_sistem': {
                'uporabnikov':        len(self.user_profili),
                'poti_z_ocenami':     len(self.feedback),
                'profil_kljucev_ust': len(self.ustreznost),
            }
        }


# ─── SINGLETON ────────────────────────────────────────────────
_recommender = None

def get_recommender():
    global _recommender
    if _recommender is None:
        _recommender = GrmUHribeRecommender()
        _recommender.nalozi()
    return _recommender
