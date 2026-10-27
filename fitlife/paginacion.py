"""
Paginación de la API. Por defecto 20 registros por página, pero se
pueden pedir más con ?page_size=N (hasta 200). Las páginas de gestión lo
usan para llenar las listas de socios o planes de una vez.
"""
from rest_framework.pagination import PageNumberPagination


class PaginacionEstandar(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 200
