GRM U HRIBE — Pohodniški priporočilni sistem z AI
==================================================
Šolski projekt | 3. letnik računalništva | 2025/26
Avtorja: Gasper Žnidar, Kukovec

STRUKTURA MAPE:
───────────────
aplikacija/
  app.py                        - Flask strežnik (API)
  recommender.py                - Collaborative Filtering algoritem
  scraper_hribi.py              - Web scraper za hribi.net
  grm_u_hribe_baza_podatkov.xlsx- Podatkovna baza (7.947 poti)
  requirements.txt              - Python paketi
  feedback.json                 - Ocene poti
  user_profili.json             - Profili uporabnikov
  feedback_ustreznost.json      - Ocene ustreznosti
  templates/index.html          - Frontend (SPA)
  static/logo.png               - Logotip

dokumentacija/
  changelog.docx                - Dnevnik sprememb (15 verzij)
  porocilopromptov.docx         - Poročilo o uporabi AI (5 promptov)

dokazi/
  dokaz2_scraper_cas.py         - Pretvorba časa v minute
  dokaz3_triglav_test.py        - Test filtra za max višino
  dokaz4_cf_test.py             - CF algoritem deluje
  dokaz4_cf_implementacija.py   - Razlaga CF algoritma
  dokaz5_strogi_filtri.py       - Strogi hard filtri
  dokaz7_grupiranje.py          - Grupiranje poti po vrhu
  dokaz8_responsive.css         - Responsive design CSS
  dokaz9_cf_bug.py              - Kritični bug v CF (popravek)
  dokaz10_profil_shranjevanje.py- Shranjevanje profila
  dokaz11_infinite_scroll.py    - Infinite scroll paginacija
  dokaz12_sort_html.html        - Sort filtri HTML
  dokaz14_sort_filtri.py        - Sort JS funkcija
  dokaz15_html_ostanki.py       - Čiščenje HTML ostankov
  VISI_OUTPUTI.txt              - Terminal outputi vseh dokazov

ZAGON APLIKACIJE:
─────────────────
1. pip install -r aplikacija/requirements.txt
2. cd aplikacija
3. python app.py
4. Odpri: http://localhost:5000

ŽIVA VERZIJA:
─────────────
https://grmuhribe.pythonanywhere.com/
