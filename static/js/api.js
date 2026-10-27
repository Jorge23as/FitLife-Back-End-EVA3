/*
  api.js: funciones que usan todas las páginas de FitLife.

  - La sesión es la de Django: el navegador manda solo la cookie de sesión
    (HttpOnly: el JavaScript no la puede leer) en cada fetch a /api/.
  - En las peticiones que modifican datos (POST, PUT, PATCH, DELETE) se
    manda el token CSRF en el header X-CSRFToken, igual que en la guía de
    enmascaramiento: sale de la cookie csrftoken o del {% csrf_token %}
    de base.html.
  - Si la API responde 401 (la sesión venció), se manda al login.
  - Los botones no usan onclick="..." (el CSP lo bloquea): llevan
    data-accion="nombre" y cada página registra sus funciones con
    registrarAcciones(). Así un HTML inyectado no puede ejecutar nada.
*/

function csrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  if (m) return decodeURIComponent(m[1]);
  const campo = document.querySelector('[name=csrfmiddlewaretoken]');
  return campo ? campo.value : '';
}

async function leerJSON(resp) {
  try { return await resp.json(); } catch (e) { return {}; }
}

// fetch a la API. Devuelve { ok, status, data } y nunca lanza excepción.
async function api(url, { metodo = 'GET', datos } = {}) {
  const opciones = { method: metodo, credentials: 'same-origin', headers: { Accept: 'application/json' } };
  if (datos !== undefined) {
    opciones.headers['Content-Type'] = 'application/json';
    opciones.body = JSON.stringify(datos);
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(metodo)) opciones.headers['X-CSRFToken'] = csrfToken();
  let resp;
  try {
    resp = await fetch(url, opciones);
  } catch (e) {
    return { ok: false, status: 0, data: { detail: 'No hay conexión con el servidor.' } };
  }
  const data = await leerJSON(resp);
  if (resp.status === 401 && !url.startsWith('/api/auth/')) {
    // la sesión venció: al login, y después de vuelta a esta página
    window.location.href = `/login/?next=${encodeURIComponent(location.pathname)}&expirada=1`;
  }
  return { ok: resp.ok, status: resp.status, data };
}
const apiPost = (url, datos = {}) => api(url, { metodo: 'POST', datos });
const apiPatch = (url, datos) => api(url, { metodo: 'PATCH', datos });
const apiDelete = (url) => api(url, { metodo: 'DELETE' });

// formato de pesos, fechas y horas (siempre con la hora de Chile, como el servidor)
const ZONA = 'America/Santiago';
const clp = (n) => new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP' }).format(n || 0);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
// "2026-10-27" -> "27-10-2026" (sin pasar por Date, así no se corre un día por la zona horaria)
const fecha = (s) => (s ? s.slice(0, 10).split('-').reverse().join('-') : '-');
const fechaHora = (s) => (s ? new Date(s).toLocaleString('es-CL', { timeZone: ZONA, dateStyle: 'short', timeStyle: 'short', hourCycle: 'h23' }) : '-');
const hora = (s) => (s ? new Date(s).toLocaleTimeString('es-CL', { timeZone: ZONA, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }) : '-');
const diaLargo = (s) => new Date(s).toLocaleDateString('es-CL', { timeZone: ZONA, weekday: 'long', day: 'numeric', month: 'long' });
// fecha de hoy (o de un Date) en Chile, en formato AAAA-MM-DD
const isoDia = (d = new Date()) => d.toLocaleDateString('en-CA', { timeZone: ZONA });

// etiquetas de estado con los mismos colores del admin
const COLORES = {
  ACTIVA: 'verde', VENCIDA: 'rojo', CONGELADA: 'azul', CANCELADA: 'gris', POR_COMENZAR: 'amarillo', SIN_MEMBRESIA: 'gris',
  PAGADO: 'verde', ANULADO: 'gris', PROGRAMADA: 'verde', CONFIRMADA: 'verde', ESPERA: 'amarillo', ASISTIO: 'azul',
  AUSENTE: 'rojo', PERMITIDO: 'verde', DENEGADO: 'rojo', ENTRADA: 'verde', SALIDA: 'azul',
};
const TEXTOS = {
  ACTIVA: 'Activa', VENCIDA: 'Vencida', CONGELADA: 'Congelada', CANCELADA: 'Cancelada', POR_COMENZAR: 'Por comenzar',
  SIN_MEMBRESIA: 'Sin membresía', PAGADO: 'Pagado', ANULADO: 'Anulado', PROGRAMADA: 'Programada', CONFIRMADA: 'Confirmada',
  ESPERA: 'En espera', ASISTIO: 'Asistió', AUSENTE: 'No asistió', PERMITIDO: 'Permitido', DENEGADO: 'Denegado',
  ENTRADA: 'Entrada', SALIDA: 'Salida',
};
const badge = (valor, texto) => `<span class="estado estado-${COLORES[valor] || 'gris'}">${esc(texto || TEXTOS[valor] || valor)}</span>`;

// barra de ocupación (verde, amarilla desde 80% y roja al llenarse)
function colorPorcentaje(pct) { return pct >= 100 ? 'rojo' : pct >= 80 ? 'amarillo' : 'verde'; }
function barra(ocupados, total) {
  const pct = total ? Math.min(100, Math.round((ocupados * 100) / total)) : 0;
  return `<div class="barra" title="${pct}%"><div class="relleno-${colorPorcentaje(pct)}" style="width:${pct}%"></div></div>`;
}

function mensaje(texto, tipo = 'success') {
  const zona = document.getElementById('mensajes');
  if (!zona) return;
  zona.innerHTML = `<div class="alert alert-${tipo} alert-dismissible fade show" role="alert">${esc(texto)}
    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Cerrar"></button></div>`;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Nombre legible de cada campo para los mensajes de error de la API.
const ETIQUETAS = {
  username: 'Usuario', password: 'Contraseña', first_name: 'Nombres', last_name: 'Apellidos', email: 'Email',
  rut: 'RUT', telefono: 'Teléfono', fecha_nacimiento: 'Fecha de nacimiento', nombre: 'Nombre', precio: 'Precio',
  duracion_dias: 'Duración', dias_congelamiento: 'Días de congelamiento', max_reservas_activas: 'Reservas activas',
  socio: 'Socio', plan: 'Plan', metodo: 'Método de pago', motivo: 'Motivo', dias: 'Días', fecha_fin: 'Término',
  fecha_inicio: 'Inicio', actividad: 'Actividad', instructor: 'Instructor', sala: 'Sala', inicio: 'Inicio',
  fin: 'Término', cupo: 'Cupo', clase: 'Clase', codigo: 'Código', non_field_errors: '',
};

function errorTexto(data) {
  if (!data) return 'Error desconocido';
  if (typeof data === 'string') return data;
  if (data.detail) return data.detail;
  const mensajes = [];
  const recorrer = (valor, ruta) => {
    if (Array.isArray(valor)) return valor.forEach((v) => recorrer(v, ruta));
    if (valor && typeof valor === 'object') {
      return Object.entries(valor).forEach(([k, v]) => recorrer(v, ruta ? `${ruta}.${k}` : k));
    }
    const etiqueta = ETIQUETAS[ruta];
    const texto = etiqueta ? `${etiqueta}: ${valor}` : String(valor);
    if (!mensajes.includes(texto)) mensajes.push(texto);
  };
  recorrer(data, '');
  return mensajes.join(' ') || 'No se pudo completar la operación.';
}

// Ventana de confirmación del sitio (modal de base.html) en vez de confirm()/prompt().
// Devuelve una promesa: true/false, o el texto escrito (null si cancelan).
function dialogo({ titulo, mensaje = '', textoOk = 'Aceptar', peligro = false, campo = null }) {
  return new Promise((resolve) => {
    const el = document.getElementById('modal-dialogo');
    const input = el.querySelector('.modal-input');
    const ok = el.querySelector('.btn-ok');
    el.querySelector('.modal-title').textContent = titulo;
    el.querySelector('.modal-mensaje').textContent = mensaje;
    input.classList.toggle('d-none', campo === null);
    input.value = '';
    input.placeholder = campo || '';
    ok.textContent = textoOk;
    ok.className = `btn btn-ok ${peligro ? 'btn-danger' : 'btn-fl'}`;
    const modal = bootstrap.Modal.getOrCreateInstance(el);
    let respuesta = campo === null ? false : null;
    ok.onclick = () => { respuesta = campo === null ? true : input.value.trim(); modal.hide(); };
    el.querySelector('form').onsubmit = (e) => { e.preventDefault(); ok.click(); };
    el.addEventListener('shown.bs.modal', () => (campo === null ? ok : input).focus(), { once: true });
    el.addEventListener('hidden.bs.modal', () => resolve(respuesta), { once: true });
    modal.show();
  });
}
const preguntar = (titulo, texto, textoOk, peligro = false) => dialogo({ titulo, mensaje: texto, textoOk, peligro });
const pedirTexto = (titulo, texto, ejemplo = '', textoOk = 'Aceptar') => dialogo({ titulo, mensaje: texto, textoOk, campo: ejemplo });

// Formulario en ventana (modal #modal-form de base.html), para crear y editar.
// campos: [{ nombre, etiqueta, tipo, opciones: [{valor, texto}], requerido, ayuda, min, max, ancho }]
// enviar(datos) llama a la API; si responde con error, el mensaje se muestra
// dentro de la ventana y queda abierta. Devuelve los datos de la API o null.
function formulario({ titulo, campos, valores = {}, textoOk = 'Guardar', enviar }) {
  return new Promise((resolve) => {
    const el = document.getElementById('modal-form');
    const form = el.querySelector('form');
    const error = el.querySelector('.form-error');
    el.querySelector('.modal-title').textContent = titulo;
    el.querySelector('.btn-ok').textContent = textoOk;
    error.classList.add('d-none');
    form.querySelector('.campos').innerHTML = campos.map((c) => {
      const id = `f-${c.nombre}`;
      const valor = valores[c.nombre] ?? c.valor ?? '';
      const req = c.requerido ? 'required' : '';
      const extra = `${c.min !== undefined ? `min="${c.min}"` : ''} ${c.max !== undefined ? `max="${c.max}"` : ''} ${c.paso ? `step="${c.paso}"` : ''}`;
      let control;
      if (c.tipo === 'select') {
        control = `<select id="${id}" name="${c.nombre}" class="form-select" ${req}>
          ${c.vacio ? `<option value="">${esc(c.vacio)}</option>` : ''}
          ${c.opciones.map((o) => `<option value="${esc(o.valor)}" ${String(o.valor) === String(valor) ? 'selected' : ''}>${esc(o.texto)}</option>`).join('')}
        </select>`;
      } else if (c.tipo === 'textarea') {
        control = `<textarea id="${id}" name="${c.nombre}" class="form-control" rows="2" ${req}>${esc(valor)}</textarea>`;
      } else if (c.tipo === 'checkbox') {
        return `<div class="${c.ancho || 'col-12'}"><div class="form-check form-switch">
          <input id="${id}" name="${c.nombre}" type="checkbox" class="form-check-input" ${valor ? 'checked' : ''}>
          <label for="${id}" class="form-check-label">${esc(c.etiqueta)}</label>
          ${c.ayuda ? `<div class="form-text">${esc(c.ayuda)}</div>` : ''}</div></div>`;
      } else {
        control = `<input id="${id}" name="${c.nombre}" type="${c.tipo || 'text'}" class="form-control" value="${esc(valor)}" ${req} ${extra}
          ${c.tipo === 'password' ? 'autocomplete="new-password"' : ''}>`;
      }
      return `<div class="${c.ancho || 'col-12'}"><label for="${id}" class="form-label">${esc(c.etiqueta)}${c.requerido ? ' *' : ''}</label>
        ${control}${c.ayuda ? `<div class="form-text">${esc(c.ayuda)}</div>` : ''}</div>`;
    }).join('');

    const modal = bootstrap.Modal.getOrCreateInstance(el);
    let resultado = null;
    form.onsubmit = async (e) => {
      e.preventDefault();
      const datos = {};
      campos.forEach((c) => {
        const input = form.elements[c.nombre];
        if (c.tipo === 'checkbox') datos[c.nombre] = input.checked;
        else if (c.tipo === 'number') datos[c.nombre] = input.value === '' ? null : Number(input.value);
        else datos[c.nombre] = input.value;
      });
      const boton = el.querySelector('.btn-ok');
      boton.disabled = true;
      const r = await enviar(datos);
      boton.disabled = false;
      if (!r.ok) {
        error.textContent = errorTexto(r.data);
        error.classList.remove('d-none');
        return;
      }
      resultado = r.data;
      modal.hide();
    };
    el.addEventListener('shown.bs.modal', () => form.querySelector('input, select, textarea')?.focus(), { once: true });
    el.addEventListener('hidden.bs.modal', () => resolve(resultado), { once: true });
    modal.show();
  });
}

// Acciones de los botones: <button data-accion="cancelar" data-id="5"> llama a
// acciones.cancelar(boton), y la función lee boton.dataset.id.
const acciones = {};
function registrarAcciones(mapa) { Object.assign(acciones, mapa); }
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-accion]');
  if (el && Object.hasOwn(acciones, el.dataset.accion)) {
    e.preventDefault();
    acciones[el.dataset.accion](el);
  }
});

// ?next= del login: solo rutas de este sitio ("/socio/"), nunca otro dominio
// ("https://...", "//otro.cl", "/\otro.cl") ni "javascript:..."
function rutaInterna(ruta, defecto) {
  return ruta && /^\/(?![/\\])/.test(ruta) ? ruta : defecto;
}

// Repite una función cada `ms` milisegundos, pero se pausa si la pestaña no
// está a la vista (así un dashboard abierto en otra pestaña no carga al servidor).
function cadaCierto(fn, ms) {
  fn();
  let reloj = setInterval(fn, ms);
  document.addEventListener('visibilitychange', () => {
    clearInterval(reloj);
    if (document.visibilityState === 'visible') { fn(); reloj = setInterval(fn, ms); }
  });
}

async function cerrarSesion() {
  await apiPost('/api/auth/logout/');
  window.location.href = '/login/?salio=1';
}
registrarAcciones({ cerrarSesion });

// marca en el menú la página actual
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.navbar .nav-link[href], .navbar .dropdown-item[href]').forEach((a) => {
    if (a.getAttribute('href') === location.pathname) {
      a.classList.add('active');
      a.closest('.dropdown')?.querySelector('.dropdown-toggle')?.classList.add('active');
    }
  });
});
