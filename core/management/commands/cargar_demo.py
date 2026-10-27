"""
python manage.py cargar_demo [--reset]

Carga datos de prueba para mostrar FitLife funcionando. Todo se arma
relativo a la hora en que se corre (clases de la semana, gente dentro del
gimnasio ahora, pagos de hoy), así que conviene correrlo con --reset justo
antes de una demostración.

Casos que deja listos:
  maria.gonzalez   membresía activa (Mensual Full); tiene cupo en la clase HIIT llena
  pedro.rojas      membresía vencida -> el QR lo rechaza
  camila.soto      membresía congelada -> el QR lo rechaza
  juan.perez       plan Básico (sin clases grupales) -> no puede reservar
  sofia.morales    plan Estudiante (máximo 3 reservas activas, ya tiene 3)
  diego.fuentes    sin membresía
  valentina.diaz   renovó por adelantado (dos membresías seguidas)
  isidora.castillo primera en la lista de espera de la clase HIIT llena
"""
import random
from datetime import datetime, time, timedelta

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils import timezone

from accesos.models import RegistroAcceso, Sede, Visita
from clases import services as clases_services
from clases.models import Actividad, Clase, Reserva, Sala
from core.excepciones import ErrorDeNegocio
from cuentas.models import BloqueoLogin, Instructor, Socio, Usuario
from cuentas.validadores import digito_verificador
from membresias.models import Congelamiento, Membresia, Pago, Plan
from membresias.services import membresia_para

CLAVE_SOCIO = 'Socio2026!'
CLAVE_INSTRUCTOR = 'Instructor2026!'

PLANES = [
    # nombre, precio, días, clases, máx. reservas, días congelamiento, a la venta, descripción
    ('Mensual Básico', 24990, 30, False, None, 0, True, 'Sala de máquinas y cardio. No incluye clases grupales.'),
    ('Estudiante', 19990, 30, True, 3, 7, True, 'Con credencial vigente. Hasta 3 clases reservadas a la vez.'),
    ('Mensual Full', 34990, 30, True, None, 7, True, 'Sala de máquinas y clases grupales sin límite.'),
    ('Trimestral Full', 89990, 90, True, None, 21, True, 'Tres meses de acceso completo con descuento.'),
    ('Anual Full', 299990, 365, True, None, 60, True, 'Un año de acceso completo: el mejor precio por mes.'),
    ('Corporativo 2025', 27990, 30, True, None, 7, False, 'Convenio empresas 2025 (ya no se vende).'),
]

ACTIVIDADES = [
    # nombre, minutos, intensidad, color, descripción
    ('Spinning', 45, 'ALTA', '#ef4444', 'Ciclismo indoor por intervalos al ritmo de la música.'),
    ('Yoga', 60, 'BAJA', '#8b5cf6', 'Posturas, respiración y flexibilidad.'),
    ('Funcional', 50, 'ALTA', '#f97316', 'Circuitos con peso corporal, kettlebells y TRX.'),
    ('Pilates', 55, 'MEDIA', '#06b6d4', 'Fuerza del centro, postura y control.'),
    ('Zumba', 60, 'MEDIA', '#ec4899', 'Baile aeróbico con ritmos latinos.'),
    ('Boxeo', 60, 'ALTA', '#64748b', 'Técnica de golpes, saco y acondicionamiento.'),
    ('HIIT', 45, 'ALTA', '#eab308', 'Entrenamiento interválico de alta intensidad.'),
]

INSTRUCTORES = [
    # usuario, nombres, apellidos, especialidad
    ('fmunoz', 'Fernanda', 'Muñoz Rivas', 'Spinning y Funcional'),
    ('ilagos', 'Ignacio', 'Lagos Pino', 'Yoga y Pilates'),
    ('fvargas', 'Francisca', 'Vargas Toro', 'Zumba y Boxeo'),
    ('raguilera', 'Rodrigo', 'Aguilera Mena', 'HIIT'),
]

# horario semanal: (días 0=lunes..6=domingo, hora, actividad, sala, instructor, cupo)
SEMANA = [
    (range(5), '07:00', 'Spinning', 'Sala Spinning', 'fmunoz', 20),
    (range(5), '09:00', 'Yoga', 'Estudio Mente y Cuerpo', 'ilagos', 12),
    (range(5), '13:00', 'Funcional', 'Sala Multiuso', 'fmunoz', 20),
    (range(5), '18:00', 'Spinning', 'Sala Spinning', 'fmunoz', 20),
    (range(5), '19:00', 'Pilates', 'Estudio Mente y Cuerpo', 'ilagos', 12),
    (range(5), '19:30', 'Zumba', 'Sala Multiuso', 'fvargas', 25),
    (range(5), '20:30', 'Boxeo', 'Sala Multiuso', 'fvargas', 16),
    ([5], '10:00', 'Funcional', 'Sala Multiuso', 'fmunoz', 20),
    ([5], '11:00', 'Yoga', 'Estudio Mente y Cuerpo', 'ilagos', 12),
    ([5], '12:00', 'Zumba', 'Sala Multiuso', 'fvargas', 25),
    ([6], '10:30', 'Yoga', 'Estudio Mente y Cuerpo', 'ilagos', 12),
]

SOCIOS = [
    # nombres, apellidos, usuario, perfil de membresía
    ('María José', 'González Pérez', 'maria.gonzalez', 'demo'),
    ('Pedro', 'Rojas Silva', 'pedro.rojas', 'vencida'),
    ('Camila', 'Soto Valenzuela', 'camila.soto', 'congelada'),
    ('Juan Pablo', 'Pérez Muñoz', 'juan.perez', 'basico'),
    ('Sofía', 'Morales Díaz', 'sofia.morales', 'estudiante'),
    ('Diego', 'Fuentes Araya', 'diego.fuentes', 'sin'),
    ('Valentina', 'Díaz Castro', 'valentina.diaz', 'renovada'),
    ('Tomás', 'Reyes Contreras', 'tomas.reyes', 'inactivo'),
    ('Isidora', 'Castillo Núñez', 'isidora.castillo', 'full'),
    ('Benjamín', 'Torres Espinoza', 'benjamin.torres', 'trimestral'),
    ('Martín', 'Herrera Vega', 'martin.herrera', 'anual'),
    ('Antonia', 'Vásquez Rivera', 'antonia.vasquez', 'por_vencer'),
    ('Lucas', 'Sepúlveda Bravo', 'lucas.sepulveda', 'full'),
    ('Florencia', 'Cortés Pizarro', 'florencia.cortes', 'trimestral'),
    ('Joaquín', 'Navarro Molina', 'joaquin.navarro', 'estudiante'),
    ('Martina', 'Guzmán Ortiz', 'martina.guzman', 'full'),
    ('Vicente', 'Paredes Lagos', 'vicente.paredes', 'anual'),
    ('Josefa', 'Carrasco Soto', 'josefa.carrasco', 'full'),
    ('Agustín', 'Medina Fuentes', 'agustin.medina', 'basico'),
    ('Emilia', 'Rojas Henríquez', 'emilia.rojas', 'por_vencer'),
    ('Cristóbal', 'Alarcón Tapia', 'cristobal.alarcon', 'trimestral'),
    ('Renata', 'Figueroa Leiva', 'renata.figueroa', 'hoy'),
    ('Maximiliano', 'Sandoval Gallardo', 'maximiliano.sandoval', 'full'),
    ('Catalina', 'Vergara Salinas', 'catalina.vergara', 'anual'),
    ('Gabriel', 'Ibarra Cáceres', 'gabriel.ibarra', 'vencida'),
    ('Trinidad', 'Riquelme Bustos', 'trinidad.riquelme', 'hoy'),
]

# más socios para que el gimnasio se vea con movimiento (nombres armados al azar)
NOMBRES_EXTRA = ['Ignacia', 'Sebastián', 'Constanza', 'Felipe', 'Javiera', 'Nicolás', 'Paula', 'Andrés', 'Daniela',
                 'Tomás', 'Bárbara', 'Esteban', 'Macarena', 'Gonzalo', 'Carolina', 'Héctor', 'Pía', 'Simón',
                 'Fernanda', 'Rafael', 'Amanda', 'Bruno', 'Elisa', 'Hugo']
APELLIDOS_EXTRA = ['Araya', 'Bustamante', 'Cifuentes', 'Donoso', 'Escobar', 'Farías', 'Garrido', 'Hidalgo', 'Jara',
                   'Krause', 'León', 'Maldonado', 'Olivares', 'Poblete', 'Quiroz', 'Rebolledo', 'Saavedra', 'Toledo',
                   'Uribe', 'Valdés', 'Yáñez', 'Zamorano', 'Becerra', 'Ossandón']
PERFILES_EXTRA = ['full'] * 10 + ['trimestral'] * 5 + ['anual'] * 4 + ['estudiante'] * 2 + ['basico'] * 2 + ['vencida']


def sin_tildes(texto):
    return texto.lower().translate(str.maketrans('áéíóúñü', 'aeiounu'))


def rut(numero):
    return f'{numero}-{digito_verificador(numero)}'


class Command(BaseCommand):
    help = 'Carga datos de prueba de FitLife relativos a la hora actual (usar --reset para partir de cero).'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Borra los datos de FitLife antes de cargar.')

    def handle(self, *args, **opciones):
        random.seed(2026)
        if opciones['reset']:
            self.borrar()
        elif Plan.objects.exists():
            raise CommandError('Ya hay datos cargados. Use --reset para borrarlos y cargar de nuevo.')
        with transaction.atomic():
            self.ahora = timezone.localtime()
            self.hoy = self.ahora.date()
            self.crear_base()
            self.crear_personas()
            self.crear_membresias()
            self.crear_clases()
            self.crear_reservas()
            self.crear_accesos()
        self.resumen()

    # --- borrar --------------------------------------------------------------
    def borrar(self):
        with transaction.atomic():
            modelos = (RegistroAcceso, Visita, Reserva, Clase, Congelamiento, Pago, Membresia, Plan, Actividad, Sala,
                       Sede, BloqueoLogin)
            for modelo in modelos:
                modelo.objects.all().delete()
            # los ids vuelven a partir de 1 (así los comprobantes parten en FL-000001)
            with connection.cursor() as cursor:
                for sql in connection.ops.sequence_reset_sql(no_style(), modelos):
                    cursor.execute(sql)
            semilla = ['admin', 'recepcion'] + [i[0] for i in INSTRUCTORES]
            Usuario.objects.filter(rol=Usuario.Rol.SOCIO).delete()
            Usuario.objects.filter(username__in=semilla).delete()
        self.stdout.write('Datos anteriores borrados.')

    # --- catálogos -----------------------------------------------------------
    def crear_base(self):
        self.sede = Sede.objects.create(nombre='FitLife Central', direccion='Av. Providencia 1234, Providencia',
                                        aforo_maximo=40, hora_apertura=time(6, 0), hora_cierre=time(23, 0))
        self.salas = {nombre: Sala.objects.create(sede=self.sede, nombre=nombre, capacidad=capacidad) for nombre, capacidad in
                      [('Sala Spinning', 20), ('Sala Multiuso', 25), ('Estudio Mente y Cuerpo', 12), ('Box HIIT', 10)]}
        self.planes = {}
        for nombre, precio, dias, clases, maximo, congelar, activo, descripcion in PLANES:
            self.planes[nombre] = Plan.objects.create(
                nombre=nombre, precio=precio, duracion_dias=dias, incluye_clases=clases, max_reservas_activas=maximo,
                dias_congelamiento=congelar, activo=activo, descripcion=descripcion)
        self.actividades = {nombre: Actividad.objects.create(nombre=nombre, duracion_minutos=minutos, intensidad=intensidad,
                                                             color=color, descripcion=descripcion)
                            for nombre, minutos, intensidad, color, descripcion in ACTIVIDADES}

    # --- usuarios ------------------------------------------------------------
    def crear_personas(self):
        # el hash de una contraseña tarda ~0,5 s (PBKDF2): lo calculo una vez por clave y lo reutilizo
        hash_socio, hash_instructor = make_password(CLAVE_SOCIO), make_password(CLAVE_INSTRUCTOR)

        # si ya existe un "admin" (creado con createsuperuser) no le cambio la contraseña
        if not Usuario.objects.filter(username='admin').exists():
            Usuario.objects.create_superuser('admin', 'admin@fitlife.cl', 'FitLife2026!', first_name='Administrador',
                                             last_name='FitLife', rut=rut(11111112))
        self.recepcion = Usuario(username='recepcion', first_name='Valeria', last_name='Ortiz Campos',
                                 email='recepcion@fitlife.cl', rut=rut(16543210), rol=Usuario.Rol.RECEPCION)
        self.recepcion.set_password('Recepcion2026!')
        self.recepcion.save()

        self.instructores = {}
        for i, (usuario, nombres, apellidos, especialidad) in enumerate(INSTRUCTORES):
            u = Usuario.objects.create(username=usuario, first_name=nombres, last_name=apellidos, rol=Usuario.Rol.INSTRUCTOR,
                                       email=f'{usuario}@fitlife.cl', rut=rut(13200000 + i * 811), password=hash_instructor)
            u.instructor.especialidad = especialidad
            u.instructor.save()
            self.instructores[usuario] = u.instructor

        extras = []
        for i, perfil in enumerate(PERFILES_EXTRA):
            nombre, apellido = NOMBRES_EXTRA[i], APELLIDOS_EXTRA[(i * 7) % len(APELLIDOS_EXTRA)]
            segundo = APELLIDOS_EXTRA[(i * 11 + 5) % len(APELLIDOS_EXTRA)]
            extras.append((nombre, f'{apellido} {segundo}', f'{sin_tildes(nombre)}.{sin_tildes(apellido)}', perfil))

        self.socios = {}
        for i, (nombres, apellidos, usuario, perfil) in enumerate(SOCIOS + extras):
            u = Usuario.objects.create(
                username=usuario, first_name=nombres, last_name=apellidos, email=f'{usuario}@correo.cl',
                rut=rut(17000000 + i * 104729), telefono=f'+5698{random.randint(1000000, 9999999)}', rol=Usuario.Rol.SOCIO,
                password=hash_socio, is_active=perfil != 'inactivo')
            socio = u.socio
            socio.fecha_nacimiento = self.hoy - timedelta(days=random.randint(18 * 365, 55 * 365))
            socio.contacto_emergencia = random.choice(['Ana', 'Luis', 'Carmen', 'Jorge', 'Patricia']) + ' (familiar)'
            socio.telefono_emergencia = f'+5697{random.randint(1000000, 9999999)}'
            socio.save()
            Socio.objects.filter(pk=socio.pk).update(fecha_alta=self.hoy - timedelta(days=random.randint(320, 500)))
            self.socios[usuario] = (socio, perfil)

    # --- membresías y pagos ----------------------------------------------------
    def membresia(self, socio, plan, inicio, estado=Membresia.Estado.ACTIVA, pagado_el=None):
        m = Membresia.objects.create(socio=socio, plan=plan, fecha_inicio=inicio,
                                     fecha_fin=inicio + timedelta(days=plan.duracion_dias - 1), estado=estado)
        dia = pagado_el or min(inicio, self.hoy)
        momento = timezone.make_aware(datetime.combine(dia, time(random.randint(7, 20), random.randint(0, 59))))
        if dia == self.hoy:
            momento = min(momento, timezone.now() - timedelta(minutes=random.randint(5, 90)))
        Pago.objects.create(socio=socio, plan=plan, membresia=m, monto=plan.precio, fecha=momento,
                            metodo=random.choice(Pago.Metodo.values), registrado_por=self.recepcion)
        return m

    def crear_membresias(self):
        p = self.planes
        for socio, perfil in self.socios.values():
            if perfil == 'sin':
                continue
            if perfil == 'vencida':
                self.membresia(socio, p['Mensual Full'], self.hoy - timedelta(days=65), Membresia.Estado.VENCIDA)
                self.membresia(socio, p['Mensual Full'], self.hoy - timedelta(days=35), Membresia.Estado.VENCIDA)
            elif perfil == 'congelada':
                m = self.membresia(socio, p['Trimestral Full'], self.hoy - timedelta(days=40))
                Congelamiento.objects.create(membresia=m, fecha_inicio=self.hoy - timedelta(days=3),
                                             fecha_fin=self.hoy + timedelta(days=7), motivo='Viaje por trabajo',
                                             registrado_por=self.recepcion)
                m.fecha_fin += timedelta(days=10)
                m.estado = Membresia.Estado.CONGELADA
                m.save()
            elif perfil == 'renovada':
                actual = self.membresia(socio, p['Mensual Full'], self.hoy - timedelta(days=20))
                self.membresia(socio, p['Mensual Full'], actual.fecha_fin + timedelta(days=1), pagado_el=self.hoy)
            elif perfil == 'inactivo':
                self.membresia(socio, p['Mensual Full'], self.hoy - timedelta(days=70), Membresia.Estado.VENCIDA)
            else:
                plan, inicio = {
                    'demo': (p['Mensual Full'], self.hoy - timedelta(days=10)),
                    'full': (p['Mensual Full'], self.hoy - timedelta(days=random.randint(2, 24))),
                    'hoy': (p['Mensual Full'], self.hoy),
                    'por_vencer': (p['Mensual Full'], self.hoy - timedelta(days=26)),
                    'basico': (p['Mensual Básico'], self.hoy - timedelta(days=random.randint(2, 20))),
                    'estudiante': (p['Estudiante'], self.hoy - timedelta(days=random.randint(2, 20))),
                    'trimestral': (p['Trimestral Full'], self.hoy - timedelta(days=random.randint(10, 75))),
                    'anual': (p['Anual Full'], self.hoy - timedelta(days=random.randint(30, 300))),
                }[perfil]
                if perfil == 'demo' or (random.random() < 0.5 and plan.duracion_dias == 30):
                    # historial: el mes anterior también pagó
                    self.membresia(socio, plan, inicio - timedelta(days=30), Membresia.Estado.VENCIDA)
                self.membresia(socio, plan, inicio)

    # --- clases ----------------------------------------------------------------
    def clase(self, actividad, sala, instructor, inicio, cupo):
        return Clase.objects.create(actividad=self.actividades[actividad], sala=self.salas[sala],
                                    instructor=self.instructores[instructor], inicio=inicio, cupo=cupo)

    def crear_clases(self):
        lunes = self.hoy - timedelta(days=self.hoy.weekday())
        for semana in (-1, 0, 1):
            for dias, hora, actividad, sala, instructor, cupo in SEMANA:
                for d in dias:
                    dia = lunes + timedelta(days=semana * 7 + d)
                    inicio = timezone.make_aware(datetime.combine(dia, time.fromisoformat(hora)))
                    self.clase(actividad, sala, instructor, inicio, cupo)
        # clases de la demostración (sala y profesor propios, así no chocan con el horario)
        ahora = timezone.now().replace(second=0, microsecond=0)
        self.hiit_en_curso = self.clase('HIIT', 'Box HIIT', 'raguilera', ahora - timedelta(minutes=20), 10)
        despues = ahora + timedelta(minutes=90)
        en_hora = despues.replace(minute=0 if despues.minute < 30 else 30)  # entre 1 h y 1 h 30 desde ahora
        self.hiit_llena = self.clase('HIIT', 'Box HIIT', 'raguilera', en_hora, 6)

    def elegibles(self):
        """Socios que hoy pueden reservar clases (membresía activa con clases y cuenta activa)."""
        return [s for s, perfil in self.socios.values()
                if perfil in ('demo', 'full', 'hoy', 'por_vencer', 'trimestral', 'anual', 'estudiante', 'renovada')]

    def crear_reservas(self):
        candidatos = self.elegibles()
        ahora = timezone.now()
        # clases que ya pasaron: historial de asistencia (directo, sin las reglas de reserva)
        for clase in Clase.objects.filter(fin__lte=ahora).exclude(pk=self.hiit_en_curso.pk):
            con_membresia = [s for s in candidatos if membresia_para(s, clase.fecha)]
            for socio in random.sample(con_membresia, k=min(len(con_membresia), random.randint(clase.cupo // 3, clase.cupo))):
                estado = Reserva.Estado.ASISTIO if random.random() < 0.85 else Reserva.Estado.AUSENTE
                Reserva.objects.create(socio=socio, clase=clase, estado=estado)
        for socio in random.sample(candidatos, k=7):
            Reserva.objects.create(socio=socio, clase=self.hiit_en_curso, estado=Reserva.Estado.CONFIRMADA)

        # clase HIIT llena: María José tiene cupo; Isidora es la primera en la lista de espera
        maria, isidora = self.socios['maria.gonzalez'][0], self.socios['isidora.castillo'][0]
        otros = [s for s in candidatos if s not in (maria, isidora) and self.socios[s.usuario.username][1] != 'estudiante']
        for socio in [maria, *otros[:5], isidora, *otros[5:7]]:
            clases_services.reservar(socio, self.hiit_llena)

        # Sofía (Estudiante) con sus 3 reservas permitidas
        sofia = self.socios['sofia.morales'][0]
        futuras = list(Clase.objects.filter(inicio__gt=ahora + timedelta(hours=3), actividad__nombre='Yoga')[:3])
        for clase in futuras:
            clases_services.reservar(sofia, clase)

        # clases futuras del horario, con las reglas de verdad (reservar()). Cada socio reserva
        # como mucho una clase por día y entre 2 y 5 en total, como alguien que va al gimnasio.
        # Primero se llena la de Pilates de mañana (queda con lista de espera); el resto, entre 30% y 90%.
        tope = {s: random.randint(2, 5) for s in candidatos}
        tope[maria] = 3
        reservas = {s: Reserva.objects.filter(socio=s, clase__inicio__gt=ahora).exclude(estado='CANCELADA').count()
                    for s in candidatos}
        dias = {s: set() for s in candidatos}
        manana = self.hoy + timedelta(days=1)
        futuras = list(Clase.objects.filter(inicio__gt=ahora).exclude(pk=self.hiit_llena.pk).order_by('inicio'))
        futuras.sort(key=lambda c: not (c.fecha == manana and c.actividad.nombre == 'Pilates'))
        for clase in futuras:
            llena = clase.fecha == manana and clase.actividad.nombre == 'Pilates'
            meta = clase.cupo + 3 if llena else int(clase.cupo * random.uniform(0.3, 0.9))
            for socio in random.sample(candidatos, k=len(candidatos)):
                if clase.reservas.count() >= meta:
                    break
                if not llena and (reservas[socio] >= tope[socio] or clase.fecha in dias[socio]):
                    continue
                try:
                    clases_services.reservar(socio, clase)
                except ErrorDeNegocio:
                    continue  # choque de horario, tope del plan, etc.: se salta, como pasaría en la app
                reservas[socio] += 1
                dias[socio].add(clase.fecha)

    # --- accesos de hoy --------------------------------------------------------
    def registro(self, socio, tipo, momento, causa='OK', motivo='', resultado='PERMITIDO', visita=None, metodo='CAMARA'):
        return RegistroAcceso.objects.create(sede=self.sede, socio=socio, visita=visita, tipo=tipo, resultado=resultado,
                                             causa=causa, motivo=motivo, metodo=metodo, fecha_hora=momento,
                                             registrado_por=self.recepcion)

    def crear_accesos(self):
        ahora = timezone.now()
        apertura = timezone.make_aware(datetime.combine(self.hoy, self.sede.hora_apertura))
        candidatos = [s for s, perfil in self.socios.values() if perfil not in ('vencida', 'congelada', 'sin', 'inactivo')]
        maria = self.socios['maria.gonzalez'][0]
        candidatos.remove(maria)  # María José queda fuera para mostrar su entrada en la demo
        random.shuffle(candidatos)

        # visitas de días anteriores (historial de cada socio)
        for socio in candidatos + [maria]:
            for _ in range(random.randint(1, 3)):
                entrada = timezone.make_aware(datetime.combine(self.hoy - timedelta(days=random.randint(1, 6)),
                                                               time(random.randint(7, 20), random.randint(0, 59))))
                visita = Visita.objects.create(socio=socio, sede=self.sede, entrada=entrada,
                                               salida=entrada + timedelta(minutes=random.randint(45, 110)))
                self.registro(socio, 'ENTRADA', visita.entrada, motivo='Entrada registrada.', visita=visita)
                self.registro(socio, 'SALIDA', visita.salida, motivo='Salida registrada.', visita=visita)

        # hoy, más temprano: entraron y ya se fueron
        desde = max(apertura, ahora - timedelta(hours=8))
        for socio in candidatos[17:]:
            if ahora - desde < timedelta(minutes=100):
                break
            entrada = desde + timedelta(minutes=random.randint(0, int((ahora - desde).total_seconds() // 60) - 100))
            visita = Visita.objects.create(socio=socio, sede=self.sede, entrada=entrada,
                                           salida=entrada + timedelta(minutes=random.randint(50, 95)))
            self.registro(socio, 'ENTRADA', visita.entrada, motivo='Entrada registrada.', visita=visita)
            self.registro(socio, 'SALIDA', visita.salida, motivo='Salida registrada.', visita=visita)

        # dentro ahora: 17 personas (43% del aforo de 40)
        for socio in candidatos[:17]:
            entrada = ahora - timedelta(minutes=random.randint(4, 110))
            visita = Visita.objects.create(socio=socio, sede=self.sede, entrada=entrada)
            self.registro(socio, 'ENTRADA', entrada, motivo='Entrada registrada.', visita=visita)

        # intentos rechazados de hoy
        rechazos = [
            ('pedro.rojas', 'VENCIDA', 'Membresía vencida el {}.', 170),
            ('camila.soto', 'CONGELADA', 'Membresía congelada hasta el {}.', 95),
            ('diego.fuentes', 'SIN_MEMBRESIA', 'El socio no tiene una membresía vigente.', 60),
        ]
        for usuario, causa, motivo, minutos in rechazos:
            socio = self.socios[usuario][0]
            fecha = None
            if causa == 'VENCIDA':
                fecha = socio.membresias.order_by('-fecha_fin').first().fecha_fin
            elif causa == 'CONGELADA':
                fecha = self.hoy + timedelta(days=6)
            self.registro(socio, 'ENTRADA', ahora - timedelta(minutes=minutos), causa,
                          motivo.format(fecha.strftime('%d-%m-%Y')) if fecha else motivo, 'DENEGADO')
        self.registro(None, 'ENTRADA', ahora - timedelta(minutes=40), 'QR_INVALIDO',
                      'QR no válido: la firma no corresponde (código alterado o inventado).', 'DENEGADO', metodo='MANUAL')
        self.registro(None, 'ENTRADA', ahora - timedelta(minutes=25), 'QR_EXPIRADO',
                      'QR expirado: el socio debe mostrar el QR actualizado de su app.', 'DENEGADO')

    def resumen(self):
        self.stdout.write(self.style.SUCCESS(
            f'Listo: {Socio.objects.count()} socios, {Membresia.objects.count()} membresías, {Pago.objects.count()} pagos, '
            f'{Clase.objects.count()} clases, {Reserva.objects.count()} reservas, '
            f'{Visita.objects.filter(salida__isnull=True).count()} personas dentro ahora.'))
        self.stdout.write('Usuarios: admin / FitLife2026! · recepcion / Recepcion2026! · '
                          f'instructores (fmunoz, ilagos, fvargas, raguilera) / {CLAVE_INSTRUCTOR} · '
                          f'socios (maria.gonzalez, pedro.rojas, camila.soto...) / {CLAVE_SOCIO}')
