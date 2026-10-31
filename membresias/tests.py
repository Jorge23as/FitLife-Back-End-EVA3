"""
Pruebas de planes, pagos y estados de membresía (Activa, Vencida, Congelada).
python manage.py test membresias
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from clases import services as clases_services
from clases.models import Reserva
from core.excepciones import ErrorDeNegocio
from core.fabricas import crear_clase, crear_plan, crear_socio, crear_usuario
from cuentas.models import Usuario

from . import services
from .models import Congelamiento, Membresia, Pago

HOY = timezone.localdate


class PagosYMembresiasTest(APITestCase):

    def setUp(self):
        self.plan = crear_plan(duracion_dias=30, dias_congelamiento=7, precio=34990)
        self.socio = crear_socio()

    def test_el_pago_crea_la_membresia_activa_desde_hoy(self):
        pago = services.registrar_pago(self.socio, self.plan, 'DEBITO')
        membresia = pago.membresia
        self.assertEqual(membresia.estado, Membresia.Estado.ACTIVA)
        self.assertEqual(membresia.fecha_inicio, HOY())
        self.assertEqual(membresia.fecha_fin, HOY() + timedelta(days=29))
        self.assertEqual(pago.monto, 34990)
        self.assertEqual(services.membresia_para(self.socio, HOY()), membresia)

    def test_la_renovacion_parte_al_dia_siguiente_del_termino(self):
        primera = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        segunda = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        self.assertEqual(segunda.fecha_inicio, primera.fecha_fin + timedelta(days=1))
        self.assertEqual(services.situacion(self.socio)['renovada_hasta'], segunda.fecha_fin)

    def test_el_monto_del_pago_no_cambia_si_cambia_el_plan(self):
        pago = services.registrar_pago(self.socio, self.plan, 'EFECTIVO')
        self.plan.precio = 50000
        self.plan.save()
        pago.refresh_from_db()
        self.assertEqual(pago.monto, 34990)

    def test_no_se_vende_un_plan_desactivado(self):
        self.plan.activo = False
        self.plan.save()
        with self.assertRaises(ErrorDeNegocio):
            services.registrar_pago(self.socio, self.plan, 'EFECTIVO')

    def test_vence_sola_cuando_pasa_el_termino(self):
        membresia = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        Membresia.objects.filter(pk=membresia.pk).update(fecha_inicio=HOY() - timedelta(days=40),
                                                         fecha_fin=HOY() - timedelta(days=11))
        services.sincronizar_estados()
        membresia.refresh_from_db()
        self.assertEqual(membresia.estado, Membresia.Estado.VENCIDA)
        self.assertIsNone(services.membresia_para(self.socio, HOY()))
        self.assertEqual(services.motivo_sin_membresia(self.socio, HOY())[0], 'VENCIDA')

    def test_congelar_suma_los_dias_al_termino(self):
        membresia = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        termino = membresia.fecha_fin
        services.congelar(membresia, 5, 'Viaje')
        membresia.refresh_from_db()
        self.assertEqual(membresia.estado, Membresia.Estado.CONGELADA)
        self.assertEqual(membresia.fecha_fin, termino + timedelta(days=5))
        # congelada hoy no deja entrar; el día que se reactiva sí
        self.assertIsNone(services.membresia_para(self.socio, HOY()))
        self.assertEqual(services.membresia_para(self.socio, HOY() + timedelta(days=5)), membresia)

    def test_no_se_congela_mas_de_lo_que_permite_el_plan(self):
        membresia = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        with self.assertRaises(ErrorDeNegocio):
            services.congelar(membresia, 8)
        services.congelar(membresia, 4)
        services.descongelar(membresia)  # el mismo día: no usó ninguno
        services.congelar(membresia, 7)
        membresia.congelamientos.filter(fecha_fin__gt=HOY()).update(fecha_inicio=HOY() - timedelta(days=7), fecha_fin=HOY())  # ya los usó
        services.sincronizar_estados()
        with self.assertRaises(ErrorDeNegocio):
            services.congelar(membresia, 1)

    def test_un_plan_sin_congelamiento_no_se_congela(self):
        plan = crear_plan(dias_congelamiento=0)
        membresia = services.registrar_pago(crear_socio(), plan, 'EFECTIVO').membresia
        with self.assertRaises(ErrorDeNegocio):
            services.congelar(membresia, 1)

    def test_descongelar_antes_descuenta_los_dias_no_usados(self):
        membresia = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        termino = membresia.fecha_fin
        services.congelar(membresia, 5)
        services.descongelar(membresia)
        membresia.refresh_from_db()
        self.assertEqual(membresia.estado, Membresia.Estado.ACTIVA)
        self.assertEqual(membresia.fecha_fin, termino)
        self.assertEqual(membresia.dias_congelados(), 0)

    def test_el_congelamiento_termina_solo(self):
        membresia = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        services.congelar(membresia, 3)
        Congelamiento.objects.update(fecha_inicio=HOY() - timedelta(days=3), fecha_fin=HOY())
        services.sincronizar_estados()
        membresia.refresh_from_db()
        self.assertEqual(membresia.estado, Membresia.Estado.ACTIVA)

    def test_congelar_mueve_la_renovacion_pagada(self):
        actual = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        renovacion = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        services.congelar(actual, 3)
        actual.refresh_from_db()
        renovacion.refresh_from_db()
        self.assertEqual(renovacion.fecha_inicio, actual.fecha_fin + timedelta(days=1))

    def test_congelar_libera_su_cupo_para_la_lista_de_espera(self):
        membresia = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        clase = crear_clase(cupo=1)
        mia = clases_services.reservar(self.socio, clase)
        otra = clases_services.reservar(crear_socio(self.plan), clase)
        self.assertEqual(otra.estado, Reserva.Estado.ESPERA)
        services.congelar(membresia, 3)
        mia.refresh_from_db()
        otra.refresh_from_db()
        self.assertEqual(mia.estado, Reserva.Estado.CANCELADA)
        self.assertEqual(otra.estado, Reserva.Estado.CONFIRMADA)

    def test_anular_el_pago_cancela_la_membresia_y_sus_reservas(self):
        pago = services.registrar_pago(self.socio, self.plan, 'EFECTIVO')
        reserva = clases_services.reservar(self.socio, crear_clase())
        services.anular_pago(pago, 'Pago duplicado')
        pago.refresh_from_db()
        reserva.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.ANULADO)
        self.assertEqual(pago.membresia.estado, Membresia.Estado.CANCELADA)
        self.assertEqual(reserva.estado, Reserva.Estado.CANCELADA)
        with self.assertRaises(ErrorDeNegocio):
            services.anular_pago(pago)


class ApiPagosTest(APITestCase):

    def setUp(self):
        self.plan = crear_plan()
        self.socio = crear_socio()
        self.recepcion = crear_usuario(Usuario.Rol.RECEPCION)
        self.admin = crear_usuario(Usuario.Rol.ADMIN)

    def test_recepcion_registra_el_pago_y_se_crea_la_membresia(self):
        self.client.force_login(self.recepcion)
        r = self.client.post('/api/pagos/', {'socio': self.socio.id, 'plan': self.plan.id, 'metodo': 'DEBITO'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['membresia_inicio'], HOY().isoformat())
        self.assertEqual(Membresia.objects.get(socio=self.socio).estado, Membresia.Estado.ACTIVA)
        self.assertEqual(Pago.objects.get().registrado_por, self.recepcion)

    def test_solo_el_administrador_anula_pagos(self):
        pago = services.registrar_pago(self.socio, self.plan, 'EFECTIVO')
        self.client.force_login(self.recepcion)
        self.assertEqual(self.client.post(f'/api/pagos/{pago.id}/anular/', {'motivo': 'x'}).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.post(f'/api/pagos/{pago.id}/anular/', {'motivo': 'Error de digitación'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['estado'], 'ANULADO')

    def test_los_pagos_no_se_borran(self):
        pago = services.registrar_pago(self.socio, self.plan, 'EFECTIVO')
        self.client.force_login(self.admin)
        self.assertEqual(self.client.delete(f'/api/pagos/{pago.id}/').status_code, 405)

    def test_un_socio_no_ve_los_pagos(self):
        self.client.force_login(self.socio.usuario)
        self.assertEqual(self.client.get('/api/pagos/').status_code, 403)

    def test_el_socio_abre_solo_el_comprobante_de_sus_pagos(self):
        mio = services.registrar_pago(self.socio, self.plan, 'DEBITO')
        ajeno = services.registrar_pago(crear_socio(), self.plan, 'EFECTIVO')
        self.client.force_login(self.socio.usuario)
        r = self.client.get(f'/api/pagos/{mio.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['comprobante'], mio.comprobante)
        self.assertEqual(self.client.get(f'/api/pagos/{ajeno.id}/').status_code, 404)
        self.assertEqual(self.client.get(f'/comprobantes/{mio.id}/').status_code, 200)

    def test_la_pagina_del_comprobante_pide_sesion(self):
        pago = services.registrar_pago(self.socio, self.plan, 'DEBITO')
        r = self.client.get(f'/comprobantes/{pago.id}/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])
        self.client.force_login(self.recepcion)
        self.assertContains(self.client.get(f'/comprobantes/{pago.id}/'), 'Comprobante de pago')

    def test_crud_de_planes_solo_para_el_administrador(self):
        datos = {'nombre': 'Plan Nuevo', 'precio': 20000, 'duracion_dias': 30, 'dias_congelamiento': 0}
        self.client.force_login(self.recepcion)
        self.assertEqual(self.client.post('/api/planes/', datos).status_code, 403)
        self.client.force_login(self.admin)
        r = self.client.post('/api/planes/', datos)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.client.patch(f"/api/planes/{r.data['id']}/", {'precio': 25000}).data['precio'], 25000)
        self.assertEqual(self.client.delete(f"/api/planes/{r.data['id']}/").status_code, 204)

    def test_un_plan_con_membresias_no_se_borra(self):
        services.registrar_pago(self.socio, self.plan, 'EFECTIVO')
        self.client.force_login(self.admin)
        self.assertEqual(self.client.delete(f'/api/planes/{self.plan.id}/').status_code, 409)

    def test_sin_sesion_solo_se_ven_los_planes_a_la_venta(self):
        crear_plan(nombre='Antiguo', activo=False)
        nombres = [p['nombre'] for p in self.client.get('/api/planes/').data]
        self.assertIn(self.plan.nombre, nombres)
        self.assertNotIn('Antiguo', nombres)

    def test_congelar_y_descongelar_por_la_api(self):
        membresia = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        self.client.force_login(self.recepcion)
        r = self.client.post(f'/api/membresias/{membresia.id}/congelar/', {'dias': 3, 'motivo': 'Lesión'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['estado'], 'CONGELADA')
        self.assertEqual(self.client.post(f'/api/membresias/{membresia.id}/congelar/', {'dias': 1}).status_code, 409)
        r = self.client.post(f'/api/membresias/{membresia.id}/descongelar/')
        self.assertEqual(r.data['estado'], 'ACTIVA')

    def test_filtro_por_vencer(self):
        membresia = services.registrar_pago(self.socio, self.plan, 'EFECTIVO').membresia
        self.client.force_login(self.recepcion)
        self.assertEqual(self.client.get('/api/membresias/?por_vencer=7').data['count'], 0)
        Membresia.objects.filter(pk=membresia.pk).update(fecha_fin=HOY() + timedelta(days=3))
        self.assertEqual(self.client.get('/api/membresias/?por_vencer=7').data['count'], 1)
