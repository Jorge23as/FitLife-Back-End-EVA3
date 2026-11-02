// Medidor de seguridad de la contraseña (sitio y admin de Django).
// Suma los mismos puntos que fortaleza() de cuentas/validadores.py: el
// servidor es el que acepta o rechaza, esto solo avisa mientras se escribe.
//   0-2 puntos -> rojo     "Insuficiente" (el servidor la rechaza)
//   3 puntos   -> amarillo "Aceptable"
//   4 puntos   -> verde    "Seguro"
//   5 puntos   -> azul     "SEGURO"
const NIVELES_CLAVE = ['Insuficiente', 'Aceptable', 'Seguro', 'SEGURO'];

function revisarClave(clave) {
  const reglas = [
    [clave.length >= 8, 'mínimo 8 caracteres'],
    [clave.length >= 12, '12 o más caracteres'],
    [/\p{Ll}/u.test(clave) && /\p{Lu}/u.test(clave), 'mayúsculas y minúsculas'],
    [/\p{Nd}/u.test(clave), 'números'],
    [/[^\p{L}\p{N}]/u.test(clave), 'símbolos'],
  ];
  let puntos = reglas.filter(([cumple]) => cumple).length;
  if (clave.length < 8) puntos = Math.min(puntos, 2);
  const faltan = reglas.filter(([cumple]) => !cumple).map(([, texto]) => texto);
  if (clave.length < 8) faltan.splice(1, 1);  // con menos de 8, pedir "12 o más" sobra
  return { nivel: Math.max(puntos - 2, 0), faltan };
}

// Agrega la barra de 4 tramos y el texto debajo del campo de contraseña
function medidorClave(input) {
  if (input.dataset.medidor) return;
  input.dataset.medidor = '1';
  const caja = document.createElement('div');
  caja.className = 'fuerza-clave';
  caja.hidden = true;
  caja.setAttribute('aria-live', 'polite');
  caja.innerHTML = '<div class="fuerza-barra"><span></span><span></span><span></span><span></span></div><div class="fuerza-texto"></div>';
  input.insertAdjacentElement('afterend', caja);
  input.addEventListener('input', () => {
    caja.hidden = !input.value;
    if (!input.value) return;
    const { nivel, faltan } = revisarClave(input.value);
    caja.dataset.nivel = nivel;
    caja.querySelector('.fuerza-texto').textContent = NIVELES_CLAVE[nivel] + (nivel < 3 ? ` · agrega: ${faltan.join(', ')}` : '');
  });
}

// Campos de contraseña nueva: los del sitio (data-fuerza) y los del admin
// (crear usuario, cambiar contraseña).
document.querySelectorAll('[data-fuerza], #id_password1, #id_new_password1').forEach(medidorClave);
