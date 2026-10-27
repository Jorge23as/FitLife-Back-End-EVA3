"""
Páginas de error propias para la API cuando se abre en el navegador
(igual que en la EVA-2).

La API responde JSON. Pero si alguien escribe una URL de /api/ en la barra
del navegador y la respuesta es un error, en vez del JSON muestro las
plantillas del sitio (401, 403, 404 o la genérica error.html).

Cómo distingo al navegador del fetch() de api.js: al navegar, el navegador
manda "Sec-Fetch-Mode: navigate" y un Accept con text/html. fetch() manda
"cors"/"same-origin" y Accept */*, así que el JavaScript del sitio y
herramientas como curl o Postman siguen recibiendo JSON.
"""
from django.shortcuts import render

TITULOS = {
    400: 'Solicitud incorrecta',
    405: 'Método no permitido',
    406: 'Formato no aceptado',
    409: 'Conflicto con el estado actual',
    415: 'Tipo de contenido no soportado',
    429: 'Demasiadas solicitudes',
}


def es_navegacion(request):
    modo = request.headers.get('Sec-Fetch-Mode')
    if modo:
        return modo == 'navigate'
    return 'text/html' in request.headers.get('Accept', '')


class ErroresApiEnHtmlMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        respuesta = self.get_response(request)
        if not (request.path.startswith('/api/') and respuesta.status_code >= 400 and es_navegacion(request)):
            return respuesta

        codigo = respuesta.status_code
        if codigo == 401:
            html = render(request, '401.html', {'destino': request.path}, status=401)
            html['WWW-Authenticate'] = respuesta.get('WWW-Authenticate', 'Session realm="fitlife"')
        elif codigo == 403:
            html = render(request, '403.html', {'destino': request.path}, status=403)
        elif codigo == 404:
            html = render(request, '404.html', {'ruta': request.path}, status=404)
        else:
            html = render(request, 'error.html', {
                'codigo': codigo, 'titulo': TITULOS.get(codigo, 'Ocurrió un error'), 'ruta': request.path,
            }, status=codigo)
        if 'Allow' in respuesta:
            html['Allow'] = respuesta['Allow']
        return html
