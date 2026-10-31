"""WRF-ARW de MeteoGalicia (domaine « Spain », 12 km, 96 h, runs de 00 h et 12 h UTC) -> JSON départemental v3 des Pyrénées-Orientales.

Source : sorties NetCDF du WRF opérationnel de MeteoGalicia, lues par le service NetCDF Subset d'un serveur THREDDS (miroir IH Cantabria).
On y découpe la boîte du département 66, on convertit les unités, on rattache chaque commune à la maille la plus proche et on écrit
`build/departements/66.json`, au même format que les autres modèles (AROME, HARMONIE, ICON…) : 33 colonnes dans le même ordre, null
pour ce que le modèle ne fournit pas.

Usage : python scripts/update_wrf_meteogalicia.py [--out-dir build] [--run AAAAMMJJHH]
Code de sortie : 0 publié, 2 aucune publication (source indisponible ou incomplète : on garde la dernière valide).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

THREDDS = "https://ihthredds.ihcantabria.com/thredds"
CATALOGUE = f"{THREDDS}/catalog/meteogaliciawrf/Spain/catalog.xml"
FICHIER = f"{THREDDS}/ncss/grid/meteogaliciawrf/Spain/Spain_{{run}}.nc"
BOITE = {"north": 43.1, "south": 42.2, "east": 3.4, "west": 1.5}
VARIABLES = ["temp", "prec", "conv_prec", "snow_prec", "wind_gust", "mod", "dir", "cape", "rh", "mslp", "cft", "topo", "lat", "lon"]
PAS_MIN = 90  # un run complet fait 96 échéances ; en dessous, le fichier est tronqué

COLONNES = [
    "temperature_c", "humidity_pct", "precipitation_mm", "cloud_cover_pct", "wind_speed_kmh", "wind_direction_deg", "wind_gust_kmh",
    "pressure_hpa", "visibility_km", "condition_code", "pressure_surface_hpa", "dewpoint_c", "precipitation_total_mm", "cloud_low_pct",
    "cloud_mid_pct", "cloud_high_pct", "cape_jkg", "reflectivity_dbz", "graupel_mm", "thunder_risk_code", "lcl_m", "lightning_score",
    "hail_risk_code", "convective_precipitation_mm", "storm_type_code", "snow_risk_code", "snowfall_mm", "snow_fresh_cm", "snow_depth_cm",
    "snow_water_equivalent_mm", "snow_stick_risk_code", "snow_phase_code", "snowfall_total_mm",
]
IDX = {c: i for i, c in enumerate(COLONNES)}
SOURCE = "WRF-ARW 12 km de MeteoGalicia (Xunta de Galicia), réutilisation d'informations du secteur public avec mention de la source"


def arrondi(v: float | None, n: int = 1) -> float | None:
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(float(v), n)


def risque_neige(temp_c: float | None, pluie_mm: float | None, neige_mm: float | None) -> int | None:
    """Même règle que le pipeline AROME : 0 aucun à 4 très fort, d'après la neige du pas, la pluie et la température."""
    if temp_c is None or pluie_mm is None or neige_mm is None:
        return None
    ratio = 15.0 if temp_c <= -10 else 12.0 if temp_c <= -5 else 10.0 if temp_c <= 0 else 6.0 if temp_c <= 1.5 else 2.0
    frais_cm = max(neige_mm, 0.0) * ratio / 10.0
    if frais_cm >= 3.0 or (pluie_mm >= 8 and temp_c <= -1):
        return 4
    if frais_cm >= 1.0 or (pluie_mm >= 3 and temp_c <= 0):
        return 3
    if frais_cm >= 0.3 or (pluie_mm >= 1 and temp_c <= 0.5):
        return 2
    if neige_mm >= 0.03 or (pluie_mm >= 0.2 and temp_c <= 1.5):
        return 1
    return 0


def ligne(brut: dict[str, float | None]) -> list[float | int | None]:
    """33 valeurs d'un point et d'une échéance, d'après les valeurs brutes du WRF (unités de la source)."""
    v: list[float | int | None] = [None] * len(COLONNES)
    t = brut.get("temp")
    temp_c = None if t is None else t - 273.15
    v[IDX["temperature_c"]] = arrondi(temp_c)
    rh = brut.get("rh")
    v[IDX["humidity_pct"]] = None if rh is None else arrondi(min(max(rh, 0.0), 1.0) * 100, 0)
    pluie = brut.get("prec")
    v[IDX["precipitation_mm"]] = None if pluie is None else arrondi(max(pluie, 0.0), 2)
    nuages = brut.get("cft")
    v[IDX["cloud_cover_pct"]] = None if nuages is None else arrondi(min(max(nuages, 0.0), 1.0) * 100, 0)
    vent = brut.get("mod")
    v[IDX["wind_speed_kmh"]] = None if vent is None else arrondi(vent * 3.6, 0)
    v[IDX["wind_direction_deg"]] = arrondi(brut.get("dir"), 0)
    raf = brut.get("wind_gust")
    v[IDX["wind_gust_kmh"]] = None if raf is None else arrondi(raf * 3.6, 0)
    p = brut.get("mslp")
    v[IDX["pressure_hpa"]] = None if p is None else arrondi(p / 100.0, 0)
    v[IDX["cape_jkg"]] = arrondi(brut.get("cape"), 0)
    conv = brut.get("conv_prec")
    v[IDX["convective_precipitation_mm"]] = None if conv is None else arrondi(max(conv, 0.0), 2)
    neige = brut.get("snow_prec")
    v[IDX["snowfall_mm"]] = None if neige is None else arrondi(max(neige, 0.0), 2)
    v[IDX["snow_risk_code"]] = risque_neige(temp_c, pluie, neige)
    return v


def plus_proche(lat: float, lon: float, lats, lons) -> tuple[int, int]:
    """Indice (j, i) de la maille la plus proche, par distance sur la sphère (haversine) ; `lats` et `lons` sont des tableaux 2D."""
    meilleur, ij = float("inf"), (0, 0)
    r = math.pi / 180
    for j in range(len(lats)):
        for i in range(len(lats[j])):
            la, lo = float(lats[j][i]), float(lons[j][i])
            a = math.sin((la - lat) * r / 2) ** 2 + math.cos(lat * r) * math.cos(la * r) * math.sin((lo - lon) * r / 2) ** 2
            if a < meilleur:
                meilleur, ij = a, (j, i)
    return ij


def derniers_runs(catalogue: str | None = None) -> list[str]:
    """Runs disponibles sur le serveur (AAAAMMJJHH), du plus récent au plus ancien."""
    txt = catalogue if catalogue is not None else requests.get(CATALOGUE, timeout=60).text
    return sorted(set(re.findall(r"Spain_(20\d{8})\.nc", txt)), reverse=True)


def telecharger(run: str, dossier: Path) -> Path:
    debut = datetime.strptime(run, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    params = [("var", v) for v in VARIABLES] + list(BOITE.items()) + [
        ("time_start", (debut + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("time_end", (debut + timedelta(hours=96)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("accept", "netcdf4"),
    ]
    r = requests.get(FICHIER.format(run=run), params=params, timeout=300)
    r.raise_for_status()
    chemin = dossier / f"wrf_{run}.nc"
    chemin.write_bytes(r.content)
    return chemin


def construire(chemin: Path, run: str, communes: list[list]) -> dict:
    import netCDF4  # noqa: PLC0415 - dépendance lourde, importée à l'usage
    import numpy as np  # noqa: PLC0415

    ds = netCDF4.Dataset(chemin)
    try:
        temps = ds.variables["time"]
        dates = netCDF4.num2date(temps[:], temps.units, only_use_cftime_datetimes=False, only_use_python_datetimes=True)
        if len(dates) < PAS_MIN:
            raise RuntimeError(f"run {run} incomplet : {len(dates)} échéances")
        lats = np.asarray(ds.variables["lat"][:], dtype=float)
        lons = np.asarray(ds.variables["lon"][:], dtype=float)
        topo = np.asarray(ds.variables["topo"][:], dtype=float)
        if topo.ndim == 3:
            topo = topo[0]
        champs = {n: np.ma.filled(np.ma.asarray(ds.variables[n][:], dtype=float), np.nan) for n in VARIABLES if n not in ("lat", "lon", "topo")}
    finally:
        ds.close()

    # Maille la plus proche de chaque commune ; seules les mailles utilisées sont publiées.
    rattache = [plus_proche(c[4], c[5], lats, lons) for c in communes]
    utilises = sorted(set(rattache))
    index = {ij: k for k, ij in enumerate(utilises)}
    points = [[j * 1000 + i, round(float(lats[j][i]), 5), round(float(lons[j][i]), 5), int(round(float(topo[j][i])))] for j, i in utilises]
    prevision = []
    for t, d in enumerate(dates):
        lignes = []
        for j, i in utilises:
            brut = {n: (None if not math.isfinite(float(champs[n][t][j][i])) else float(champs[n][t][j][i])) for n in champs}
            lignes.append(ligne(brut))
        prevision.append([d.strftime("%Y-%m-%dT%H:%M:%SZ"), lignes])
    return {
        "schema_version": 3,
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "department": "66",
        "model": {"name": "WRF-ARW MeteoGalicia 12 km", "run_time": datetime.strptime(run, "%Y%m%d%H").strftime("%Y-%m-%dT%H:00:00Z"), "source": SOURCE},
        "columns": {"values": COLONNES, "communes": ["code_insee", "name", "postal_codes", "population", "latitude", "longitude", "point_id"]},
        "points": points,
        "communes": [[c[0], c[1], c[2], c[3], c[4], c[5], index[ij]] for c, ij in zip(communes, rattache)],
        "forecast": prevision,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default="build")
    p.add_argument("--run", help="forcer un run (AAAAMMJJHH)")
    a = p.parse_args()
    communes = json.loads((Path(__file__).resolve().parent.parent / "config" / "communes-66.json").read_text(encoding="utf-8"))
    try:
        runs = [a.run] if a.run else derniers_runs()
    except requests.RequestException as e:
        print(f"Catalogue MeteoGalicia injoignable : {e}", file=sys.stderr)
        return 2
    for run in runs[:3]:  # le plus récent peut être en cours de copie : on essaie les deux précédents
        try:
            with tempfile.TemporaryDirectory() as tmp:
                donnees = construire(telecharger(run, Path(tmp)), run, communes)
        except (requests.RequestException, RuntimeError, OSError, KeyError) as e:
            print(f"Run {run} inutilisable : {e}", file=sys.stderr)
            continue
        sortie = Path(a.out_dir) / "departements"
        sortie.mkdir(parents=True, exist_ok=True)
        (sortie / "66.json").write_text(json.dumps(donnees, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        (Path(a.out_dir) / "index.json").write_text(
            json.dumps({"model": donnees["model"], "generated_at": donnees["generated_at"], "model_run": donnees["model"]["run_time"], "departments": ["66"]}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"WRF MeteoGalicia run {run} : {len(donnees['points'])} points, {len(donnees['forecast'])} échéances, {len(communes)} communes")
        return 0
    print("Aucun run utilisable : pas de publication", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
