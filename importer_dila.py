#!/usr/bin/env python3
"""Import unique des archives DILA (base CASS : Cour de cassation, depuis 1960)
-> data/ANNEE.json (un fichier par année) + data/annees.json (nombre par année)

Usage :
  python importer_dila.py --limite 2000   # test rapide sur 2000 fichiers
  python importer_dila.py                 # import complet
"""
import argparse
import json
import os
import re
import tarfile
import xml.etree.ElementTree as ET
from collections import defaultdict

import requests

BASE = "https://echanges.dila.gouv.fr/OPENDATA/CASS/"
SORTIE = "data"
SOURCE = "Cour de cassation (Bulletin)"

# mot-clé dans la formation -> matière (à ajuster)
MATIERES = [("sociale", "Travail"), ("criminelle", "Pénal"), ("commerciale", "Commercial"),
            ("mixte", "Jurisprudence"), ("plénière", "Jurisprudence"), ("civile", "Civil")]


def texte(el):
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def trouver_archive():
    page = requests.get(BASE, timeout=60)
    page.raise_for_status()
    noms = re.findall(r'href="(Freemium_cass_global_[^"]+\.tar\.gz)"', page.text)
    if not noms:
        raise SystemExit(f"Aucune archive globale trouvée à {BASE}")
    return BASE + sorted(noms)[-1]


def lire(contenu):
    r = ET.fromstring(contenu)
    ident = texte(r.find(".//META_COMMUN/ID"))
    date = texte(r.find(".//META_JURI/DATE_DEC"))
    if not ident or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    formation = texte(r.find(".//FORMATION")) or texte(r.find(".//META_JURI/JURIDICTION"))
    numero = texte(r.find(".//META_JURI/NUMERO"))
    titre = texte(r.find(".//META_JURI/TITRE")) or f"Cour de cassation, {formation}, {date}, n° {numero}"
    matiere = "Jurisprudence"
    for mot, m in MATIERES:
        if mot in formation.lower():
            matiere = m
            break
    resume = texte(r.find(".//SOMMAIRE")) or texte(r.find(".//ANA"))
    return {"id": f"cass:{ident}", "source": SOURCE, "date": date, "titre": titre[:220],
            "matiere": matiere, "url": f"https://www.legifrance.gouv.fr/juri/id/{ident}",
            "resume": resume[:300]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limite", type=int, default=0, help="arrêt après N fichiers XML (test)")
    limite = p.parse_args().limite

    url = trouver_archive()
    print("Archive :", url)
    par_annee, vus, ignores = defaultdict(list), 0, 0
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with tarfile.open(fileobj=r.raw, mode="r|gz") as tar:
            for m in tar:
                if not (m.isfile() and m.name.endswith(".xml")):
                    continue
                vus += 1
                try:
                    e = lire(tar.extractfile(m).read())
                except ET.ParseError:
                    e = None
                if e:
                    par_annee[e["date"][:4]].append(e)
                else:
                    ignores += 1
                if vus % 10000 == 0:
                    print(f"{vus} fichiers lus…", flush=True)
                if limite and vus >= limite:
                    break

    os.makedirs(SORTIE, exist_ok=True)
    comptes = {}
    for an, liste in sorted(par_annee.items()):
        liste.sort(key=lambda x: x["date"], reverse=True)
        with open(f"{SORTIE}/{an}.json", "w", encoding="utf-8") as f:
            json.dump(liste, f, ensure_ascii=False, separators=(",", ":"))
        comptes[an] = len(liste)
    with open(f"{SORTIE}/annees.json", "w", encoding="utf-8") as f:
        json.dump(comptes, f)
    print(f"Terminé : {vus} fichiers lus, {sum(comptes.values())} décisions, {ignores} ignorés.")
    print("Années couvertes :", min(comptes, default="-"), "->", max(comptes, default="-"))


if __name__ == "__main__":
    main()
