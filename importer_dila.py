#!/usr/bin/env python3
"""Import des archives DILA (base CASS : Cour de cassation, depuis 1960)
-> data/ANNEE.json (un fichier par année) + data/annees.json (nombre par année)
   + indexsrc.jsonl (sommaires complets, pour construire le moteur de recherche)

Le script lit l'archive globale puis, si elles existent, toutes les archives de
mise à jour publiées ensuite par la DILA (nouvelles décisions, corrections, suppressions).

Usage :
  python importer_dila.py --limite 2000   # test rapide (archive globale seulement)
  python importer_dila.py                 # import complet + mises à jour
"""
import argparse
import json
import os
import re
import tarfile
import xml.etree.ElementTree as ET
from collections import defaultdict

import requests

BASE = os.environ.get("DILA_BASE", "https://echanges.dila.gouv.fr/OPENDATA/CASS/")
SORTIE = "data"
SOURCE = "Cour de cassation (Bulletin)"

# mot-clé dans la formation -> matière (à ajuster)
MATIERES = [("sociale", "Travail"), ("criminelle", "Pénal"), ("commerciale", "Commercial"),
            ("mixte", "Jurisprudence"), ("plénière", "Jurisprudence"), ("civile", "Civil")]


def texte(el):
    return " ".join(" ".join(el.itertext()).split()) if el is not None else ""


def horodatage(nom):
    m = re.search(r"(\d{8}-\d{6})", nom)
    return m.group(1) if m else ""


def lister_archives():
    page = requests.get(BASE, timeout=60)
    page.raise_for_status()
    return sorted(set(re.findall(r'href="([^"?/][^"]*\.tar\.gz)"', page.text)))


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
            "resume": resume[:400], "texte": resume[:4000]}


def lire_archive(nom, docs, limite=0):
    """Lit une archive en flux et met à jour docs (id -> décision)."""
    vus = ignores = supprimes = 0
    with requests.get(BASE + nom, stream=True, timeout=120) as r:
        r.raise_for_status()
        with tarfile.open(fileobj=r.raw, mode="r|gz") as tar:
            for m in tar:
                if not m.isfile():
                    continue
                if m.name.endswith(".xml"):
                    vus += 1
                    try:
                        e = lire(tar.extractfile(m).read())
                    except ET.ParseError:
                        e = None
                    if e:
                        docs[e["id"]] = e   # une version plus récente remplace l'ancienne
                    else:
                        ignores += 1
                    if vus % 10000 == 0:
                        print(f"{vus} fichiers lus…", flush=True)
                    if limite and vus >= limite:
                        break
                elif m.name.lower().endswith(".txt") and "suppression" in m.name.lower():
                    brut = tar.extractfile(m).read().decode("utf-8", "ignore")
                    for ident in set(re.findall(r"JURITEXT\d+", brut)):
                        if docs.pop(f"cass:{ident}", None):
                            supprimes += 1
    return vus, ignores, supprimes


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limite", type=int, default=0, help="arrêt après N fichiers XML (test)")
    limite = p.parse_args().limite

    noms = lister_archives()
    globales = sorted(n for n in noms if n.startswith("Freemium_cass_global_"))
    if not globales:
        raise SystemExit(f"Aucune archive globale trouvée à {BASE}")
    globale = globales[-1]
    t0 = horodatage(globale)
    maj = sorted((n for n in noms if not n.startswith("Freemium") and horodatage(n) > t0),
                 key=horodatage)
    print("Archive globale :", globale)
    print("Derniers fichiers du dossier :", ", ".join(noms[-5:]))
    print(f"Archives de mise à jour postérieures au {t0[:8]} : {len(maj)}")

    docs = {}
    vus, ignores, supprimes = lire_archive(globale, docs, limite)
    if limite:
        print("Mode test : archives de mise à jour ignorées.")
    else:
        for i, nom in enumerate(maj, 1):
            v, ig, su = lire_archive(nom, docs)
            vus, ignores, supprimes = vus + v, ignores + ig, supprimes + su
            if i % 25 == 0 or i == len(maj):
                print(f"{i}/{len(maj)} archives de mise à jour appliquées", flush=True)

    par_annee = defaultdict(list)
    with open("indexsrc.jsonl", "w", encoding="utf-8") as idx:
        for e in docs.values():
            brut = e.pop("texte")
            idx.write(json.dumps({"url": e["url"], "titre": e["titre"], "date": e["date"],
                                  "matiere": e["matiere"], "source": e["source"],
                                  "texte": brut}, ensure_ascii=False) + "\n")
            par_annee[e["date"][:4]].append(e)

    os.makedirs(SORTIE, exist_ok=True)
    comptes = {}
    for an, liste in sorted(par_annee.items()):
        liste.sort(key=lambda x: x["date"], reverse=True)
        with open(f"{SORTIE}/{an}.json", "w", encoding="utf-8") as f:
            json.dump(liste, f, ensure_ascii=False, separators=(",", ":"))
        comptes[an] = len(liste)
    with open(f"{SORTIE}/annees.json", "w", encoding="utf-8") as f:
        json.dump(comptes, f)
    recente = max((e["date"] for l in par_annee.values() for e in l), default="-")
    print(f"Terminé : {vus} fichiers lus, {len(docs)} décisions, {ignores} ignorés, "
          f"{supprimes} supprimées.")
    print("Années couvertes :", min(comptes, default="-"), "->", max(comptes, default="-"))
    print("Décision la plus récente :", recente)


if __name__ == "__main__":
    main()
