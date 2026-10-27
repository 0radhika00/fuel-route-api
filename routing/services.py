import requests
import json
from pprint import pprint
from sklearn.neighbors import BallTree
import math
import numpy as np
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

BUFFER_MILES = 20 
EARTH_RADIUS_MILES = 3958.8
MAX_CAPACITY = 500
MILES_PER_GALLON = 10
OSRM_BASE_URL = "https://router.project-osrm.org"
NOMINATION_URL = "https://nominatim.openstreetmap.org/search"
FILE_PATH = "data/stations.json"

class DataSource(ABC):
    @abstractmethod
    def get_data(self):
        pass

class StationDataSource(DataSource):
    def __init__(self,FILE_PATH):
        self.filepath = FILE_PATH

    def get_data(self):
        with open(self.filepath) as f:
            station_data = json.load(f)
        logger.debug("Station data loaded: %d", len(station_data))
        return station_data

def geocoding(address):

    headers = {
        "User-Agent": "FuelRouteDjangoApp/1.0 (workradhika12@gmail.com)" 
    }
    
    params = {
        "q": address,
        "format": "json",
        "limit": 1 
    }

    try:
        response = requests.get(NOMINATION_URL,headers=headers,params=params,timeout=10)
        response.raise_for_status()
        data = response.json()
        if data:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            return {"lat": lat, "lon": lon}
        else:
            return None
    except requests.exceptions.RequestException as e:
        logger.exception(f"Error occurred during geocoding: {e}")

def convert(data):

    data["routes"][0]["distance"] = data["routes"][0]["distance"]/1609.34
    data["routes"][0]["duration"] = data["routes"][0]["duration"]/3600
    
    return data

def get_map(start,end,profile="driving"):

    start_coordinates = geocoding(start)
    end_cordinates = geocoding(end)
    coordinates = f"{start_coordinates['lon']},{start_coordinates['lat']};{end_cordinates['lon']},{end_cordinates['lat']}"
    
    url = f"{OSRM_BASE_URL}/route/v1/{profile}/{coordinates}?overview=full&geometries=geojson"

    try:
        response = requests.get(url,timeout=10)
        response.raise_for_status()
        data = response.json()
        data = convert(data)

        return {"distance": data["routes"][0]["distance"], "duration": data["routes"][0]["duration"], "geometry": data["routes"][0]["geometry"]}
    except requests.exceptions.RequestException as e:
        logger.exception(f"Error occurred during routing: {e}")

def get_cumulative_distance(path_coordinates):

    #convert routecordinates to generate cumulative distance
    cumulative_distance = [0.0]

    for coord in range(1,len(path_coordinates)):
        prevlong , prevlat = path_coordinates[coord-1]
        curlong , curlat = path_coordinates[coord]

        #convert to radians
        prevlong_rad,prevlat_rad = math.radians(prevlong), math.radians(prevlat)
        curlong_rad,curlat_rad = math.radians(curlong), math.radians(curlat)

        #Haversine formula differences
        dlon = curlong_rad - prevlong_rad
        dlat = curlat_rad - prevlat_rad

        #Haversine formula
        a = math.sin(dlat / 2)**2 + math.cos(prevlat_rad) * math.cos(curlat_rad) * math.sin(dlon / 2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        # 4. Distance for this single segment in miles
        segment_miles = c * EARTH_RADIUS_MILES

        
        new_segment = round((cumulative_distance[coord-1]+segment_miles),2)
        cumulative_distance.append(new_segment)

 
    logger.debug("Cummulative_distance: %d", len(cumulative_distance))
    return cumulative_distance

def create_tree(path_coordinates):

    route_data = [[i[1],i[0]] for i in path_coordinates]
    route_radians = np.radians(route_data)

    #ball tree
    tree = BallTree(route_radians, metric='haversine')
    logger.debug("Tree created")
    return tree
    
# def load_data(file_path):

#     with open(file_path) as f:
#         station_data = json.load(f)
#     logger.debug("Station data loaded: %d", len(station_data))
#     return station_data

def generate_idx(station_data,tree):

    station_radians = np.radians(station_data)
    distance_rad , idx = tree.query(station_radians, k=1)
    return distance_rad , idx

def get_nearby_stations(path_coordinates,cumulative_distance):


    tree = create_tree(path_coordinates)
    station_data = StationDataSource(FILE_PATH)
    station_data = station_data.get_data()
    station_data_lat_long = [[i['lat'],i['lon']] for i in station_data]
    distance_rad , idx = generate_idx(station_data_lat_long,tree)

    nearby_stations = []

    for i in range(len(distance_rad)):
        station_distance_in_miles = distance_rad[i]*EARTH_RADIUS_MILES
        if station_distance_in_miles<=BUFFER_MILES:
            route_index = idx[i].item()
            nearby_stations.append({"cummulative_idx":cumulative_distance[route_index],
                                    "station_distance_in_miles":station_distance_in_miles.item(),
                                    "station_price":station_data[i]["price"],
                                    "station_name":station_data[i]["name"],
                                    "station_address":str(station_data[i]["address"] +" "+ station_data[i]["city"] +" "+ station_data[i]["state"])})

    logger.info("Nearby Stations Created: %d", len(nearby_stations))
    return nearby_stations

def generate_filtered_stations(nearby_stations):
    """Sort by route position and drop stations that are strictly worse
    than another station at the same mile marker (price AND detour)."""
    by_idx = {}
    for s in sorted(nearby_stations, key=lambda d: d['cummulative_idx']):
        by_idx.setdefault(s['cummulative_idx'], []).append(s)

    filtered_stations = []
    for idx in sorted(by_idx):
        group = by_idx[idx]
        for s in group:
            dominated = any(
                o is not s
                and o['station_price'] <= s['station_price']
                and o['station_distance_in_miles'] <= s['station_distance_in_miles']
                and (o['station_price'] < s['station_price']
                     or o['station_distance_in_miles'] < s['station_distance_in_miles'])
                for o in group
            )
            if not dominated:
                filtered_stations.append(s)

    logger.info("Filtered Stations Created: %d", len(filtered_stations))
    return filtered_stations


def reach(station):
    # range left after fueling here: the off-route detour already used some
    return MAX_CAPACITY - 2 * station['station_distance_in_miles']


def leg_cost(station, end_idx):
    # fuel for the leg leaving `station` (its own detour included), at its price
    miles = end_idx - station['cummulative_idx'] + 2 * station['station_distance_in_miles']
    return miles / MILES_PER_GALLON * station['station_price']


def list_of_stations(nearby_stations, total_distance):
    # Trip fits on the starting tank: no stops needed.
    if total_distance <= MAX_CAPACITY:
        logger.info("Route of %.1f miles fits on one tank; no stops needed", total_distance)
        return [], 0.0

    stations = generate_filtered_stations(nearby_stations)
    n = len(stations)

    INF = float('inf')
    dp = [INF] * n        # dp[j] = cheapest cost to be at station j
    parent = [-1] * n     # previous stop on that cheapest path (-1 = start)

    for j in range(n):
        if stations[j]['cummulative_idx'] <= MAX_CAPACITY:
            dp[j] = 0.0   # first tank is free
        # only stations within MAX_CAPACITY behind j can possibly reach it
        i = j - 1
        while i >= 0 and stations[j]['cummulative_idx'] - stations[i]['cummulative_idx'] <= MAX_CAPACITY:
            gap = stations[j]['cummulative_idx'] - stations[i]['cummulative_idx']
            if dp[i] < INF and gap <= reach(stations[i]):
                candidate = dp[i] + leg_cost(stations[i], stations[j]['cummulative_idx'])
                if candidate < dp[j]:
                    dp[j] = candidate
                    parent[j] = i
            i -= 1

    # choose the last stop: it must be able to reach the destination
    total_cost, last = INF, -1
    for i in range(n):
        if dp[i] < INF and total_distance - stations[i]['cummulative_idx'] <= reach(stations[i]):
            candidate = dp[i] + leg_cost(stations[i], total_distance)
            if candidate < total_cost:
                total_cost, last = candidate, i

    if last == -1:
        logger.warning("No feasible fuel stops for a %.1f mile route (%d candidate stations)",
                       total_distance, n)
        raise ValueError("No feasible set of fuel stops for this route")

    final_list = []
    k = last
    while k != -1:
        final_list.append(stations[k])
        k = parent[k]
    final_list.reverse()

    logger.info("Final Stations Created: %d, total cost %.2f", len(final_list), total_cost)
    return final_list, round(total_cost, 2)







    


   


  
















