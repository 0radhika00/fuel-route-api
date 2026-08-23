# fuelroute

A Django API that plans a driving route between two US locations and
picks cost-effective fuel stops along the way, given a vehicle with a
500-mile range and 10 MPG fuel economy.

## Quick start

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# One-time: turn the raw price CSV into a clean, geocoded fixture.
# (Already run once and committed as data/stations.json -- only needed
# again if the raw CSV changes.)
python manage.py build_stations --input data/fuel-prices-raw.csv --output data/stations.json

python manage.py runserver 8001
```

Then:

```
POST /api/route/
start=Chicago, 
end=Los Angeles, CA
```

### Optional query params

| Param | Default | Meaning |
|---|---|---|
| `MAX_CAPACITY` | 500 | Vehicle's max range in miles between fill-ups |
| `MILES_PER_GALLON` | 10 | Miles per gallon |
| `BUFFER_MILES` | 20 | How far (miles) off the route a station can be and still be considered |

### Example response (trimmed)

```json
{
  
    "final_stations": [
        {
            "cummulative_idx": 484.85,
            "station_distance_in_miles": 1.924646834498902,
            "station_price": 2.921,
            "station_name": "KUM & GO #0370",
            "station_address": "I-80, EXIT 439 & SR-370 Gretna NE"
        }
    ],
    "total_price": 517.29,
  "geometry": {"type": "LineString", "coordinates": [[-87.63, 41.88], "..."]},
}
```

`geometry` is a GeoJSON `LineString` -- drop it straight into
Leaflet/Mapbox GL/etc. to render the map.


**Choosing fuel stops: greedy, cheapest-in-reachable-window.** From the
current position, look at every candidate station within the next
`MAX_CAPACITY` miles and pick the cheapest one; repeat until the
remaining distance to the destination fits within one more tank. This
guarantees no leg between stops (or from start/finish) ever exceeds
`MAX_CAPACITY`. If a stretch of route has no candidate station within
range at all ("fuel desert"), the planner falls back to the nearest
station beyond that point and surfaces a `warnings` entry rather than
failing the whole request.

**Cost model.** The vehicle starts the trip with a full tank, so the
first leg (start -> first fuel stop) is free. Each subsequent leg's
fuel is charged at the price of the stop where it was purchased. A
trip that fits within one tank (`total_distance <= max_range`) needs no
stop at all and costs $0.

## Why greedy instead of DP

- Both approaches are choosing a subset of candidate stations along a line such that consecutive gaps never exceed 500 miles, minimizing total cost. Here's the reasoning for greedy:

- The greedy is actually near-optimal for this specific cost structure. Because the vehicle always fills up "enough for the next leg" and the decision at each stop is independent of what happens further down the line (any reachable stop resets your range to a fresh 500), the classic result for this class of problem ("minimize fuel cost with a hard range constraint, refuel amounts freely chosen") is that a greedy strategy — go as far as you can, then buy from the cheapest station reachable within range — is provably optimal or very close to it, provided you're allowed to not-fill-completely (buy just enough to reach the next stop). That's exactly the assumption I'm using: gallons purchased at each stop = exactly what's needed for the next leg, not a forced full tank.

- Where greedy can be suboptimal: if the algorithm is forced to always top off to a full tank (not just "enough for the next leg"), then DP does matter — because overbuying at an expensive station now to skip a cheap one 50 miles later becomes a real tradeoff, and that requires comparing full future paths, which greedy can't see. My implementation avoids that whole complication by choosing the "buy exactly enough for the next leg" model, which is also more realistic for cost accounting and keeps greedy essentially correct.

