"""
Negociación de contenido de la API.

Como la API solo tiene JSONRenderer, si un cliente pide únicamente
"Accept: text/html" DRF respondería 406. En ese caso devuelvo JSON igual.
"""
from rest_framework.exceptions import NotAcceptable
from rest_framework.negotiation import DefaultContentNegotiation


class NegociacionJSON(DefaultContentNegotiation):
    def select_renderer(self, request, renderers, format_suffix=None):
        try:
            return super().select_renderer(request, renderers, format_suffix)
        except NotAcceptable:
            return renderers[0], renderers[0].media_type
