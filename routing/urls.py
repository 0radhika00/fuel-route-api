from django.urls import path
from . import views

urlpatterns = [
    path('',views.home_view, name='home'),
    path('api/route/', views.get_map_view, name='get_map'),
]