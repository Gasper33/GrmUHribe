"""
GRM U HRIBE — Web scraper za hribi.net (DODATNI PODATKI)
================================================================

Iz spletne strani hribi.net izlušči naslednje podatke za vsako pot
v vseh slovenskih gorovjih:

  A) Gorovje
  B) Vrh
  C) Pot
  D) Visinska_razlika              (npr. "1611 m")
  E) Visinska_razlika_po_poti      (npr. "1611 m")
  F) Oprema_poletje                (npr. "cepin, dereze" ali "ni priporočil")
  G) Oprema_zima                   (npr. "cepin, dereze" ali "ni priporočil")

Rezultat se zapiše v: hribi_DODATKI_VSE.xlsx

Skripta deluje enako kot prejšnji `hribi_scraper_poti.py` — najprej brska
hierarhijo gorovja → vrhovi → poti, potem za vsako pot scrape-a
specifične 4 podatke.

────────────────────────────────────────────────────────────────
KAKO ZAGNATI V VS CODE:
────────────────────────────────────────────────────────────────
1. Namesti knjižnice (samo prvič) — v VS Code terminal (Ctrl+`):
       pip install requests beautifulsoup4 pandas openpyxl

2. Klikni gumb ▶️ Run (zgoraj desno) ali pritisni F5.

────────────────────────────────────────────────────────────────
KAKO ZAGNATI V CMD:
────────────────────────────────────────────────────────────────
    python scraper_hribi.py
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os

BASE_URL = "https://www.hribi.net"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

OUTPUT_FILE = "hribi_DODATKI_VSE.xlsx"

# ════════════════════════════════════════════════════════════════
# NASTAVITVE ZA TESTIRANJE
# ════════════════════════════════════════════════════════════════
# Za prvi preizkus pusti 10 — skripta bo obdelala samo prvih 10 poti
# (vzame ~1 minuto).
# Ko vidiš da deluje, nastavi na None — skripta bo obdelala vse poti.
LIMIT_POTI = None

# Filter regije — če želiš preizkusiti samo specifično gorovje (npr. da
# vidiš opremo za zahtevne poti na Triglavu), tu vpiši ime ali del imena.
# Primer: SAMO_REGIJA = "Julijske" → samo Julijske Alpe
# Primer: SAMO_REGIJA = None → vse regije (privzeto)
SAMO_REGIJA = None

# Filter števila vrhov — koliko vrhov v vsaki regiji obdelati.
# Vsak vrh ima ponavadi več poti (povprečno 3-5).
# Primer: LIMIT_VRHOV = 3 → samo prvi 3 vrhovi v vsaki regiji (~9-15 poti)
# Primer: LIMIT_VRHOV = None → vsi vrhovi (privzeto)
LIMIT_VRHOV = None
# ════════════════════════════════════════════════════════════════


def get_soup(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        print(f"Napaka pri povezavi ({url}): {e}")
        return None


def cleanup_text(s):
    """Počisti besedilo — odstrani odvečne presledke."""
    if not s:
        return ''
    s = s.strip()
    s = re.sub(r'\s+', ' ', s)
    return s


def extract_dodatne_podatke(soup):
    """
    Iz HTML-a strani z opisom poti izlušči 4 dodatne podatke.

    POMEMBNO: hribi.net uporablja <b> tag (ne <strong>!).
    Struktura na strani:
      <div class="g2">
         <b>Priporočena oprema (poletje):</b> čelada, komplet za samovarovanje
      </div>
      <div class="g2">
         <b>Priporočena oprema (zima):</b> cepin, dereze
      </div>

    Pri praznih vrednostih je text node prazen ali samo presledek.
    """
    rezultat = {
        'visinska_razlika':         '',
        'visinska_razlika_po_poti': '',
        'oprema_poletje':           'ni priporočil',
        'oprema_zima':              'ni priporočil',
    }

    # ── 1) VIŠINSKE RAZLIKE in OPREMA: išči po <b> in <strong> ──
    # Hribi.net uporablja oba (odvisno od strani) — prebereme oba.
    for tag_name in ('b', 'strong'):
        for tag in soup.find_all(tag_name):
            label = cleanup_text(tag.get_text())
            if not label:
                continue
            label_lower = label.lower().rstrip(':').strip()

            # Zberi vsebino za tag — tipično text node v parent elementu
            # Najprej: poskusi z next_siblings
            value = ''
            for sib in tag.next_siblings:
                if hasattr(sib, 'name') and sib.name in ('b', 'strong', 'br', 'p', 'div'):
                    break
                if hasattr(sib, 'get_text'):
                    value += ' ' + sib.get_text(' ', strip=True)
                else:
                    value += str(sib)
            value = cleanup_text(value).lstrip(':').strip()

            # Pomembno: "višinska razlika po poti" mora biti pred "višinska razlika"
            # (ker oba label-a vsebujeta "višinska razlika")
            if 'višinska razlika po poti' in label_lower:
                if value and not rezultat['visinska_razlika_po_poti']:
                    rezultat['visinska_razlika_po_poti'] = value
            elif 'višinska razlika' in label_lower:
                if value and not rezultat['visinska_razlika']:
                    rezultat['visinska_razlika'] = value
            elif 'priporočena oprema' in label_lower and 'poletj' in label_lower:
                # Vrednost je lahko prazna (= ni priporočil)
                if value:
                    rezultat['oprema_poletje'] = value
                # else: ostane "ni priporočil"
            elif 'priporočena oprema' in label_lower and 'zim' in label_lower:
                if value:
                    rezultat['oprema_zima'] = value
                # else: ostane "ni priporočil"

    # ── 2) FALLBACK: regex po celotnem HTML-u ──
    # Če zgornja strategija ni delovala (recimo struktura strani drugačna),
    # iščemo direktno v HTML-u: <b>...</b> ali <strong>...</strong> + besedilo.
    if rezultat['oprema_poletje'] == 'ni priporočil' or rezultat['oprema_zima'] == 'ni priporočil':
        html_str = str(soup)

        if rezultat['oprema_poletje'] == 'ni priporočil':
            # Iščemo: <b>Priporočena oprema (poletje):</b> VREDNOST
            # Vrednost je vse do naslednjega <
            pattern = re.compile(
                r'<(?:b|strong)[^>]*>\s*Priporočena oprema\s*\(\s*poletje\s*\)\s*:?\s*</(?:b|strong)>([^<]*)',
                re.IGNORECASE
            )
            m = pattern.search(html_str)
            if m:
                val = cleanup_text(m.group(1))
                if val:
                    rezultat['oprema_poletje'] = val

        if rezultat['oprema_zima'] == 'ni priporočil':
            pattern = re.compile(
                r'<(?:b|strong)[^>]*>\s*Priporočena oprema\s*\(\s*zima\s*\)\s*:?\s*</(?:b|strong)>([^<]*)',
                re.IGNORECASE
            )
            m = pattern.search(html_str)
            if m:
                val = cleanup_text(m.group(1))
                if val:
                    rezultat['oprema_zima'] = val

    # ── 3) FALLBACK za višinske razlike: regex po celem besedilu ──
    full_text = soup.get_text(' ', strip=True)
    if not rezultat['visinska_razlika']:
        m = re.search(r'Višinska razlika\s*:?\s*([\d\.\,]+\s*m)\b', full_text, re.IGNORECASE)
        if m:
            rezultat['visinska_razlika'] = m.group(1).strip()
    if not rezultat['visinska_razlika_po_poti']:
        m = re.search(r'Višinska razlika po poti\s*:?\s*([\d\.\,]+\s*m)\b', full_text, re.IGNORECASE)
        if m:
            rezultat['visinska_razlika_po_poti'] = m.group(1).strip()

    return rezultat


def save_to_excel_safely(data_list):
    """Zanesljivo shranjevanje na dno obstoječe datoteke po vsaki regiji."""
    if not data_list:
        return

    df_new = pd.DataFrame(data_list)

    if os.path.exists(OUTPUT_FILE):
        try:
            df_old = pd.read_excel(OUTPUT_FILE)
            df_combined = pd.concat([df_old, df_new], ignore_index=True)
            df_combined.to_excel(OUTPUT_FILE, index=False)
            print(f"✅ Regija shranjena! V {OUTPUT_FILE} je dodanih {len(data_list)} novih vrstic. "
                  f"(skupaj {len(df_combined)})")
        except Exception as e:
            print(f"Napaka pri pisanju v Excel: {e}. PREVERITE, ČE JE DATOTEKA ODPRTA!")
    else:
        df_new.to_excel(OUTPUT_FILE, index=False)
        print(f"✅ Ustvarjena nova datoteka {OUTPUT_FILE} z {len(data_list)} vrsticami.")


def run_full_dodatki_scrape():
    print("Pridobivam seznam vseh slovenskih gorovij...")
    soup = get_soup(f"{BASE_URL}/gorovja")
    if not soup:
        return

    regions = []
    for a in soup.find_all('a', href=True):
        if '/gorovje/' in a['href'] or 'skupina.asp?' in a['href']:
            region_url = BASE_URL + a['href'] if a['href'].startswith('/') else BASE_URL + "/" + a['href']
            # Izpustimo tuja gorovja
            if "tuje" not in region_url.lower():
                regions.append({"name": a.text.strip(), "url": region_url})

    if LIMIT_POTI is not None:
        print(f"⚠️  TESTNI NAČIN: skripta bo obdelala samo prvih {LIMIT_POTI} poti, "
              f"potem se zaustavi.")
        print(f"   (Za vse poti spremeni LIMIT_POTI = None na vrhu skripte.)")
    if LIMIT_VRHOV is not None:
        print(f"⚠️  FILTER VRHOV: v vsaki regiji se obdeluje samo prvih {LIMIT_VRHOV} vrhov.")
        print(f"   (Za vse vrhove spremeni LIMIT_VRHOV = None na vrhu skripte.)")
    if SAMO_REGIJA is not None:
        regions_filtered = [r for r in regions if SAMO_REGIJA.lower() in r['name'].lower()]
        print(f"⚠️  FILTER: samo regije, ki vsebujejo '{SAMO_REGIJA}' "
              f"({len(regions_filtered)}/{len(regions)} regij).")
        regions = regions_filtered
    print(f"\nZačenjam obsežno skeniranje dodatkov...\n")

    # Skupni števec obdelanih poti — uporabi se za LIMIT_POTI
    skupaj_obdelanih = 0

    for region in regions:
        # Preveri ali smo dosegli limit pred regijo
        if LIMIT_POTI is not None and skupaj_obdelanih >= LIMIT_POTI:
            break

        print(f"\n=====================================")
        print(f"Obdelava regije: {region['name']}")
        print(f"=====================================")

        reg_soup = get_soup(region['url'])
        if not reg_soup:
            continue

        peaks = []
        seen_peak_names = set()

        for a in reg_soup.find_all('a', href=True):
            if any(x in a['href'] for x in ['/gora/', 'gora.asp?', '/slap/', '/koca/', '/jezero/']):
                raw_name = a.text.strip()
                clean_name = re.sub(r'\s*[\d\.]+\s*m\s*$', '', raw_name, flags=re.IGNORECASE).strip()
                p_url = BASE_URL + a['href'] if a['href'].startswith('/') else BASE_URL + "/" + a['href']

                if clean_name.lower() not in seen_peak_names:
                    seen_peak_names.add(clean_name.lower())
                    peaks.append({"name": clean_name, "url": p_url})

        # Filter: če je nastavljen LIMIT_VRHOV, vzemi samo prvih N vrhov v regiji
        if LIMIT_VRHOV is not None:
            peaks = peaks[:LIMIT_VRHOV]
            print(f"  (omejitev na prvih {LIMIT_VRHOV} vrhov v regiji)")

        region_data = []

        for peak in peaks:
            # Preveri ali smo dosegli limit pred vrhom
            if LIMIT_POTI is not None and skupaj_obdelanih >= LIMIT_POTI:
                break

            print(f"  > Skeniram dodatne podatke za: {peak['name']}")
            p_soup = get_soup(peak['url'])
            if not p_soup:
                continue

            seen_path_urls = set()
            for a in p_soup.find_all('a', href=True):
                # Preveri ali smo dosegli limit pred potjo
                if LIMIT_POTI is not None and skupaj_obdelanih >= LIMIT_POTI:
                    break

                if '/izlet/' in a['href'] or 'izlet.asp?' in a['href']:
                    path_url = BASE_URL + a['href'] if a['href'].startswith('/') else BASE_URL + "/" + a['href']
                    if path_url in seen_path_urls:
                        continue

                    row = a.find_parent('tr')
                    if row:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            seen_path_urls.add(path_url)
                            p_name = cols[0].get_text(separator=" ", strip=True)

                            path_soup = get_soup(path_url)
                            podatki = {
                                'visinska_razlika':         '',
                                'visinska_razlika_po_poti': '',
                                'oprema_poletje':           'ni priporočil',
                                'oprema_zima':              'ni priporočil',
                            }
                            if path_soup:
                                podatki = extract_dodatne_podatke(path_soup)

                            region_data.append({
                                "Gorovje":                   region['name'],
                                "Vrh":                       peak['name'],
                                "Pot":                       p_name,
                                "Visinska_razlika":          podatki['visinska_razlika'],
                                "Visinska_razlika_po_poti":  podatki['visinska_razlika_po_poti'],
                                "Oprema_poletje":            podatki['oprema_poletje'],
                                "Oprema_zima":               podatki['oprema_zima'],
                            })
                            skupaj_obdelanih += 1
                            print(f"    [{skupaj_obdelanih:>4}]  ✓  {p_name[:55]:55}  "
                                  f"hm={podatki['visinska_razlika'][:10]:>10}  "
                                  f"po_poti={podatki['visinska_razlika_po_poti'][:10]:>10}")
                            # Nežna pavza, da nas strežnik ne blokira
                            time.sleep(0.3)

        # Shrani takoj, ko konča celotno regijo
        if region_data:
            save_to_excel_safely(region_data)

    if LIMIT_POTI is not None and skupaj_obdelanih >= LIMIT_POTI:
        print(f"\n✅ TESTNI NAČIN končan — obdelanih {skupaj_obdelanih} poti.")
        print(f"   Preveri datoteko {OUTPUT_FILE}, da vidiš ali je vse OK.")
        print(f"   Za scraping VSEH poti spremeni LIMIT_POTI = None na vrhu skripte.")
    else:
        print("\n🎉 MEGA USPEH! Skeniranje dodatnih podatkov za celotno Slovenijo je zaključeno.")


if __name__ == "__main__":
    run_full_dodatki_scrape()
