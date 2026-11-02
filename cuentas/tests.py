"""
Pruebas de seguridad: sesiones, login con bloqueo, CSRF, roles y permisos.
python manage.py test cuentas
"""
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from rest_framework.test import APIClient, APITestCase

from core.fabricas import CLAVE, crear_plan, crear_socio, crear_usuario

from .models import BloqueoLogin, Usuario
from .validadores import fortaleza, normalizar_rut, validar_rut

Rol = Usuario.Rol


class SesionTest(APITestCase):

    def setUp(self):
        self.socio = crear_socio(crear_plan(), username='socia')

    def login(self, clave=CLAVE, cliente=None):
        return (cliente or self.client).post('/api/auth/login/', {'username': 'socia', 'password': clave})

    def test_login_crea_la_sesion_y_dice_a_donde_ir(self):
        r = self.login()
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['rol'], r.data['inicio']), ('SOCIO', '/socio/'))
        self.assertIn('fitlife_sesion', r.cookies)
        self.assertTrue(r.cookies['fitlife_sesion']['httponly'])
        self.assertEqual(self.client.get('/api/auth/sesion/').data['username'], 'socia')

    def test_el_login_exige_el_token_csrf(self):
        cliente = APIClient(enforce_csrf_checks=True)
        self.assertEqual(self.login(cliente=cliente).status_code, 403)
        cliente.get('/login/')  # la página deja la cookie csrftoken
        r = cliente.post('/api/auth/login/', {'username': 'socia', 'password': CLAVE},
                         HTTP_X_CSRFTOKEN=cliente.cookies['csrftoken'].value)
        self.assertEqual(r.status_code, 200)

    def test_cinco_intentos_fallidos_bloquean_la_ip(self):
        for intento in range(1, 5):
            r = self.login('incorrecta')
            self.assertEqual((r.status_code, r.data['intentos_restantes']), (401, 5 - intento))
        self.assertEqual(self.login('incorrecta').status_code, 429)
        r = self.login()  # ni con la clave correcta durante el bloqueo
        self.assertEqual(r.status_code, 429)
        self.assertIn('Retry-After', r)
        BloqueoLogin.objects.all().delete()
        self.assertEqual(self.login().status_code, 200)

    def test_logout_cierra_la_sesion(self):
        self.login()
        self.assertEqual(self.client.post('/api/auth/logout/').status_code, 200)
        self.assertEqual(self.client.get('/api/mi-cuenta/').status_code, 401)

    def test_sin_sesion_la_api_responde_401(self):
        r = self.client.get('/api/socios/')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r['WWW-Authenticate'], 'Session realm="fitlife"')

    def test_permisos_por_rol(self):
        recepcion, admin = crear_usuario(Rol.RECEPCION), crear_usuario(Rol.ADMIN)
        self.client.force_login(self.socio.usuario)
        self.assertEqual(self.client.get('/api/socios/').status_code, 403)
        self.assertEqual(self.client.get('/api/aforo/').status_code, 403)
        self.client.force_login(recepcion)
        self.assertEqual(self.client.get('/api/socios/').status_code, 200)
        self.assertEqual(self.client.get('/api/mi-cuenta/').status_code, 403)
        self.client.force_login(admin)
        self.assertEqual(self.client.get('/api/schema/').status_code, 200)


class UsuariosTest(APITestCase):

    def test_el_rol_define_staff_grupo_y_perfil(self):
        socio = crear_usuario(Rol.SOCIO)
        recepcion = crear_usuario(Rol.RECEPCION)
        instructor = crear_usuario(Rol.INSTRUCTOR)
        self.assertFalse(socio.is_staff)
        self.assertTrue(recepcion.is_staff)
        self.assertEqual(list(socio.groups.values_list('name', flat=True)), ['Socios'])
        self.assertEqual(list(recepcion.groups.values_list('name', flat=True)), ['Recepción'])
        self.assertTrue(hasattr(socio, 'socio'))
        self.assertTrue(hasattr(instructor, 'instructor'))

    def test_los_grupos_tienen_los_permisos_del_admin(self):
        recepcion = Group.objects.get(name='Recepción')
        permisos = set(recepcion.permissions.values_list('codename', flat=True))
        self.assertIn('add_pago', permisos)
        self.assertIn('view_plan', permisos)
        self.assertNotIn('add_plan', permisos)
        self.assertFalse(any(p.startswith('delete_') for p in permisos))

    def test_createsuperuser_crea_un_administrador(self):
        call_command('createsuperuser', interactive=False, username='jefe', email='jefe@fitlife.cl',
                     first_name='Jefa', last_name='FitLife', rut='12345678-5', verbosity=0)
        jefe = Usuario.objects.get(username='jefe')
        self.assertEqual((jefe.rol, jefe.is_staff), (Rol.ADMIN, True))

    def test_rut_con_digito_verificador(self):
        self.assertEqual(normalizar_rut('12.345.678-5'), '12345678-5')
        self.assertEqual(normalizar_rut('7654321k'), '7654321-K')
        validar_rut('12345678-5')
        validar_rut('7654321-6')
        with self.assertRaises(ValidationError):
            validar_rut('12345678-9')

    def test_niveles_de_la_contrasena(self):
        # rojo / amarillo / verde / azul del medidor (static/js/clave.js)
        self.assertEqual(fortaleza('abc12345')[1], 'Insuficiente')
        self.assertEqual(fortaleza('Abc12345')[1], 'Aceptable')
        self.assertEqual(fortaleza('Abc12345!')[1], 'Seguro')
        self.assertEqual(fortaleza('Gimnasio.2026!')[1], 'SEGURO')

    def test_telefono_solo_numeros(self):
        self.client.force_login(crear_usuario(Rol.RECEPCION))
        socio = crear_socio()
        url = f'/api/socios/{socio.id}/'
        r = self.client.patch(url, {'telefono': '+569abc12345'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('telefono', r.data)
        r = self.client.patch(url, {'telefono_emergencia': 'llamar a Juan'})
        self.assertIn('telefono_emergencia', r.data)
        # espacios y guiones se aceptan y se guardan solo los números
        r = self.client.patch(url, {'telefono': '+56 9 1234-5678', 'telefono_emergencia': '22345 6789'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['telefono'], r.data['telefono_emergencia']), ('+56912345678', '223456789'))

    def test_recepcion_crea_un_socio_con_su_cuenta(self):
        self.client.force_login(crear_usuario(Rol.RECEPCION))
        datos = {'username': 'nuevo.socio', 'password': 'Gimnasio.2026', 'first_name': 'Ana', 'last_name': 'Pérez',
                 'email': 'ana@correo.cl', 'rut': '11.111.111-1'}
        r = self.client.post('/api/socios/', datos)
        self.assertEqual(r.status_code, 201)
        usuario = Usuario.objects.get(username='nuevo.socio')
        self.assertEqual((usuario.rol, usuario.rut), (Rol.SOCIO, '11111111-1'))
        self.assertTrue(usuario.check_password('Gimnasio.2026'))  # guardada con hash, no en texto plano
        self.assertEqual(r.data['membresia']['estado'], 'SIN_MEMBRESIA')
        # el mismo RUT escrito distinto se detecta como repetido; una clave débil se rechaza
        r = self.client.post('/api/socios/', {**datos, 'username': 'otro', 'rut': '111111111'})
        self.assertIn('rut', r.data)
        r = self.client.post('/api/socios/', {**datos, 'username': 'otro2', 'rut': '22222222-2', 'password': 'abc12345'})
        self.assertIn('password', r.data)

    def test_editar_un_socio_conserva_su_usuario_y_rut(self):
        socio = crear_socio()
        self.client.force_login(crear_usuario(Rol.RECEPCION))
        r = self.client.patch(f'/api/socios/{socio.id}/', {'telefono': '+56911112222', 'rut': socio.rut,
                                                          'username': socio.usuario.username})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['telefono'], '+56911112222')


class RegistroTest(APITestCase):

    DATOS = {'username': 'nueva.socia', 'password': 'Gimnasio.2026', 'first_name': 'Ana', 'last_name': 'Pérez',
             'email': 'ana@correo.cl', 'rut': '11.111.111-1'}

    def setUp(self):
        cache.clear()  # el límite de registros por IP se cuenta en la caché

    def test_el_registro_crea_un_socio_sin_membresia_y_lo_deja_con_sesion(self):
        r = self.client.post('/api/auth/registro/', self.DATOS)
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.data['rol'], r.data['inicio']), ('SOCIO', '/socio/'))
        usuario = Usuario.objects.get(username='nueva.socia')
        self.assertEqual((usuario.rut, usuario.is_staff), ('11111111-1', False))
        self.assertTrue(usuario.check_password('Gimnasio.2026'))
        cuenta = self.client.get('/api/mi-cuenta/')
        self.assertEqual(cuenta.status_code, 200)
        self.assertEqual(cuenta.data['membresia']['estado'], 'SIN_MEMBRESIA')

    def test_no_se_puede_elegir_el_rol_ni_activar_campos_de_personal(self):
        r = self.client.post('/api/auth/registro/', {**self.DATOS, 'rol': 'ADMIN', 'is_staff': True,
                                                     'is_superuser': True, 'activo': False})
        self.assertEqual(r.status_code, 201)
        usuario = Usuario.objects.get(username='nueva.socia')
        self.assertEqual((usuario.rol, usuario.is_staff, usuario.is_superuser, usuario.is_active),
                         (Rol.SOCIO, False, False, True))

    def test_valida_rut_repetido_clave_debil_y_csrf(self):
        self.client.post('/api/auth/registro/', self.DATOS)
        self.client.logout()
        r = self.client.post('/api/auth/registro/', {**self.DATOS, 'username': 'otra', 'rut': '111111111'})
        self.assertIn('rut', r.data)
        r = self.client.post('/api/auth/registro/', {**self.DATOS, 'username': 'otra', 'rut': '22222222-2',
                                                     'password': '12345678'})
        self.assertIn('password', r.data)
        r = self.client.post('/api/auth/registro/', {**self.DATOS, 'username': 'otra', 'rut': '22222222-2',
                                                     'telefono': 'no tengo'})
        self.assertIn('telefono', r.data)
        cliente = APIClient(enforce_csrf_checks=True)
        r = cliente.post('/api/auth/registro/', {**self.DATOS, 'username': 'otra', 'rut': '22222222-2'})
        self.assertEqual(r.status_code, 403)

    def test_maximo_cinco_cuentas_por_hora_por_ip(self):
        ruts = ['22222222-2', '33333333-3', '44444444-4', '55555555-5', '66666666-6', '77777777-7']
        for i, rut in enumerate(ruts):
            r = APIClient().post('/api/auth/registro/', {**self.DATOS, 'username': f'socio{i}', 'rut': rut})
            self.assertEqual(r.status_code, 201 if i < 5 else 429)

    def test_la_pagina_de_registro(self):
        self.assertContains(self.client.get('/registro/'), 'Crear cuenta de socio')
        self.client.force_login(crear_usuario(Rol.RECEPCION))
        self.assertRedirects(self.client.get('/registro/'), '/recepcion/', fetch_redirect_response=False)


class PaginasTest(APITestCase):

    def test_las_paginas_privadas_piden_iniciar_sesion(self):
        r = self.client.get('/socio/')
        self.assertRedirects(r, '/login/?next=/socio/', fetch_redirect_response=False)

    def test_con_otro_rol_muestra_la_403(self):
        self.client.force_login(crear_usuario(Rol.SOCIO))
        r = self.client.get('/recepcion/')
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, 'Acceso denegado', status_code=403)

    def test_404_propia(self):
        self.assertContains(self.client.get('/no-existe/'), 'Página no encontrada', status_code=404)

    def test_la_api_abierta_en_el_navegador_muestra_la_pagina_de_error(self):
        r = self.client.get('/api/socios/', HTTP_ACCEPT='text/html', HTTP_SEC_FETCH_MODE='navigate')
        self.assertContains(r, 'Debes iniciar sesión', status_code=401)
