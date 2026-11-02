#!/usr/bin/env python3
"""Collecte quotidienne des actualités juridiques françaises -> data.json

Usage :
  python collecte.py                       # les 3 derniers jours
  python collecte.py --depuis 2026-01-01   # rattrapage depuis une date

Variables d'environnement : PISTE_CLIENT_ID, PISTE_CLIENT_SECRET
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

import requests

CID = os.environ.get("PISTE_CLIENT_ID")
SECRET = os.environ.get("PISTE_CLIENT_SECRET")
TOKEN_URL = "https://oauth.piste.gouv.fr/api/oauth/token"
JUDI = "https://api.piste.gouv.fr/cassation/judilibre/v1.0"
LEGI = "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app"
FICHIER = "data.json"

# Correspondance chambre -> matière (à ajuster selon vos besoins)
CHAMBRES = {
    "soc": "Travail", "cr": "Pénal", "civ1": "Famille et civil",
    "civ2": "Civil", "civ3": "Immobilier", "comm": "Commercial",
}


def requete(methode, url, **kw):
    """Appel HTTP avec nouvelles tentatives (limites de débit, erreurs réseau)."""
    for essai in range(5):
        try:
            r = requests.request(methode, url, timeout=60, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** essai * 2)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            if essai == 4:
                raise
            time.sleep(2 ** essai * 2)
    raise RuntimeError(f"Échec après plusieurs essais : {url}")


def entetes():
    if not CID or not SECRET:
        sys.exit("Identifiants PISTE manquants (PISTE_CLIENT_ID / PISTE_CLIENT_SECRET).")
    r = requete("POST", TOKEN_URL, data={
        "grant_type": "client_credentials", "client_id": CID,
        "client_secret": SECRET, "scope": "openid"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def texte(v):
    if isinstance(v, dict):
        return v.get("title") or v.get("text") or ""
    return v or ""


def collecter_judilibre(h, debut, fin, items):
    """Décisions de justice (Cour de cassation, cours d'appel, tribunaux)."""
    lot, ajoutes = 0, 0
    while True:
        r = requete("GET", f"{JUDI}/export", headers=h, params={
            "date_start": debut, "date_end": fin, "batch": lot, "batch_size": 100})
        resultats = r.json().get("results", [])
        if not resultats:
            break
        for d in resultats:
            cle = f"judilibre:{d['id']}"
            themes = d.get("themes") or []
            matiere = CHAMBRES.get(d.get("chamber")) or (themes[0] if themes else "Jurisprudence")
            titre = texte(d.get("summary")) or "Décision n° {} ({})".format(
                d.get("number", "?"), d.get("jurisdiction", ""))
            if cle not in items:
                ajoutes += 1
            items[cle] = {
                "id": cle, "source": "Judilibre", "date": d.get("decision_date"),
                "titre": titre[:220], "matiere": matiere,
                "url": f"https://www.courdecassation.fr/decision/{d['id']}",
                "resume": f"{d.get('jurisdiction', '')} – chambre {d.get('chamber', '')}".strip(" –"),
            }
        lot += 1
        time.sleep(0.5)  # ménager l'API
    print(f"Judilibre : {ajoutes} nouvelle(s) décision(s)")


def date_iso(v):
    """Accepte un timestamp en millisecondes ou une chaîne AAAA-MM-JJ."""
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc).date().isoformat()
    return str(v)[:10] if v else None


def collecter_jorf(h, items):
    """Derniers numéros du Journal officiel (un enregistrement par numéro)."""
    r = requete("POST", f"{LEGI}/consult/lastNJo", headers=h, json={"nbElement": 5})
    ajoutes = 0
    for c in r.json().get("containers", []):
        ident = c.get("id")
        if not ident:
            continue
        d = date_iso(c.get("dateParution") or c.get("datePublication"))
        cle = f"jorf:{ident}"
        if cle not in items:
            ajoutes += 1
        items[cle] = {
            "id": cle, "source": "Journal officiel", "date": d,
            "titre": c.get("titre") or f"Journal officiel du {d}",
            "matiere": "Journal officiel",
            "url": f"https://www.legifrance.gouv.fr/jorf/id/{ident}",
            "resume": "Numéro du Journal officiel de la République française.",
        }
    print(f"Journal officiel : {ajoutes} nouveau(x) numéro(s)")


def charger():
    try:
        with open(FICHIER, encoding="utf-8") as f:
            return {i["id"]: i for i in json.load(f).get("items", [])}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def enregistrer(items):
    liste = sorted(items.values(), key=lambda i: i.get("date") or "", reverse=True)
    maj = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with open(FICHIER, "w", encoding="utf-8") as f:
        json.dump({"maj": maj, "items": liste}, f, ensure_ascii=False, indent=0)
    print(f"{len(liste)} entrées enregistrées dans {FICHIER}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--depuis", help="date de début AAAA-MM-JJ")
    p.add_argument("--fin", help="date de fin AAAA-MM-JJ")
    a = p.parse_args()
    fin = a.fin or dt.date.today().isoformat()
    debut = a.depuis or (dt.date.today() - dt.timedelta(days=3)).isoformat()

    h = entetes()
    items = charger()
    erreurs = 0
    for nom, appel in (
        ("Judilibre", lambda: collecter_judilibre(h, debut, fin, items)),
        ("Journal officiel", lambda: collecter_jorf(h, items)),
    ):
        try:
            appel()
        except Exception as e:  # une source en panne ne bloque pas les autres
            erreurs += 1
            print(f"ERREUR {nom} : {e}", file=sys.stderr)
    enregistrer(items)
    if erreurs == 2:
        sys.exit(1)


if __name__ == "__main__":
    main()
