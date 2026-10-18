# Proyecto Kubernetes 202630 — Gestor de Jobs

Herramienta de consola en Python que lanza tareas en Kubernetes sin escribir YAML. El usuario elige
un lenguaje, una tarea y una complejidad desde un menú, y el programa crea el `Job` con el cliente
oficial de Kubernetes. El mismo menú permite ver el estado de las tareas (con la causa cuando fallan),
leer sus logs y limpiar las que ya terminaron.

El proyecto parte del repositorio del profesor
([Proyecto-Kubernetes-202630](https://github.com/augustosalazar/Proyecto-Kubernetes-202630)):
las imágenes, el catálogo, el namespace y el script de preparación vienen de ahí, y el grupo
completó el gestor y añadió una tarea nueva en Python, `primos`.

**Video de demostración:** _(pendiente: se agrega aquí cuando esté grabado)_

## Contenido

1. [El recorrido de una tarea](#el-recorrido-de-una-tarea)
2. [Preparación y ejecución](#preparación-y-ejecución)
3. [Cómo se usa el menú](#cómo-se-usa-el-menú)
4. [Cómo está implementado](#cómo-está-implementado)
5. [La tarea adicional: primos](#la-tarea-adicional-primos)
6. [Estructura del repositorio](#estructura-del-repositorio)
7. [Qué se probó](#qué-se-probó)
8. [Problemas frecuentes](#problemas-frecuentes)

## El recorrido de una tarea

```text
gestor_jobs.py  ->  Job  ->  Pod  ->  contenedor con argumentos  ->  logs
```

1. **`gestor_jobs.py`** reúne las tres elecciones del usuario y arma un objeto `V1Job` con el cliente
   de Python. El objeto es el equivalente de un YAML de Job.
2. **El Job** se envía al namespace `estudiantes-202630`. Un Job es la instrucción; él no ejecuta nada, y lleva en su plantilla el molde del Pod.
3. **El Pod** lo crea Kubernetes a partir de esa plantilla. Es donde corre el programa, con los
   recursos reservados que pidió el Job.
4. **El contenedor** arranca la imagen elegida (`kubernates-202630-python`, `-java` o `-c`) con los
   argumentos `<tarea> <N>`, por ejemplo `fib 30`.
5. **Los logs** son lo que el contenedor escribe por la salida estándar. Pertenecen al Pod, y el gestor
   lo encuentra por la etiqueta `job-name=<nombre del Job>` que Kubernetes le pone al crearlo.

## Preparación y ejecución

Requisitos: Windows con PowerShell, Docker Desktop, Minikube, `kubectl` y Python 3.
Los comandos se ejecutan desde la carpeta raíz del repositorio.

Con Docker Desktop abierto:

```powershell
minikube start --driver=docker --container-runtime=docker
kubectl get nodes -o wide
kubectl apply -f .\k8s\00-namespace.yaml
.\scripts\preparar-imagenes.ps1
pip install -r .\entrega\requirements.txt
python .\entrega\gestor_jobs.py
```

- `kubectl get nodes -o wide` debe mostrar el nodo en `Ready` y `docker://` en la columna
  `CONTAINER-RUNTIME`. El `--container-runtime=docker` es necesario porque `preparar-imagenes.ps1`
  construye las imágenes contra el demonio Docker de Minikube (`minikube docker-env`), y con el runtime
  `containerd` ese comando falla. El runtime se fija al crear el clúster: para cambiarlo hay que hacer
  `minikube delete` y arrancar de nuevo.
- `preparar-imagenes.ps1` hay que volver a ejecutarlo **cada vez que cambie algo dentro de `imagenes\`**.
  No se usa `minikube image load`: no reemplaza una imagen que ya existe con el mismo nombre, y el clúster
  seguiría ejecutando la versión vieja sin avisar.
- Los nombres de imagen son locales (`kubernates-202630-*`, con esa ortografía) y no se publica ninguna.
- Se usó el cliente `kubernetes` 37.0.1 con Python 3.12. El `requirements.txt` no fija la versión.

## Cómo se usa el menú

```text
=== Gestor de Jobs - namespace estudiantes-202630 ===
  1. Ejecutar una tarea nueva
  2. Revisar el estado de las tareas
  3. Ver los logs de una tarea
  4. Limpiar las tareas terminadas
  5. Salir
```

- **1** pide lenguaje, tarea y complejidad. El menú de complejidad muestra el valor de N y la memoria que
  implica cada nivel. Al terminar imprime el nombre del Job, la imagen, los argumentos y los recursos.
- **2** lista todos los Jobs del namespace con su estado.
- **3** deja elegir una de esas tareas y muestra la salida de su contenedor.
- **4** muestra las tareas terminadas, pide confirmación y las borra. Las que siguen corriendo no se tocan.

Para comparar lo que muestra el menú con lo que ve el clúster:

```powershell
kubectl get jobs,pods -n estudiantes-202630
kubectl logs -n estudiantes-202630 job/<nombre-del-job>
```

## Cómo está implementado

Todo el gestor está en `entrega\gestor_jobs.py`. El código del menú, la carga del catálogo y la búsqueda
del Pod por etiqueta vienen del esqueleto del profesor. Las funciones que se escribieron son las que se
describen aquí. Ninguna invoca `kubectl`: todo pasa por el cliente de Python.

### Elegir la tarea: `seleccionar`

Pide por menú el lenguaje, la tarea y la complejidad, y devuelve seis valores: lenguaje, tarea,
complejidad, imagen, argumentos y recursos.

- La **imagen** sale del catálogo `catalogo\tareas.json`, que declara una imagen por lenguaje y las tareas
  que admite.
- Los **argumentos** son `[tarea, str(N)]`, por ejemplo `["fib", "30"]`. Son texto porque un contenedor
  recibe sus argumentos como una línea de comandos, y el programa de la imagen convierte `"30"` en número.
- Los **recursos** son la fila de la tabla `NIVELES` correspondiente a la complejidad.

La complejidad fija dos cosas a la vez: los recursos que el Job pide (`NIVELES`) y el tamaño del trabajo,
el valor de N (`TAMANOS`).

| Nivel     | CPU pedida / límite | Memoria pedida / límite |
| --------- | -------------------- | ------------------------ |
| `baja`  | 100m / 500m          | 64Mi / 128Mi             |
| `media` | 250m / 1000m         | 128Mi / 512Mi            |
| `alta`  | 500m / 2000m         | 256Mi / 1Gi              |

| Tarea       | `baja` | `media` | `alta` |
| ----------- | -------- | --------- | -------- |
| `hola`    | 0        | 0         | 0        |
| `ordenar` | 100000   | 1000000   | 3000000  |
| `fib`     | 25       | 30        | 35       |
| `matriz`  | 60       | 120       | 250      |
| `primos`  | 200000   | 2000000   | 10000000 |

### Crear el Job: `crear_job`

Arma el `V1Job` y lo envía con `create_namespaced_job`. Equivale a este YAML:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: <nombre>
  namespace: estudiantes-202630
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 300
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: tarea
          image: <imagen>
          imagePullPolicy: Never
          args: [<tarea>, <N>]
          resources:
            requests: { cpu: <cpu_request>, memory: <mem_request> }
            limits:   { cpu: <cpu_limit>,   memory: <mem_limit> }
```

Cada campo responde a una decisión:

| Campo                     | Valor                    | Por qué                                                                                                                                                                                           |
| ------------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `resources.requests`    | fila del nivel           | Es lo que Kubernetes reserva y usa para decidir dónde poner el Pod.                                                                                                                               |
| `resources.limits`      | fila del nivel           | Es el tope. Si el contenedor supera el límite de memoria, Kubernetes lo mata con `OOMKilled`; si supera el de CPU, lo frena.                                                                    |
| `imagePullPolicy`       | `Never`                | Las imágenes existen solo dentro de Minikube. Kubernetes nunca intenta descargarlas, y si falta una el Pod queda en `ErrImageNeverPull`, causa que el gestor muestra.                           |
| `restartPolicy`         | `Never`                | Si el contenedor falla, el Pod no se reinicia dentro de sí mismo: el fallo queda visible.                                                                                                         |
| `backoffLimit`          | `0`                    | `restartPolicy` evita reiniciar el contenedor, y `backoffLimit` evita que el Job cree Pods de reemplazo. Con el valor por defecto (6), una tarea que falla por memoria se ejecutaría 7 veces. |
| `activeDeadlineSeconds` | `PLAZO_SEGUNDOS` (300) | Si el Job pasa de 300 s, Kubernetes lo corta. Sin plazo, una tarea colgada ocuparía el nodo indefinidamente.                                                                                      |

El nombre del Job lo construye `nombre_job` como `<lenguaje>-<tarea>-<complejidad>-<hora>`. La hora
permite repetir la misma tarea sin chocar con un Job anterior que siga en el namespace.

### Estado: `describir_estado`, `causa_en_pod` y `listar_jobs`

El estado se obtiene en dos niveles, porque el Job y el Pod saben cosas distintas.

**El Job** lleva tres contadores en su `status`: `active`, `succeeded` y `failed` (valen `None` mientras
Kubernetes no los fija). `describir_estado` los traduce a texto. Antes de eso revisa las condiciones del
Job: si alguna tiene el motivo `DeadlineExceeded`, el plazo se venció. Kubernetes marca esa condición
primero como `FailureTarget` y, cuando el Pod termina de apagarse (hasta unos 30 s después), como `Failed`;
el gestor acepta las dos para mostrar la causa desde que ocurre.

**El Pod** sabe por qué murió o por qué no arranca. `causa_en_pod` busca el Pod por la etiqueta
`job-name` y mira el estado de su contenedor: `terminated.reason == "OOMKilled"` indica falta de memoria,
y `waiting.reason == "ErrImageNeverPull"` indica que la imagen no está en el nodo. `listar_jobs` la usa en
dos casos: cuando el Job falló (para distinguir `OOMKilled`) y cuando figura en ejecución (porque un Pod sin
imagen cuenta como activo y, sin esta revisión, se vería «en ejecución» para siempre).

| Situación                  | Texto en el menú                              |
| --------------------------- | ---------------------------------------------- |
| Hay Pods activos            | `en ejecucion`                               |
| Terminó bien               | `termino correctamente`                      |
| Falló, causa desconocida   | `fallo`                                      |
| Falló por memoria          | `fallo: sin memoria (OOMKilled)`             |
| Superó el plazo            | `fallo: tiempo agotado (DeadlineExceeded)`   |
| Falta la imagen             | `atascado: imagen no encontrada`             |
| Los tres contadores en cero | `pendiente (el Pod todavia no ha arrancado)` |

### Logs: `consultar_logs`

Busca el Pod del Job por la etiqueta `job-name=<nombre>` y pide su salida con `read_namespaced_pod_log`.
Se usa `_preload_content=False` y se decodifica el resultado: sin esa opción, el cliente devuelve la
representación de los bytes (`b'...'`) y todo el log sale en una sola línea.

### Limpieza: `jobs_terminados` y `eliminar_job`

`jobs_terminados` devuelve los Jobs sin Pods activos y con al menos uno correcto o fallido. Un Job en
ejecución no entra, porque la limpieza no puede cancelar trabajo que sigue corriendo.

`eliminar_job` borra el Job con `propagation_policy="Background"`. Esa opción hace que Kubernetes borre
también los Pods que el Job creó. Sin ella, el Job desaparece y su Pod queda huérfano en el namespace.

## La tarea adicional: primos

Cuenta los números primos menores o iguales que N, con una criba de Eratóstenes escrita con bucles simples.
Está en Python, en `imagenes\python\tareas.py`, y respeta el contrato de las otras tareas: recibe
`<tarea> <N>`, escribe su progreso por stdout (al llegar al 25 %, 50 %, 75 % y 100 %), y la última línea es
un JSON de una sola línea con el resultado. Para `n < 2` la cantidad es 0.

```powershell
cd imagenes\python
python tareas.py primos 1000000
```

La última línea es `{"tarea": "primos", "lenguaje": "python", "ms": ..., "n": 1000000, "cantidad": 78498}`.

Para que la tarea quede integrada hubo que tocar tres sitios, que son los que pide añadir cualquier
tarea nueva:

1. `imagenes\python\tareas.py`: la función `primos` y su entrada en el diccionario `TAREAS`.
2. `catalogo\tareas.json`: `primos` en la lista de tareas de Python (Java y C no cambian).
3. `entrega\gestor_jobs.py`: la fila `primos` de la tabla `TAMANOS`.

Después se reconstruyen las imágenes con `.\scripts\preparar-imagenes.ps1`.

## Estructura del repositorio

```text
catalogo\tareas.json         lenguajes, imagen de cada uno y tareas que admite
entrega\gestor_jobs.py       el gestor: menú, creación, estado, logs y limpieza
entrega\requirements.txt     dependencias de Python (kubernetes)
imagenes\python\             Dockerfile y tareas.py (incluye primos)
imagenes\java\               Dockerfile y Tareas.java
imagenes\c\                  Dockerfile y tareas.c
k8s\00-namespace.yaml        namespace estudiantes-202630
scripts\preparar-imagenes.ps1  construye las imágenes dentro de Minikube
```

## Qué se probó

Sobre Minikube con Kubernetes v1.37.0 y runtime `docker`, usando el menú:

- Las cuatro tareas originales en Python, Java y C en nivel `baja`, y `primos` en Python.
- Otras combinaciones en `media` y `alta`: `ordenar` en Python, `matriz` en Java y `fib` en C (`media`);
  `primos` y `matriz` en Python, `ordenar` en C y `fib` en Java (`alta`).
  En todas, el estado final fue `termino correctamente` y la última línea del log era un JSON válido con la
  tarea y el lenguaje esperados. `primos` dio 78498 hasta 1.000.000 y 664579 hasta 10.000.000.
- Un Job con límite de memoria muy bajo muestra `fallo: sin memoria (OOMKilled)`.
- Un Job con una imagen inexistente muestra `atascado: imagen no encontrada`.
- Un Job con un plazo de 3 segundos que no alcanza muestra `fallo: tiempo agotado (DeadlineExceeded)`.
  Estas tres pruebas se hicieron con valores de prueba que no están en el código.
- La limpieza deja fuera un Job que sigue corriendo y el que está atascado por la imagen, y devuelve los
  demás. Al eliminar un Job desaparece también su Pod.

## Problemas frecuentes

| Síntoma                                                                                 | Causa y solución                                                                                                                                   |
| ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `connectex: No connection could be made` o `no se pudo conectar`                     | El clúster está apagado. Abrir Docker Desktop y ejecutar `minikube start`.                                                                      |
| `preparar-imagenes.ps1` falla con `SSH_AGENT_START`                                  | Minikube arrancó con el runtime `containerd`. Hay que hacer `minikube delete` y `minikube start --driver=docker --container-runtime=docker`. |
| `the path ".\k8s\00-namespace.yaml" does not exist`                                    | El comando se ejecutó fuera de la raíz del repositorio.                                                                                           |
| Un Job queda «en ejecución» o «atascado» y no avanza                                | La imagen no está dentro de Minikube (`ErrImageNeverPull`). Volver a ejecutar `.\scripts\preparar-imagenes.ps1`.                               |
| Un Job con plazo vencido muestra `fallo: tiempo agotado` sin que haya terminado el Pod | Es normal: Kubernetes tarda hasta 30 s en apagar el Pod después de marcar el plazo.                                                                |
| `ModuleNotFoundError: No module named 'kubernetes'`                                    | Falta la dependencia: `pip install -r .\entrega\requirements.txt`.                                                                                |
