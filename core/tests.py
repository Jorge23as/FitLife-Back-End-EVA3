"""
Pruebas del admin de Django personalizado, de "Mi cuenta" y de la carga de datos de demo.
python manage.py test core
"""
import io

from django.contrib import admin
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APITestCase

from accesos import qr
from accesos import services as accesos
from clases import services as clases
from cuentas.models import Socio, Usuario
from membresias import services as membresias
from membresias.models import Membresia, Pago

from .fabricas import crear_clase, crear_plan, crear_sede, crear_socio, crear_usuario


class AdminTest(APITestCase):

    def setUp(self):
        self.sede = crear_sede()
        self.plan = crear_plan()
        self.socio = crear_socio(self.plan)
        clases.reservar(self.socio, crear_clase())
        accesos.validar_acceso(qr.generar_token(self.socio), self.sede, 'SIMULADO')
        accesos.validar_acceso('hola', self.sede, 'MANUAL')
        self.admin = crear_usuario(Usuario.Rol.ADMIN, is_superuser=True)

    def test_todas_las_paginas_del_admin_cargan(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/admin/'), 'Membresías activas')
        for modelo, modelo_admin in admin.site._registry.items():
            app, nombre = modelo._meta.app_label, modelo._meta.model_name
            with self.subTest(modelo=nombre):
                lista = self.client.get(reverse(f'admin:{app}_{nombre}_changelist'))
                self.assertEqual(lista.status_code, 200)
                agregar = self.client.get(reverse(f'admin:{app}_{nombre}_add'))
                self.assertIn(agregar.status_code, (200, 403))
                objeto = modelo.objects.first()
                if objeto:
                    self.assertEqual(self.client.get(reverse(f'admin:{app}_{nombre}_change', args=[objeto.pk])).status_code, 200)

    def test_recepcion_entra_al_admin_con_permisos_limitados(self):
        self.client.force_login(crear_usuario(Usuario.Rol.RECEPCION))
        self.assertEqual(self.client.get('/admin/membresias/pago/').status_code, 200)
        self.assertEqual(self.client.get('/admin/membresias/pago/add/').status_code, 200)
        self.assertEqual(self.client.get('/admin/membresias/plan/add/').status_code, 403)
        self.assertEqual(self.client.get('/admin/cuentas/usuario/add/').status_code, 403)
        self.client.force_login(self.socio.usuario)
        self.assertRedirects(self.client.get('/admin/'), '/admin/login/?next=/admin/', fetch_redirect_response=False)

    def test_registrar_un_pago_en_el_admin_crea_la_membresia(self):
        otro = crear_socio()
        self.client.force_login(self.admin)
        r = self.client.post('/admin/membresias/pago/add/', {'socio': otro.id, 'plan': self.plan.id, 'metodo': 'EFECTIVO',
                                                              'observacion': 'En caja'})
        self.assertEqual(r.status_code, 302)
        pago = Pago.objects.get(socio=otro)
        self.assertEqual((pago.monto, pago.membresia.estado, pago.registrado_por), (self.plan.precio, 'ACTIVA', self.admin))

    def test_accion_congelar_con_pagina_intermedia(self):
        membresia = self.socio.membresias.get()
        self.client.force_login(self.admin)
        url = '/admin/membresias/membresia/'
        r = self.client.post(url, {'action': 'congelar', '_selected_action': [membresia.id]})
        self.assertContains(r, 'Días a congelar')
        r = self.client.post(url, {'action': 'congelar', '_selected_action': [membresia.id], 'aplicar': '1',
                                   'dias': 4, 'motivo': 'Lesión'})
        self.assertEqual(r.status_code, 302)
        membresia.refresh_from_db()
        self.assertEqual(membresia.estado, Membresia.Estado.CONGELADA)


class MiCuentaTest(APITestCase):

    def test_resumen_del_socio(self):
        crear_sede()
        socio = crear_socio(crear_plan(nombre='Mensual Full'))
        espera = crear_clase(cupo=1)
        clases.reservar(crear_socio(crear_plan()), espera)
        reserva = clases.reservar(socio, espera)  # queda en espera
        clases.cancelar_reserva(espera.reservas.first())  # el otro cancela: sube
        self.client.force_login(socio.usuario)
        datos = self.client.get('/api/mi-cuenta/').data
        self.assertEqual((datos['membresia']['estado'], datos['membresia']['plan']), ('ACTIVA', 'Mensual Full'))
        self.assertEqual(datos['avisos_promovidas'][0]['id'], reserva.id)
        self.assertEqual(len(datos['pagos']), 1)


class CargarDemoTest(APITestCase):

    def test_carga_los_casos_de_la_demostracion(self):
        call_command('cargar_demo', stdout=io.StringIO())
        maria = Socio.objects.get(usuario__username='maria.gonzalez')
        pedro = Socio.objects.get(usuario__username='pedro.rojas')
        self.assertEqual(membresias.situacion(maria)['estado'], 'ACTIVA')
        self.assertEqual(membresias.situacion(pedro)['estado'], 'VENCIDA')
        self.assertTrue(Membresia.objects.filter(estado='CONGELADA').exists())
        self.assertGreater(accesos.estado_aforo(accesos.sede_principal())['actual'], 0)
        call_command('cargar_demo', reset=True, stdout=io.StringIO())  # se puede repetir


class DriverBaseDeDatosTest(APITestCase):

    def test_psycopg_usa_la_libpq_del_sistema(self):
        # sin psycopg-binary (que trae su propio OpenSSL): OpenSSL y libpq se parchan con apt
        from psycopg import pq
        self.assertEqual(pq.__impl__, 'python')
