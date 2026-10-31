import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import update_wrf_meteogalicia as w  # noqa: E402


class Conversions(unittest.TestCase):
    def test_unites(self):
        v = w.ligne({"temp": 288.15, "rh": 0.8, "prec": 1.234, "cft": 0.5, "mod": 10.0, "dir": 271.4, "wind_gust": 20.0, "mslp": 101325.0, "cape": 850.4, "conv_prec": 0.5, "snow_prec": 0.0})
        i = w.IDX
        self.assertEqual(v[i["temperature_c"]], 15.0)
        self.assertEqual(v[i["humidity_pct"]], 80)
        self.assertEqual(v[i["precipitation_mm"]], 1.23)
        self.assertEqual(v[i["cloud_cover_pct"]], 50)
        self.assertEqual(v[i["wind_speed_kmh"]], 36)
        self.assertEqual(v[i["wind_gust_kmh"]], 72)
        self.assertEqual(v[i["wind_direction_deg"]], 271)
        self.assertEqual(v[i["pressure_hpa"]], 1013)
        self.assertEqual(v[i["cape_jkg"]], 850)
        self.assertEqual(len(v), 33)

    def test_valeurs_absentes(self):
        v = w.ligne({})
        self.assertTrue(all(x is None for x in v))

    def test_pas_de_valeur_negative(self):
        v = w.ligne({"prec": -0.01, "snow_prec": -1.0})
        self.assertEqual(v[w.IDX["precipitation_mm"]], 0.0)
        self.assertEqual(v[w.IDX["snowfall_mm"]], 0.0)


class RisqueNeige(unittest.TestCase):
    def test_niveaux(self):
        self.assertEqual(w.risque_neige(10, 0, 0), 0)
        self.assertEqual(w.risque_neige(1, 0.5, 0), 1)
        self.assertEqual(w.risque_neige(0, 2, 0.5), 2)
        self.assertEqual(w.risque_neige(-2, 3, 1.0), 3)
        self.assertEqual(w.risque_neige(-2, 9, 3.0), 4)
        self.assertIsNone(w.risque_neige(None, 1, 1))


class Rattachement(unittest.TestCase):
    def test_plus_proche(self):
        lats = [[42.0, 42.0], [43.0, 43.0]]
        lons = [[2.0, 3.0], [2.0, 3.0]]
        self.assertEqual(w.plus_proche(42.9, 2.9, lats, lons), (1, 1))
        self.assertEqual(w.plus_proche(42.1, 2.1, lats, lons), (0, 0))

    def test_runs(self):
        txt = '<dataset name="Spain_2026103012.nc"/><dataset name="Spain_2026103100.nc"/><dataset name="Spain_2026103100.nc"/>'
        self.assertEqual(w.derniers_runs(txt), ["2026103100", "2026103012"])


if __name__ == "__main__":
    unittest.main()
