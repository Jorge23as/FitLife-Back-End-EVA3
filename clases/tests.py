"""
Pruebas de reserva de clases: cupos, lista de espera y sobrecupo.
python manage.py test clases
"""
import threading
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import connection
from django.utils.dateparse import parse_datetime
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APITestCase

from core.excepciones import ErrorDeNegocio
from core.fabricas import crear_clase, crear_plan, crear_socio, crear_usuario
from cuentas.models import Usuario

from . import services
from .models import Clase, Reserva

Estado = Reserva.Estado


class ReservasTest(TestCase):

    def setUp(self):
        self.plan = crear_plan()
        self.clase = crear_clase(cupo=2)
        self.a, self.b, self.c, self.d = (crear_socio(self.plan) for _ in range(4))

    def reservar_todos(self):
        return [services.reservar(s, self.clase) for s in (self.a, self.b, self.c, self.d)]

    def test_confirma_hasta_el_cupo_y_despues_lista_de_espera(self):
        a, b, c, d = self.reservar_todos()
        self.assertEqual([a.estado, b.estado], [Estado.CONFIRMADA, Estado.CONFIRMADA])
        self.assertEqual([c.estado, d.estado], [Estado.ESPERA, Estado.ESPERA])
        self.assertEqual([c.posicion_espera(), d.posicion_espera()], [1, 2])
        self.assertEqual(self.clase.ocupados(), 2)

    def test_al_cancelar_sube_el_primero_de_la_espera(self):
        a, _, c, d = self.reservar_todos()
        _, promovidas = services.cancelar_reserva(a)
        c.refresh_from_db()
        d.refresh_from_db()
        self.assertEqual(promovidas, [c])
        self.assertEqual(c.estado, Estado.CONFIRMADA)
        self.assertIsNotNone(c.promovida_en)
        self.assertEqual(d.posicion_espera(), 1)
        self.assertEqual(self.clase.ocupados(), 2)  # nunca más que el cupo

    def test_salir_de_la_lista_de_espera_no_sube_a_nadie(self):
        _, _, c, d = self.reservar_todos()
        _, promovidas = services.cancelar_reserva(c)
        d.refresh_from_db()
        self.assertEqual(promovidas, [])
        self.assertEqual(d.estado, Estado.ESPERA)

    def test_subir_el_cupo_hace_entrar_a_la_lista_de_espera(self):
        self.reservar_todos()
        self.clase.cupo = 3
        promovidas = services.guardar_clase(self.clase)
        self.assertEqual([r.socio for r in promovidas], [self.c])

    def test_el_cupo_no_baja_de_los_confirmados_ni_supera_la_sala(self):
        self.reservar_todos()
        self.clase.cupo = 1
        with self.assertRaises(ValidationError):
            self.clase.clean()
        self.clase.cupo = 21  # la sala es de 20
        with self.assertRaises(ValidationError):
            self.clase.clean()

    def test_no_reserva_dos_veces_la_misma_clase(self):
        services.reservar(self.a, self.clase)
        with self.assertRaises(ErrorDeNegocio):
            services.reservar(self.a, self.clase)

    def test_no_reserva_dos_clases_a_la_misma_hora(self):
        services.reservar(self.a, self.clase)
        otra = crear_clase(en=timedelta(days=1, minutes=30))
        with self.assertRaises(ErrorDeNegocio):
            services.reservar(self.a, otra)

    def test_reglas_de_la_membresia(self):
        sin_clases = crear_socio(crear_plan(incluye_clases=False))
        sin_membresia = crear_socio()
        for socio in (sin_clases, sin_membresia):
            with self.assertRaises(ErrorDeNegocio):
                services.reservar(socio, self.clase)

    def test_maximo_de_reservas_activas_del_plan(self):
        socio = crear_socio(crear_plan(max_reservas_activas=1))
        services.reservar(socio, self.clase)
        with self.assertRaises(ErrorDeNegocio):
            services.reservar(socio, crear_clase(en=timedelta(days=2)))

    def test_clase_que_ya_comenzo(self):
        reserva = services.reservar(self.a, self.clase)
        Clase.objects.filter(pk=self.clase.pk).update(inicio=self.clase.inicio - timedelta(days=2),
                                                      fin=self.clase.fin - timedelta(days=1, hours=23))
        self.clase.refresh_from_db()
        with self.assertRaises(ErrorDeNegocio):
            services.reservar(self.b, self.clase)
        with self.assertRaises(ErrorDeNegocio):
            services.cancelar_reserva(reserva)

    def test_cancelar_la_clase_cancela_sus_reservas(self):
        self.reservar_todos()
        self.assertEqual(services.cancelar_clase(self.clase), 4)
        self.assertFalse(self.clase.reservas.exclude(estado=Estado.CANCELADA).exists())
        with self.assertRaises(ErrorDeNegocio):
            services.reservar(crear_socio(self.plan), self.clase)

    def test_la_sala_no_se_ocupa_dos_veces(self):
        choque = Clase(actividad=self.clase.actividad, instructor=crear_usuario('INSTRUCTOR').instructor,
                       sala=self.clase.sala, inicio=self.clase.inicio + timedelta(minutes=15), cupo=5)
        with self.assertRaises(ValidationError) as error:
            choque.clean()
        self.assertIn('sala', error.exception.message_dict)

    def test_asistencia(self):
        reserva = services.reservar(self.a, self.clase)
        with self.assertRaises(ErrorDeNegocio):  # falta un día para la clase
            services.marcar_asistencia(reserva, True)
        Clase.objects.filter(pk=self.clase.pk).update(inicio=self.clase.inicio - timedelta(days=1))
        reserva.refresh_from_db()
        self.assertEqual(services.marcar_asistencia(reserva, True).estado, Estado.ASISTIO)


class ApiReservasTest(APITestCase):

    def setUp(self):
        self.plan = crear_plan()
        self.clase = crear_clase(cupo=1)
        self.socio = crear_socio(self.plan)

    def test_el_horario_es_publico(self):
        r = self.client.get('/api/clases/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['results'][0]['disponibles'], 1)

    def test_el_socio_reserva_y_ve_su_reserva_en_el_horario(self):
        self.client.force_login(self.socio.usuario)
        r = self.client.post('/api/reservas/', {'clase': self.clase.id})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['estado'], 'CONFIRMADA')
        mi_reserva = self.client.get(f'/api/clases/{self.clase.id}/').data['mi_reserva']
        self.assertEqual(mi_reserva['estado'], 'CONFIRMADA')

    def test_clase_llena_queda_en_espera_con_su_lugar(self):
        services.reservar(crear_socio(self.plan), self.clase)
        self.client.force_login(self.socio.usuario)
        r = self.client.post('/api/reservas/', {'clase': self.clase.id})
        self.assertEqual((r.data['estado'], r.data['posicion_espera']), ('ESPERA', 1))

    def test_un_socio_no_cancela_la_reserva_de_otro(self):
        ajena = services.reservar(crear_socio(self.plan), self.clase)
        self.client.force_login(self.socio.usuario)
        self.assertEqual(self.client.post(f'/api/reservas/{ajena.id}/cancelar/').status_code, 404)

    def test_recepcion_reserva_a_nombre_de_un_socio(self):
        self.client.force_login(crear_usuario(Usuario.Rol.RECEPCION))
        r = self.client.post('/api/reservas/', {'clase': self.clase.id, 'socio': self.socio.id})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['socio_nombre'], self.socio.nombre)

    def test_cada_instructor_ve_solo_la_lista_de_sus_clases(self):
        services.reservar(self.socio, self.clase)
        self.client.force_login(self.clase.instructor.usuario)
        self.assertEqual(len(self.client.get(f'/api/clases/{self.clase.id}/asistentes/').data), 1)
        self.client.force_login(crear_usuario(Usuario.Rol.INSTRUCTOR))
        self.assertEqual(self.client.get(f'/api/clases/{self.clase.id}/asistentes/').status_code, 403)

    def test_solo_el_administrador_crea_clases(self):
        datos = {'actividad': self.clase.actividad.id, 'instructor': self.clase.instructor.id, 'sala': self.clase.sala.id,
                 'inicio': (self.clase.inicio + timedelta(days=1)).isoformat(), 'cupo': 10}
        self.client.force_login(crear_usuario(Usuario.Rol.RECEPCION))
        self.assertEqual(self.client.post('/api/clases/', datos).status_code, 403)
        self.client.force_login(crear_usuario(Usuario.Rol.ADMIN))
        r = self.client.post('/api/clases/', datos)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(parse_datetime(r.data['fin']), self.clase.inicio + timedelta(days=1, minutes=60))  # inicio + duración
        self.assertEqual(self.client.post('/api/clases/', {**datos, 'cupo': 50}).status_code, 400)  # sala de 20


class CarreraPorElUltimoCupoTest(TransactionTestCase):
    """
    El problema del caso: sobrecupo. Dos socios reservan el último cupo en el
    mismo instante (2 hilos, cada uno con su conexión a PostgreSQL, sincronizados
    con una Barrier). Por el select_for_update() de la clase, uno espera al
    otro: uno queda CONFIRMADO y el otro EN ESPERA. Nunca dos confirmados.
    TransactionTestCase porque los hilos necesitan transacciones reales.
    """

    def test_dos_socios_al_mismo_tiempo_por_el_ultimo_cupo(self):
        plan = crear_plan()
        clase = crear_clase(cupo=1)
        socios = [crear_socio(plan), crear_socio(plan)]
        barrera = threading.Barrier(2)
        resultados = []

        def reservar(socio):
            try:
                barrera.wait()
                resultados.append(services.reservar(socio, clase).estado)
            finally:
                connection.close()  # cada hilo cierra su conexión

        hilos = [threading.Thread(target=reservar, args=(s,)) for s in socios]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()

        self.assertEqual(sorted(resultados), [Estado.CONFIRMADA, Estado.ESPERA])
        self.assertEqual(clase.reservas.filter(estado=Estado.CONFIRMADA).count(), 1)
