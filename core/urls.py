"""Rutas de las páginas HTML (las que ve el usuario)."""
from django.urls import path

from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('horario/', views.horario, name='horario'),
    path('login/', views.login, name='login'),
    path('socio/', views.mi_cuenta, name='mi-cuenta'),
    path('socio/qr/', views.mi_qr, name='mi-qr'),
    path('instructor/', views.instructor, name='instructor'),
    path('recepcion/', views.recepcion, name='recepcion'),
    path('aforo/', views.aforo, name='aforo'),
    path('gestion/socios/', views.gestion_socios, name='gestion-socios'),
    path('gestion/pagos/', views.gestion_pagos, name='gestion-pagos'),
    path('gestion/membresias/', views.gestion_membresias, name='gestion-membresias'),
    path('gestion/planes/', views.gestion_planes, name='gestion-planes'),
    path('gestion/clases/', views.gestion_clases, name='gestion-clases'),
]
