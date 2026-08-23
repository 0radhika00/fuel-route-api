"""
One-time build step: turn the raw OPIS fuel-price CSV into a clean,
geocoded stations.json fixture that ships with the app.

"""
import csv
import json
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

import zipcodes


class Command(BaseCommand):
    help = "Geocode and dedupe the raw fuel-price CSV into data/stations.json"

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            default=str(Path(settings.BASE_DIR) / "data" / "fuel-prices-raw.csv"),
        )
        parser.add_argument(
            "--output",
            default=str(Path(settings.BASE_DIR) / "data" / "stations.json"),
        )

    def handle(self, *args, **options):
        input_path = Path(options["input"])
        output_path = Path(options["output"])

        self.stdout.write(f"Reading {input_path} ...")
        with open(input_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.stdout.write(f"  {len(rows)} raw rows")

        # --- Step 1: dedupe by OPIS Truckstop ID, take min price ---
        by_id = {}
        min_price = {}
        for r in rows:
            sid = r["OPIS Truckstop ID"].strip()
            price = float(r["Retail Price"])
            if sid not in by_id:
                by_id[sid] = r
                min_price[sid] = price
            else:
                min_price[sid] = min(min_price[sid], price)

        self.stdout.write(f"  {len(by_id)} unique truckstop IDs")

        # --- Step 2: build a case-insensitive (city, state) -> centroid lookup ---
        # (averaging every zip's lat/lon for that city/state gives a reasonable
        # city-center point; exact enough for route-corridor filtering)
        self.stdout.write("Building city/state geocode lookup from zip data ...")
        sums = defaultdict(lambda: [0.0, 0.0, 0])
        for z in zipcodes.list_all():
            try:
                lat, lon = float(z["lat"]), float(z["long"])
            except (TypeError, ValueError):
                continue
            key = (z["city"].strip().upper(), z["state"].strip().upper())
            s = sums[key]
            s[0] += lat
            s[1] += lon
            s[2] += 1
        centroid = {k: (v[0] / v[2], v[1] / v[2]) for k, v in sums.items()}

        # --- Step 3: geocode each station, skip ones we can't place ---
        stations = []
        skipped = 0
        for sid, r in by_id.items():
            city = r["City"].strip()
            state = r["State"].strip()
            key = (city.upper(), state.upper())
            latlon = centroid.get(key)
            if latlon is None:
                skipped += 1
                continue
            stations.append(
                {
                    "id": sid,
                    "name": r["Truckstop Name"].strip(),
                    "address": r["Address"].strip(),
                    "city": city,
                    "state": state,
                    "price": round(min_price[sid], 3),
                    "lat": round(latlon[0], 5),
                    "lon": round(latlon[1], 5),
                }
            )

        # self.stdout.write(
        #     f"  geocoded {len(stations)} stations, skipped {skipped} "
        #     f"(mostly non-US/Canadian entries in the raw data)"
        # )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(stations, f)

        # self.stdout.write(self.style.SUCCESS(f"Wrote {output_path} ({len(stations)} stations)"))
