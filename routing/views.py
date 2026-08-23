from django.shortcuts import render
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .services import get_map,get_nearby_stations,get_cumulative_distance,list_of_stations
from django.http import JsonResponse


def home_view(request):
    return render(request, 'routing/show.html')

@csrf_exempt
def get_map_view(request):

    start = request.POST.get('start')
    end = request.POST.get('end')
    try:
        if start and end:
            router_data = get_map(start, end)
            needed_router_data = router_data['geometry']['coordinates']
            cumulative_distance = get_cumulative_distance(needed_router_data)
            nearby_stations = get_nearby_stations(needed_router_data,cumulative_distance)
            final_stations,total_price = list_of_stations(nearby_stations,router_data['distance'])
     
            if final_stations:
                return JsonResponse({'final_stations': final_stations,  'total_price': total_price, 'router_data': router_data})
            else:
                return JsonResponse({ 'router_data': router_data,'message': 'No stations Needed Fuel is enough to reach the destination'})
    except Exception as e:
        print(f"Error occurred: {e}")
    return HttpResponse("Error occurred while fetching map data.", status=500)