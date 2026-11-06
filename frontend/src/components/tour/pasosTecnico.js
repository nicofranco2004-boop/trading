// Los pasos del tutorial de Análisis técnico — qué te dice cada pestaña.
// ═══════════════════════════════════════════════════════════════════════════
// Pedido de Nico (02/11): un recorrido de una sola vez, la primera vez que la
// persona entra a /analisis-tecnico, para que entienda qué le muestra cada
// pestaña. Se vuelve a abrir a mano con «¿Cómo se lee esto?»; solo, nunca más.
// El mecanismo es el de novedades (Tour.jsx); ver pasosTecnico.test.js, que
// cruza cada `marca` contra el código y cada promesa contra la pantalla.
//
// EL ORDEN. Primero el Gráfico, que es la pestaña con la que se abre la
// pantalla, y lo esencial para usarlo (cambiar de activo, línea o velas y cada
// cuánto es una vela, dibujar): es lo que la persona tiene delante. Después
// las otras pestañas en el orden de la fila, y Comparar y lo que viene al
// final, ya de vuelta en el Gráfico: así el tutorial termina donde la persona
// va a empezar a usar la pantalla, y no en Señales.
//
// LO QUE NO DICE. Ningún paso sugiere qué hacer con un activo (CNV: Rendi no
// asesora): describen qué muestra cada parte, nunca qué comprar o vender. Y
// ninguno nombra un monto: con «Ocultar saldos» prendido el tutorial se ve
// igual, y lo que queda iluminado ya respeta el ojito por su cuenta.
//
// `grupo: 'grafico'`: los botones de arriba del gráfico y su barra de dibujo
// sólo están si el activo tiene gráfico (un fondo común no; el demo no trae
// precios): si el primero no aparece, el tutorial saltea los dos juntos. Si el
// gráfico falló al cargar, los botones de arriba sí están (con «Reintentar»
// adentro) y la barra no: ese paso espera lo que dice TourTecnico.jsx y se
// saltea solo.
//
// `busqueda`: lo que el paso necesita de la dirección (ver `destino` en
// recorrido.js). `?tab=` sin valor es la pestaña de entrada, el Gráfico; el resto
// de la dirección (?activo=GGAL) se respeta.

export const PASOS_TECNICO = [
  {
    id: 'grafico',
    marca: 'tab-grafico',
    ruta: '/analisis-tecnico',
    busqueda: '?tab=',
    titulo: 'Gráfico: el precio, para mirarlo y dibujarle encima',
    texto: 'Es la pestaña con la que se abre esta pantalla: el gráfico del activo que elijas, '
      + 'para ver cómo se movió su precio y hacer tu propio análisis.',
  },
  {
    id: 'activo',
    marca: 'grafico-activo',
    ruta: '/analisis-tecnico',
    busqueda: '?tab=',
    titulo: 'Cambiá de activo desde acá',
    // El buscador tiene los filtros «Tu cartera» y «Tu lista», y al lado del
    // botón van los últimos que miraste (GraficoTecnico.jsx).
    texto: 'Tocá el nombre y buscá por ticker o por nombre, o elegí uno de tu cartera o de tu '
      + 'lista. Los últimos que miraste quedan al lado, a un toque.',
  },
  {
    id: 'vista',
    grupo: 'grafico',
    marca: 'grafico-vista',
    ruta: '/analisis-tecnico',
    busqueda: '?tab=',
    titulo: 'Línea o velas, y cada cuánto es una vela',
    // EL BOTÓN QUE SE NOMBRA TIENE QUE EXISTIR CON ESE NOMBRE. «1D» sólo
    // aparece con velas (con línea no hay velas que medir), y arranca siempre
    // en diarias: por eso el texto dice «con velas aparece».
    texto: 'Elegí si el precio se dibuja en línea o en velas. Con velas aparece «1D»: ahí cambiás '
      + 'cada cuánto es una vela (1 hora, 4 horas, 1 día o 1 semana). En el mismo renglón, la '
      + 'moneda, el período y la pantalla completa.',
  },
  {
    id: 'dibujar',
    grupo: 'grafico',
    marca: 'grafico-herramientas',
    ruta: '/analisis-tecnico',
    busqueda: '?tab=',
    titulo: 'Dibujá sobre el gráfico',
    texto: 'En esta barra están las líneas (de tendencia, horizontales o a mano alzada), Fibonacci y '
      + 'las ondas de Elliott —Rendi las calcula o las marcás vos— y la regla para medir entre dos '
      + 'puntos. Lo que dibujás queda guardado en ese activo.',
  },
  {
    id: 'panorama',
    marca: 'tab-panorama',
    ruta: '/analisis-tecnico',
    busqueda: '?tab=panorama',
    titulo: 'Panorama: tu cartera de un vistazo',
    texto: 'Qué parte de tu cartera está en tendencia alcista de largo plazo y cómo cambió contra la '
      + 'semana pasada, el mapa de tus activos y lo último que cambió en la semana.',
  },
  {
    id: 'lista',
    marca: 'tab-lista',
    ruta: '/analisis-tecnico',
    busqueda: '?tab=lista',
    titulo: 'Tu lista: lo que tenés y lo que seguís',
    // Los tres medidores de cada tarjeta (TuLista.jsx): Tendencia (largo y
    // mediano plazo), Impulso y Fuerza.
    // El buscador de arriba suma a la watchlist sin salir de acá (Nico, 02/11):
    // `SUMAR_A_LA_WATCHLIST` en TuLista.jsx.
    texto: 'Cada activo de tu cartera y de tu watchlist con su lectura: la tendencia de largo y '
      + 'mediano plazo, el impulso y la fuerza. Con el buscador de arriba sumás activos a tu '
      + 'watchlist ahí mismo.',
  },
  {
    id: 'senales',
    marca: 'tab-senales',
    ruta: '/analisis-tecnico',
    busqueda: '?tab=senales',
    titulo: 'Señales: qué cambió esta semana',
    texto: 'Lo que cambió en los últimos 7 días en tu cartera y en tu watchlist, día por día: '
      + 'cambios de tendencia, máximos del año, impulso y fuerza. Muestra cómo se movieron los '
      + 'precios, no qué hacer con ellos.',
  },
  {
    id: 'backtesting',
    // Ilumina «¿Qué querés probar?» (pages/Backtesting.jsx), no la pestaña: en la
    // compu «Una cartera» casi no se descubría (producto 05/11, A6). La pestaña
    // queda abierta y marcada igual.
    marca: 'backtesting-modo',
    ruta: '/analisis-tecnico',
    busqueda: '?tab=backtesting',
    titulo: 'Backtesting: una regla o una cartera contra el pasado',
    // Las cuentas y las palabras: backend/backtest.py y utils/backtesting.js; la
    // cartera, backend/cartera_simulada.py y utils/carteraSimulada.js. Lo que
    // muestra es el pasado: el paso lo dice, como la pantalla.
    texto: 'Acá elegís qué probar: una regla técnica en un activo —o hasta 3—, al lado de comprar y no tocar '
      + 'nada, o una cartera entera contra el S&P 500 y el Nasdaq. Muestra el pasado: no dice qué va a pasar.',
  },
  {
    id: 'comparar',
    marca: 'tab-comparar',
    ruta: '/analisis-tecnico',
    // De vuelta en el Gráfico: Comparar no es una pestaña de acá, lleva a otra
    // pantalla (y el tutorial no la abre: la describe).
    busqueda: '?tab=',
    titulo: 'Comparar: varios activos en la misma vara',
    // Con «Ocultar saldos» no abre con los que más pesan sino con los primeros
    // de la A a la Z (urlDeCompararTuyos): por eso dice «algunos de los tuyos».
    texto: 'Te lleva a otra pantalla con hasta 4 activos juntos, todos arrancando en 100 el mismo '
      + 'día, para ver cuál se movió más. Si tenés activos, abre con algunos de los tuyos ya '
      + 'cargados.',
  },
  {
    id: 'pronto',
    marca: 'pronto',
    ruta: '/analisis-tecnico',
    busqueda: '?tab=',
    titulo: 'Lo que viene',
    // En el celular el «Pronto» no va (AnalisisTecnico.jsx): el paso se
    // saltea solo y el tutorial termina en Comparar.
    texto: 'Mercado es la parte que estamos armando para esta pantalla. Todavía no se puede abrir.',
  },
]
