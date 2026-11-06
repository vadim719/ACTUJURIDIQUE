// Construit le moteur de recherche (dossier "pagefind") à partir de indexsrc.jsonl
import * as pagefind from "pagefind";
import fs from "node:fs";
import readline from "node:readline";

const { index } = await pagefind.createIndex({ forceLanguage: "fr" });

const lignes = readline.createInterface({
  input: fs.createReadStream("indexsrc.jsonl", { encoding: "utf8" }),
  crlfDelay: Infinity,
});

let n = 0;
let erreurs = 0;
for await (const ligne of lignes) {
  if (!ligne.trim()) continue;
  const d = JSON.parse(ligne);
  const { errors } = await index.addCustomRecord({
    url: d.url,
    content: `${d.titre}. ${d.texte}`,
    language: "fr",
    meta: { title: d.titre, date: d.date, matiere: d.matiere, source: d.source },
    filters: { annee: [d.date.slice(0, 4)], matiere: [d.matiere] },
    sort: { date: d.date },
  });
  if (errors && errors.length) {
    erreurs++;
    if (erreurs <= 5) console.error("Erreur d'indexation :", errors);
  }
  n++;
  if (n % 10000 === 0) console.log(`${n} décisions indexées…`);
}

const res = await index.writeFiles({ outputPath: "pagefind" });
if (res.errors && res.errors.length) {
  console.error("Erreur d'écriture de l'index :", res.errors);
  process.exit(1);
}
await pagefind.close();
console.log(`Index terminé : ${n} décisions indexées, ${erreurs} erreur(s).`);
