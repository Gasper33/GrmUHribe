GRM U HRIBE — Pohodniški priporočilni sistem z AI
==================================================
Šolski projekt | 3. letnik računalništva | 2025/26
Avtorja: Žnidar, Kukovec

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

ZAGON APLIKACIJE:
─────────────────
1. pip install -r aplikacija/requirements.txt
2. cd aplikacija
3. python app.py
4. Odpri: http://localhost:5000

ŽIVA VERZIJA:
─────────────
https://grmuhribe.pythonanywhere.com/
