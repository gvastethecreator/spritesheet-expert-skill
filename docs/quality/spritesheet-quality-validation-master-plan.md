# Plan maestro de calidad y validacion de assets 2D

Estado: **borrador operativo, basado en el repositorio al 2026-07-11**.

Este documento responde dos preguntas distintas:

1. Que casos promete o prepara actualmente la suite.
2. Que evidencia debe existir antes de considerar estable cada caso.

No considera una capacidad estable solo porque exista un schema, un preset o un
script. La madurez se clasifica como:

- **Operativa:** contrato, procesamiento, QA deterministico y prueba
  representativa disponibles.
- **Parcial:** existe ruta ejecutable, pero faltan evals representativos o una
  prueba visual estable.
- **Scaffold:** existen schemas/tests iniciales, pero la skill de usuario o el
  workflow end-to-end todavia no esta implementado.
- **No cubierta:** fuera del alcance raster 2D o sin ruta honesta.

## 1. Diagnostico ejecutivo

El problema actual no es solamente la calidad de una imagen. El pipeline puede
confundir cuatro cosas diferentes:

- consistencia de color con consistencia anatomica;
- alineacion del canvas con movimiento correcto;
- cambio de silueta con biomecanica correcta;
- una hoja visualmente atractiva con una animacion util en runtime.

`sideview-walk` revelo tres falsos positivos consecutivos:

1. El maniqui de capsulas mantenia la fase, pero el movimiento parecia un
   recorte articulado y rigido.
2. El maniqui organico cambiaba colores entre formas casi congeladas, simulando
   alternancia sin mover realmente brazos y piernas.
3. El maniqui articulado ya cambia la silueta, pero una pose de paso puede seguir
   siendo biomecanicamente incorrecta: pie de soporte en punta, swing atrasado o
   rodilla demasiado alta.

Por lo tanto, ninguna metrica unica puede aprobar una animacion. Cada workflow
necesita contrato de fases, invariantes geometricas, QA de identidad, reproduccion
y revision visual con evidencia vigente.

## 2. Inventario real de cobertura

### 2.1 Motor `spritesheet-expert`

El contrato v2 reconoce ocho clases:

| Clase | Semanticas principales | Madurez actual |
|---|---|---|
| `sprite` | animacion, variantes | Parcial; pipeline amplio, referencias de movimiento aun inestables |
| `tileset` | tiles, proyeccion top-down/isometrica | Parcial; gates de slots e isometria disponibles |
| `texture` | texturas seamless | Parcial; composicion disponible, eval visual incompleto |
| `asset` | packs genericos por slots | Parcial |
| `prop` | props/items/pickups | Parcial |
| `icon` | iconos raster/UI pequenos | Parcial |
| `ui` | componentes raster | Parcial dentro del motor; kit reusable separado es scaffold |
| `vfx` | efectos temporales | Parcial; contrato temporal disponible, masters sin estabilizar |

Modos de extraccion: `components` y `slots`. Semanticas declaradas:
`animation`, `variants`, `tiles`, `seamless-textures`, `still-assets`,
`effects` y `user-defined`.

### 2.2 Presets incluidos

| Preset | Casos |
|---|---|
| `codex-pet` | idle, carrera bilateral, saludo, salto, fallo, espera, review |
| `platformer-character` | idle, run, jump, fall, land, attack, hurt, death |
| `topdown-character` | idle/walk/attack en cuatro direcciones |
| `isometric-character` | idle/walk/attack en cuatro diagonales |
| `combat-character` | stance, walk, run, ataques ligero/pesado, block, dodge, hit, death |
| `fighting-game-character` | idle, avance/retroceso, crouch, jump, punch, kick, special, hitstun, knockdown, win |
| `rpg-monster` | idle, move, attack, cast, hit, death, taunt, sleep |
| `ui-avatar` | idle, blink, talk y emociones |
| `tileset-topdown` | terrain, paths, water, walls, decor |
| `tileset-platformer` | ground, slopes, ledges, hazards, decor |
| `texture-pack` | stone, wood, metal, fabric, ground |
| `asset-pack` | props, pickups, UI icons, VFX, decals |
| `custom-asset-atlas` | slots definidos por el usuario |
| `custom-atlas` | filas/celdas definidas por el usuario |

Que un preset exista significa que se puede preparar su contrato. No significa
que cada fila tenga una generacion representativa aprobada.

### 2.3 Workflows temporales

| Workflow | Casos que cubre | Riesgo dominante | Estado representativo |
|---|---|---|---|
| `sideview-locomotion` | walk, run, move, advance, retreat | contactos falsos, foot sliding, recoloreado | Walk en estabilizacion |
| `topdown-locomotion` | 4/8 direcciones, diagonales | proyeccion, handedness, pierna oculta | Pendiente |
| `idle-breath` | idle/espera/respiracion | zoom, bob uniforme, loop pop | Pendiente |
| `fighting-stance-idle` | guardia/stance | falta de peso/rol, manos congeladas | Pendiente |
| `responsive-jump` | jump/fall/land | escala falsa, arco debil, baseline | Pendiente |
| `combat-quick-strike` | jab/punch/kick rapido | contacto ilegible, smear incorrecto | Pendiente |
| `combat-power-strike` | heavy/special/weapon | anticipacion, peso, recovery | Pendiente |
| `topdown-weapon-attack` | ataques direccionales | arma cambia de mano/proyeccion | Pendiente |
| `hit-reaction-knockdown` | hurt/hit/death/fall | fuerza ilegible, miniaturizacion | Pendiente |
| `run-gun-layered-motion` | correr y disparar | piernas/torso se bloquean mutuamente | Pendiente |
| `vfx-buildup-peak-decay` | impacto, fuego, humo, explosion | area plana, pivot, alpha | Pendiente |
| `water-loop` | agua, ripple, waterfall | seam temporal/espacial | Pendiente |
| `wind-ambient-loop` | tela, pelo, plantas, polvo | movimiento sincronizado/artificial | Pendiente |
| `pickup-feedback` | coin, gem, powerup | hazard read, loop/escala | Pendiente |
| `tiny-motion` | 8x8, 8x16, sprites minimos | frames redundantes/flicker | Deterministico parcial |

`sideview-walk` y `sideview-run` comparten el identificador de locomocion, pero
deben estabilizarse como casos distintos: caminar conserva apoyo; correr requiere
fase de vuelo, inclinacion y timing diferentes.

### 2.4 Vistas de locomocion que requieren masters independientes

1. Lateral derecha; izquierda solo se deriva por espejo cuando la asimetria lo
   permite.
2. Frontal.
3. Trasera.
4. Tres cuartos frontal derecha/izquierda.
5. Tres cuartos trasera derecha/izquierda.
6. Top-down cardinal.
7. Top-down diagonal.
8. Isometrica/dimetrica 2:1.

Cada combinacion `mecanica x vista` es un caso de evaluacion. No se aprueba una
vista por extrapolacion de otra.

### 2.5 Suite ampliada

| Hoja | Casos declarados | Estado honesto |
|---|---|---|
| `build-static-game-assets` | prop, item, pickup, icon, cursor, badge, portrait, key art | Scaffold: schema/validator inicial; `SKILL.md` sin implementar |
| `build-game-backgrounds` | sky/far/mid/near/foreground/fog/lighting, parallax | Scaffold |
| `build-game-ui-kits` | button/panel/bar/icon/cursor/badge/frame/toggle y estados | Scaffold |
| `compose-asset-mockups` | boards, contact sheets, gameplay, store, social | Scaffold |
| `produce-2d-assets` | inventario/DAG/variantes/entrega multifamilia | Scaffold |

No deben publicarse como skills estables hasta reemplazar los documentos TODO,
cerrar sus rutas end-to-end y ejecutar sus evals representativos.

### 2.6 Fuera de alcance

- Modelos 3D, rigs 3D, materiales PBR completos.
- Audio, musica, video y cinematicas.
- Fuentes tipograficas y logos vectoriales editables.
- PSD/archivos de autor multicapa como promesa de salida.
- UI funcional en codigo. La suite produce assets raster y evidencia; no una app.
- Garantia de calidad artistica basada solo en numeros.

## 3. Taxonomia de fallos

### A. Contrato

- numero, orden o duracion de frames incorrectos;
- asset kind, vista, facing o workflow ambiguo;
- variantes tratadas como tiempo;
- falta de source hash, licencia o provenance.

### B. Identidad

- cabeza, torso, manos o pies cambian de tamano;
- colores/asimetrias saltan de limb;
- ropa, arma o rostro se redescubren por frame;
- cambio de camara, perspectiva o escala.

### C. Pose y biomecanica

- recoloreado sin desplazamiento real;
- articulaciones congeladas;
- centro de masa fuera del soporte;
- rodillas/codos imposibles;
- contacto, pass, anticipation, hit o recovery ausentes;
- marcha alta confundida con caminata o vuelo confundido con apoyo.

### D. Registro y runtime

- root/pivot deriva;
- baseline o foot sliding;
- cropping, overlap o padding variable;
- loop seam con pop;
- timing correcto en contact sheet pero incorrecto a FPS real.

### E. Render y extraccion

- alpha roto, halo/chroma visible, agujeros internos;
- sampling borroso en pixel art;
- paleta o grosor de linea inconsistentes;
- bleed entre celdas, gutter insuficiente;
- decoracion/fondo/texto no solicitado.

### F. Semantica por familia

- tile que no repite o pivot isometrico incorrecto;
- textura con seam;
- VFX sin buildup/peak/decay o emitter inestable;
- nine-slice que se deforma;
- parallax con orden/profundidad incorrectos;
- mockup que afirma ser runtime sin evidencia.

## 4. Arquitectura de calidad fail-closed

Cada caso debe pasar estas capas en orden. Un fallo temprano bloquea las capas
siguientes.

### Gate 0: definicion del caso

- request schema valido;
- workflow, vista, facing, frames, FPS, loop y pivots explicitos;
- identidad/style anchors y licencias conocidas;
- hard invariants y rubric especificos escritos antes de generar.

### Gate 1: referencia mecanica

- las poses clave se resuelven antes de los inbetweens;
- cada key pose tiene soporte, linea de accion y articulaciones verificables;
- un control monocromo demuestra que la silueta cambia sin depender del color;
- las referencias de color conservan identidad anatomica, no solo apariencia.

### Gate 2: generacion

- bitmap final creado por Image Gen o importado honestamente;
- prompt, referencias, orden de dependencia y candidatos preservados;
- maximo dos intentos con el mismo metodo por frame/caso;
- tras dos fallos iguales se cambia de representacion o control, no se reescribe
  el mismo prompt una tercera vez.

### Gate 3: consistencia estatica

- frame count, dimensiones, camera y fondo;
- bboxes de cabeza/torso/manos/pies;
- root x, baseline, volumen, line weight y paleta;
- no crop, overlap, debris, texto ni elementos inventados.

### Gate 4: semantica temporal o espacial

- fases obligatorias presentes;
- contactos/apoyos/pivots correctos;
- cambio de silueta color-independent;
- movimiento por limb y no simple recoloreado;
- tiles/texturas: repeat y proyeccion;
- UI: estados/nine-slice; VFX: area/pivot/phase.

### Gate 5: runtime

- manifest real, no slicing supuesto;
- reproduccion a FPS y duraciones declaradas;
- inspeccion de loop seam, jitter, sliding y readability a tamano objetivo;
- viewport/DPR/filter/background registrados.

### Gate 6: revision visual

- contact sheet, onion skin y playback;
- veredicto por frame/fase con nota concreta;
- artifact hashes actuales;
- ninguna puntuacion compensa un hard invariant fallido.

### Gate 7: transferencia y release

- la referencia se transfiere a un personaje real sin perder identidad/movimiento;
- al menos dos ejecuciones visuales consecutivas superan el caso;
- master aprobado, hash-pinned y con sidecar; candidatos nunca entran al catalogo;
- regression case positivo y mutaciones negativas guardadas.

## 5. Estrategia especifica para animacion generada

### 5.1 Separar mecanica y render

Una sola llamada intenta resolver demasiadas variables. El flujo estable sera:

1. **Mechanics control:** pose simple, alta legibilidad de soporte y joints.
2. **Mechanics QA:** silueta, contactos, centro de masa y arcs.
3. **Organic render:** Image Gen convierte la pose aceptada en maniqui organico,
   conservando geometria, colores anatomicos e identidad.
4. **Render QA:** verifica que el estilizado no haya alterado la mecanica.

El mechanics control puede usar geometria deterministica o material licenciado
como guia, pero nunca se presenta como arte final. Todos los frames finales
representativos siguen siendo Image Gen o importados.

### 5.2 Orden pose-to-pose para seis frames

```text
1 contact A
  -> 6 pass B
1 + 6
  -> 4 contact B
1 + 4
  -> 2 down A
2 + 4
  -> 3 pass A-to-B
4 + 6
  -> 5 down B
```

Un frame solo puede alimentar el siguiente si ya tiene veredicto individual.

### 5.3 Controles automaticos minimos

- diferencia de silueta alineada, ignorando colores;
- centroides/bboxes permanentes por limb;
- drift de torso/root y escala;
- contacto de cada pie con baseline;
- alternancia de soporte;
- distancia recorrida por manos y pies;
- promedio y minimo de cambio entre frames;
- seam ultimo-primero.

Estos controles detectan congelamiento y recoloreado, pero no certifican peso,
arcos o anatomia; eso permanece como gate visual obligatorio.

### 5.4 Controles visuales obligatorios

Para cada frame registrar:

- fase esperada y fase observada;
- pie de soporte y pie de swing;
- posicion de pelvis/centro de masa;
- rodillas, tobillos, hombros y codos;
- contrabalanceo de brazos;
- continuidad desde el frame anterior y hacia el siguiente;
- defectos de identidad/render;
- `pass`, `fail` o `blocked`, nunca “parece mejor”.

## 6. Matriz de pruebas por familia

| Familia | Prueba positiva minima | Mutaciones negativas obligatorias | Evidencia visual |
|---|---|---|---|
| Side-view walk | 6/8 fases, apoyo continuo, loop | recolor-only, frozen arms, high-knee, sliding | contact, onion, HTML/GIF, personaje real |
| Side-view run | contacts/pass/flight | sin flight, walk acelerado, scale drift | playback y trayectoria root |
| Top-down locomotion | 4 cardinales + diagonales | misma pierna, handedness swap, thickness drift | rotation/direction board |
| Idle/stance | breath/weight loop | global zoom, uniform bob, frozen guard | loop + bbox overlays |
| Jump/fall/land | arco y retorno baseline | miniaturizacion, sin apex, landing flotante | arc plot + playback |
| Quick/power strike | startup/contact/recovery | contacto ausente, smear inverso, teleport | hit-frame board + playback |
| Hit/knockdown | fuerza y settle | surprised idle, slide, shrink | force/readability board |
| Run-and-gun | piernas y aim independientes | torso congela piernas o viceversa | layered playback |
| Tiny motion | 2-4 cambios utiles | frames redundantes, flicker, color nuevo | 1x y ampliado nearest |
| VFX | buildup/peak/decay, pivot | area plana, alpha halo, emitter drift | checker/dark/light playback |
| Water/wind | loop matematico y material | seam, sync uniforme, foco robado | tiled/scroll playback |
| Tileset top-down | catalogo y edges | seam/corner roto, label faltante | repeat/map proof |
| Isometric tiles | 2:1, pivot, depth | ratio/pivot/depth invalidos | map/depth proof |
| Texture | repeticion y texel density | bordes rotos, perspectiva | 3x3 repeat |
| Props/items/icons | rol, escala, silhouette | crop, label ausente, set drift | target-size catalog |
| UI kit | estados, safe area, nine-slice | estado faltante, stretch/contrast | state/stretch board |
| Background/parallax | layers, camera, seams | orden/depth/horizon incorrecto | scroll/parallax preview |
| Portrait/key art | crop, identity, target profile | face drift, unsafe crop | native + thumbnail |
| Import irregular | boxes/manifest confiables | auto-detect falso verde | segmentation/registration |
| Mockup/presentation | truth class, safe zones, copy | stale asset, fake runtime, font/license | native + thumbnail + guides |
| Multifamily pack | DAG, style bible, hashes | stale child, palette/projection drift | delivery board + reports |

## 7. Orden de estabilizacion

No abrir el siguiente workflow hasta cerrar el anterior con prueba representativa:

1. `sideview-walk` de seis frames.
2. `sideview-walk` de ocho frames y reducciones 4/6.
3. `sideview-run`.
4. `topdown-locomotion` cardinal y diagonal.
5. `idle-breath`.
6. `fighting-stance-idle`.
7. `responsive-jump` y fall/land.
8. quick strike.
9. power strike.
10. top-down weapon attack.
11. hit reaction/knockdown.
12. run-and-gun.
13. tiny motion.
14. pickup feedback.
15. VFX buildup/peak/decay.
16. water loop.
17. wind loop.
18. tilesets top-down y platformer.
19. tilesets isometricos.
20. textures.
21. static packs/portraits.
22. UI kits.
23. backgrounds/parallax.
24. imports irregulares.
25. mockups/presentaciones.
26. pack multifamilia end-to-end.

## 8. Protocolo para probar cada caso

### Paso A: contrato y corpus

1. Escribir `case.json` con input, output, hard invariants y rubric.
2. Crear un positivo deterministico para probar el harness.
3. Crear al menos tres mutaciones: fallo obvio, fallo sutil y stale evidence.
4. Seleccionar una referencia representativa licenciada o generada.

### Paso B: generacion representativa

1. Ejecutar cuatro candidatos iniciales sin escoger silenciosamente el mejor.
2. Medir first-pass success por candidato.
3. Permitir una reparacion focalizada por candidato.
4. Si best-of-two no llega a 100%, el workflow sigue experimental.
5. Preservar prompts, referencias, candidatos rechazados y razones.

### Paso C: procesamiento

1. Ingesta y provenance con hashes.
2. Extraccion/matte/sampling segun familia.
3. Registro, compose, manifest y previews.
4. Gates deterministicos aplicables ejecutados por `validate_run.py`.

### Paso D: runtime y adjudicacion

1. Reproducir/renderizar en la ruta real.
2. Revisar tamano nativo y ampliado.
3. Completar rubric sin conocer el diagnostico esperado cuando sea posible.
4. Guardar veredicto, hashes y capturas.
5. Ejecutar el caso una segunda vez para medir estabilidad del modelo.

## 9. Umbrales de release

### Hard invariants

- 100% de contratos, frame counts, provenance, hashes y dimensiones.
- 0 crop, overlap, path escape, placeholder o evidencia stale.
- 100% de fases/contactos obligatorios en animacion.
- 0 recolor-only, frozen-limb o support-side false positive.
- 100% de outputs cargables mediante manifest/runtime.

### Rubric visual

- mediana global >= 4/5;
- ninguna dimension critica < 3/5;
- first-pass success >= 80%;
- best-of-two success = 100%;
- dos ejecuciones model-backed consecutivas verdes antes de promocionar.

### Coste y reintentos

- registrar llamadas Image Gen por asset/frame;
- maximo dos intentos con el mismo control;
- distinguir coste de discovery, repair y final accepted;
- si un caso necesita correcciones manuales repetidas, no es template estable;
- una mejora de best-case no oculta una tasa first-pass baja.

## 10. Prueba piloto: `sideview-walk`

### Objetivo

Producir un master lateral derecho de seis frames que luego pueda transferirse a
un personaje real sin perder movimiento o identidad.

### Fases

| Frame | Fase | Soporte | Geometria obligatoria |
|---:|---|---|---|
| 1 | orange contact | doble contacto | orange adelante, green atras; blue arm adelante |
| 2 | orange down | orange + green toe | pelvis baja, orange knee flexiona, green heel sube |
| 3 | green pass | orange | green swing pasa al frente bajo; brazos cruzan neutral |
| 4 | green contact | doble contacto | green adelante, orange atras; red arm adelante |
| 5 | green down | green + orange toe | complemento real del frame 2 |
| 6 | orange pass | green | orange swing pasa al frente bajo; prepara frame 1 |

### Estado de candidatos

- 001-003: whole-sheet/view failures.
- 004: rechazado por rigidez cutout.
- 005: rechazado por recoloreado sobre geometria casi estatica.
- 006 mannequin: el cambio a `mechanics-control -> organic-render` corrigio los
  dos pass, los inbetweens de brazos y los contactos. El checker mecanico y el
  playback HTML estricto a 8 FPS pasan.
- 006 real-character transfer: rechazado. Aunque conserva bastante bien la
  identidad, 1/2/4/5 colapsan hacia una zancada generica, los brazos no
  completan el counter-swing, hay drift de escala y el frame 1 introduce una
  linea de suelo. El master mecanico no se promociona por este fallo downstream.

### Criterio de salida

La prueba solo pasa cuando:

1. Los seis frames superan veredicto individual.
2. El checker color-independent y de limbs pasa.
3. Playback a 8 FPS y loop seam pasan.
4. La transferencia a un personaje real conserva identidad y mecanica.
5. El navegador carga el manifest/sheet sin errores.
6. El master y su sidecar de aprobacion quedan hash-pinned.

Hasta entonces el workflow se declara **experimental** y ningun candidato se
materializa automaticamente como referencia de produccion.

## 11. Entregables de implementacion

1. Catalogo versionado de eval cases y threshold profiles.
2. Checker de movimiento por silueta y limbs independiente del color.
3. Sidecars de veredicto por frame y por fase.
4. Viewer con overlays de baseline, root, bboxes, limb centroids y onion skin.
5. Harness que ejecuta positivos y mutaciones negativas.
6. Reporte first-pass/best-of-two/coste por workflow.
7. Masters aprobados con hashes y provenance.
8. Evals de transferencia a personaje real.
9. Release dashboard por familia y workflow.
10. Skills scaffold promovidas solo cuando sus rutas end-to-end y evals esten
    verdes.

## 12. Decision actual

El piloto valida el enfoque de separar mecanica y render, pero tambien muestra
que una referencia visual por si sola no obliga a Image Gen a conservar los
joints durante el cambio de personaje. La siguiente iteracion de `sideview-walk`
debe incorporar un gate de concordancia pose/silueta contra el control antes de
aceptar cada render vestido. Se regeneraran solo 1/2/4/5, se rechazaran artefactos
de fondo antes del registro y se repetiran contact sheet, playback y seam 6->1.
No se inicia el siguiente workflow ni se publica un template de walk mientras
la transferencia real no pase esos gates.
