import requests
import json
from pprint import pprint
from sklearn.neighbors import BallTree
import math
import numpy as np
import logging

logger = logging.getLogger(__name__)

BUFFER_MILES = 20 
EARTH_RADIUS_MILES = 3958.8
MAX_CAPACITY = 500
MILES_PER_GALLON = 10
OSRM_BASE_URL = "https://router.project-osrm.org"
NOMINATION_URL = "https://nominatim.openstreetmap.org/search"

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

def get_map(start,end,profile="driving"):

    start_coordinates = geocoding(start)
    end_cordinates = geocoding(end)
    coordinates = f"{start_coordinates['lon']},{start_coordinates['lat']};{end_cordinates['lon']},{end_cordinates['lat']}"
    
    url = f"{OSRM_BASE_URL}/route/v1/{profile}/{coordinates}?overview=full&geometries=geojson"

    try:
        response = requests.get(url,timeout=10)
        response.raise_for_status()
        data = response.json()

        return {"distance": data["routes"][0]["distance"]/1609.34, "duration": data["routes"][0]["duration"]/3600, "geometry": data["routes"][0]["geometry"]}
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

def get_nearby_stations(path_coordinates,cumulative_distance):


    route_data = [[i[1],i[0]] for i in path_coordinates]
    route_radians = np.radians(route_data)

    #ball tree
    tree = BallTree(route_radians, metric='haversine')
    logger.debug("Tree created")
    with open('data/stations.json') as f:
        station_data = json.load(f)

    station_data_lat_long = [[i['lat'],i['lon']] for i in station_data]
    station_radians = np.radians(station_data_lat_long)

    distance_rad , idx = tree.query(station_radians, k=1)
    # print(len(distance_rad))
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


def list_of_stations(nearby_stations,total_distance):

    sorted_dic_idx = sorted(nearby_stations, key=lambda d: d['cummulative_idx'])
    filtered_data = {}

    
    for station in sorted_dic_idx:
        idx = station['cummulative_idx']
        # print(idx, station['station_price'])
        if idx not in filtered_data or station['station_price'] < filtered_data[idx]['station_price']:
            filtered_data[idx] = station

    filtered_stations = list(filtered_data.values())

    # for _ in sorted_dic_idx:
    #     print(_)

    # for _ in filtered_stations:
    #     print(_)
    final_list = []
    total_cost = 0
    position = 0            # cumulative distance where we currently stand
    i = 0
    n = len(filtered_stations)
    edge_capacity = 0

    while position < total_distance:

        if total_distance - position <= MAX_CAPACITY - edge_capacity:
            break

        intial_price = 1e9
        intial_station = None

        j = i
        while j < n and filtered_stations[j]['cummulative_idx'] <= position + MAX_CAPACITY - edge_capacity:
            if filtered_stations[j]['cummulative_idx'] > position:
                if filtered_stations[j]['station_price'] < intial_price:
                    intial_price = filtered_stations[j]['station_price']
                    intial_station = filtered_stations[j]
            j += 1

        if intial_station is None:
            break

        if final_list:
            prev_stop = final_list[-1]
            leg_miles = intial_station['cummulative_idx'] - prev_stop['cummulative_idx']
            detour_miles = 2 * prev_stop['station_distance_in_miles']
            total_cost += (leg_miles+detour_miles) / MILES_PER_GALLON * prev_stop['station_price']

        final_list.append(intial_station)
        position = intial_station['cummulative_idx']
        edge_capacity = 2*intial_station['station_distance_in_miles']

        while i < n and filtered_stations[i]['cummulative_idx'] <= position:
            i += 1

    if final_list:
        last_stop = final_list[-1]
        leg_miles = total_distance - position
        detour_miles = 2 * last_stop['station_distance_in_miles']
        total_cost += ((leg_miles + detour_miles) / MILES_PER_GALLON) * last_stop['station_price']

    logger.info("Final Stations Created: %d", len(final_list))
    return final_list, round(total_cost, 2)







    


   


  
















