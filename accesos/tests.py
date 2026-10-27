"""
Pruebas del control de acceso con QR y del aforo en tiempo real.
python manage.py test accesos
"""
import time as reloj
from datetime import time, timedelta
from unittest import mock

from django.utils import timezone
from rest_framework.test import APITestCase

from core.fabricas import crear_plan, crear_sede, crear_socio, crear_usuario
from cuentas.models import Usuario
from membresias import services as membresias
from membresias.models import Membresia

from . import qr, services
from .models import RegistroAcceso, Visita

Causa = RegistroAcceso.Causa


class ControlDeAccesoTest(APITestCase):

    def setUp(self):
        self.sede = crear_sede(aforo_maximo=2)
        self.plan = crear_plan()
        self.socio = crear_socio(self.plan)
        self.recepcion = crear_usuario(Usuario.Rol.RECEPCION)

    def leer(self, socio=None, codigo=None, modo='AUTO'):
        codigo = codigo or qr.generar_token(socio or self.socio)
        registro, *_ = services.validar_acceso(codigo, self.sede, 'SIMULADO', self.recepcion, modo)
        return registro

    def test_la_entrada_permitida_abre_una_visita(self):
        registro = self.leer()
        self.assertEqual((registro.resultado, registro.tipo, registro.causa), ('PERMITIDO', 'ENTRADA', 'OK'))
        self.assertTrue(Visita.objects.filter(socio=self.socio, salida__isnull=True).exists())
        self.assertEqual(services.estado_aforo(self.sede)['actual'], 1)

    def test_la_segunda_lectura_es_la_salida(self):
        self.leer()
        registro = self.leer()
        self.assertEqual((registro.resultado, registro.tipo), ('PERMITIDO', 'SALIDA'))
        self.assertEqual(services.estado_aforo(self.sede)['actual'], 0)

    def test_anti_passback_no_entra_dos_veces(self):
        self.leer()
        self.assertEqual(self.leer(modo='ENTRADA').causa, Causa.YA_DENTRO)

    def test_qr_expirado(self):
        # un QR generado hace 2 minutos (vale 60 s): una captura de pantalla vieja
        with mock.patch('django.core.signing.time.time', return_value=reloj.time() - 120):
            viejo = qr.generar_token(self.socio)
        self.assertEqual(self.leer(codigo=viejo).causa, Causa.QR_EXPIRADO)

    def test_qr_alterado_o_inventado(self):
        bueno = qr.generar_token(self.socio)
        self.assertEqual(self.leer(codigo=bueno[:-2] + 'xx').causa, Causa.QR_INVALIDO)
        self.assertEqual(self.leer(codigo='hola').causa, Causa.QR_INVALIDO)
        self.assertEqual(RegistroAcceso.objects.filter(resultado='DENEGADO', socio__isnull=True).count(), 2)

    def test_qr_regenerado_deja_de_servir(self):
        codigo = qr.generar_token(self.socio)
        self.socio.regenerar_qr()
        self.assertEqual(self.leer(codigo=codigo).causa, Causa.QR_INVALIDO)

    def test_membresia_vencida_congelada_o_inexistente(self):
        Membresia.objects.filter(socio=self.socio).update(fecha_inicio=timezone.localdate() - timedelta(days=40),
                                                          fecha_fin=timezone.localdate() - timedelta(days=11))
        self.assertEqual(self.leer().causa, Causa.VENCIDA)
        congelada = crear_socio(self.plan)
        membresias.congelar(congelada.membresias.get(), 3)
        self.assertEqual(self.leer(congelada).causa, Causa.CONGELADA)
        self.assertEqual(self.leer(crear_socio()).causa, Causa.SIN_MEMBRESIA)
        self.assertEqual(Visita.objects.count(), 0)

    def test_aforo_completo(self):
        otros = [crear_socio(self.plan), crear_socio(self.plan)]
        for socio in otros:
            self.leer(socio)
        registro = self.leer()
        self.assertEqual(registro.causa, Causa.AFORO_COMPLETO)
        self.leer(otros[0])  # uno sale
        self.assertEqual(self.leer().resultado, 'PERMITIDO')

    def test_fuera_de_horario(self):
        ahora = timezone.localtime()
        self.sede.hora_apertura = (ahora + timedelta(hours=2)).time()
        self.sede.hora_cierre = (ahora + timedelta(hours=3)).time()
        self.sede.save()
        self.assertEqual(self.leer().causa, Causa.FUERA_HORARIO)

    def test_la_salida_se_permite_aunque_haya_vencido(self):
        self.leer()
        Membresia.objects.filter(socio=self.socio).update(estado='VENCIDA', fecha_fin=timezone.localdate() - timedelta(days=1),
                                                          fecha_inicio=timezone.localdate() - timedelta(days=30))
        self.assertEqual((self.leer().resultado, Visita.objects.get().salida is not None), ('PERMITIDO', True))

    def test_socio_desactivado(self):
        self.socio.usuario.is_active = False
        self.socio.usuario.save()
        self.assertEqual(self.leer().causa, Causa.SOCIO_INACTIVO)

    def test_las_visitas_olvidadas_se_cierran_solas(self):
        Visita.objects.create(socio=self.socio, sede=self.sede, entrada=timezone.now() - timedelta(hours=5))
        self.assertEqual(services.estado_aforo(self.sede)['actual'], 0)
        visita = Visita.objects.get()
        self.assertTrue(visita.cierre_automatico)
        self.assertEqual(visita.salida - visita.entrada, timedelta(hours=self.sede.horas_max_permanencia))

    def test_horario_que_pasa_la_medianoche(self):
        self.sede.hora_apertura, self.sede.hora_cierre = time(6, 0), time(1, 0)
        hoy = timezone.localtime()
        self.assertTrue(self.sede.abierta(hoy.replace(hour=23, minute=30)))
        self.assertTrue(self.sede.abierta(hoy.replace(hour=0, minute=30)))
        self.assertFalse(self.sede.abierta(hoy.replace(hour=3, minute=0)))


class ApiAccesoTest(APITestCase):

    def setUp(self):
        self.sede = crear_sede()
        self.socio = crear_socio(crear_plan())
        self.recepcion = crear_usuario(Usuario.Rol.RECEPCION)

    def test_recepcion_valida_y_recibe_el_resultado_y_el_aforo(self):
        self.client.force_login(self.recepcion)
        codigo = self.client.get(f'/api/socios/{self.socio.id}/qr/').data['codigo']
        r = self.client.post('/api/accesos/validar/', {'codigo': codigo, 'metodo': 'SIMULADO'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['permitido'])
        self.assertEqual(r.data['socio']['membresia']['estado'], 'ACTIVA')
        self.assertEqual(r.data['aforo']['actual'], 1)
        self.assertEqual(self.client.get('/api/aforo/').data['dentro'][0]['socio'], self.socio.id)

    def test_un_socio_no_puede_validar_accesos(self):
        self.client.force_login(self.socio.usuario)
        r = self.client.post('/api/accesos/validar/', {'codigo': qr.generar_token(self.socio)})
        self.assertEqual(r.status_code, 403)

    def test_el_qr_del_socio_es_valido_y_cambia(self):
        self.client.force_login(self.socio.usuario)
        r = self.client.get('/api/mi-qr/')
        self.assertEqual(qr.leer_token(r.data['codigo']), str(self.socio.codigo_qr))
        self.assertTrue(r.data['imagen'].startswith('data:image/svg+xml;base64,'))

    def test_el_aforo_publico_no_muestra_nombres(self):
        services.validar_acceso(qr.generar_token(self.socio), self.sede, 'SIMULADO')
        r = self.client.get('/api/aforo/publico/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['actual'], 1)
        self.assertNotIn('dentro', r.data)
        self.assertEqual(self.client.get('/api/aforo/').status_code, 401)

    def test_el_historial_de_accesos_es_solo_lectura(self):
        self.client.force_login(crear_usuario(Usuario.Rol.ADMIN))
        services.validar_acceso('hola', self.sede, 'MANUAL')
        registro = RegistroAcceso.objects.get()
        self.assertEqual(self.client.delete(f'/api/accesos/{registro.id}/').status_code, 405)
        self.assertEqual(self.client.patch(f'/api/accesos/{registro.id}/', {'motivo': 'x'}).status_code, 405)

    def test_salida_manual_desde_el_dashboard(self):
        services.validar_acceso(qr.generar_token(self.socio), self.sede, 'SIMULADO')
        self.client.force_login(self.recepcion)
        visita = Visita.objects.get()
        r = self.client.post(f'/api/visitas/{visita.id}/salida/')
        self.assertIsNotNone(r.data['salida'])
        self.assertEqual(RegistroAcceso.objects.filter(tipo='SALIDA', metodo='MANUAL').count(), 1)
