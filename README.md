# WRF MeteoGalicia 12 km — Pyrénées-Orientales

Prévisions du modèle WRF-ARW opérationnel de MeteoGalicia (domaine « Spain », 12 km, 96 h, deux runs par jour à 00 h et 12 h UTC),
découpées sur le département 66 et publiées au **JSON départemental v3** partagé avec les autres modèles (AROME, HARMONIE, ICON, UKMO…).

- Données : branche `data`, fichier `departements/66.json` (33 colonnes dans l'ordre commun, `null` pour ce que le modèle ne fournit pas).
- Fournies : température, humidité, pluie par pas d'une heure, nuages, vent, direction, rafales, pression, CAPE, pluie convective, neige et un risque de neige calculé comme pour AROME.
- Non fournies : visibilité, point de rosée, code de temps, risque d'orage (le consensus s'appuie alors sur la CAPE).
- Workflow : `.github/workflows/update-wrf-meteogalicia.yml` (4 passages par jour, publication idempotente, dernière publication valide conservée si la source tombe).
- Source : sorties NetCDF de MeteoGalicia (Xunta de Galicia), lues par le service NetCDF Subset d'un serveur THREDDS miroir (IH Cantabria).

## Attribution

Données : MeteoGalicia — Xunta de Galicia. Réutilisation d'informations du secteur public avec mention de la source ; les conditions exactes
de réutilisation sont à confirmer auprès de MeteoGalicia avant tout usage commercial. Le modèle est un 12 km : à utiliser comme un membre du
consensus, pas comme une prévision locale détaillée.

## Utilisation locale

```bash
pip install -r requirements.txt
python -m unittest discover -s tests
python scripts/update_wrf_meteogalicia.py --out-dir build
```
