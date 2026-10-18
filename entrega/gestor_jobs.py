"""Gestor de Jobs de Kubernetes para la practica 202630.

ESQUELETO: el andamiaje del menu y del cliente de Kubernetes ya esta puesto.
Lo que falta esta marcado con TODO y con `...` en los campos a completar. El
foco de la practica es Kubernetes, no Python: no tienes que inventar la
estructura del programa, sino entender que significa cada campo del Job.

El programa es un menu interactivo:

    1. Ejecutar una tarea nueva
    2. Revisar el estado de las tareas
    3. Ver los logs de una tarea
    4. Limpiar las tareas terminadas
    5. Salir

No se permite invocar `kubectl` desde este programa; el Job se crea con el
cliente oficial de Python (`pip install -r requirements.txt`).

Se ejecuta sin argumentos:

    python gestor_jobs.py
"""

import json
import re
import time
from pathlib import Path

from kubernetes import client, config
from kubernetes.client.rest import ApiException

NAMESPACE = "estudiantes-202630"
RAIZ = Path(__file__).resolve().parent.parent
CATALOGO = RAIZ / "catalogo" / "tareas.json"

# Segundos que puede vivir un Job antes de que Kubernetes lo corte por su cuenta
# (queda como fallido con motivo DeadlineExceeded). Sin plazo, una tarea
# colgada ocuparia el nodo indefinidamente.
PLAZO_SEGUNDOS = 300

# La complejidad elegida fija DOS cosas a la vez:
#
#   - los recursos que se le piden al contenedor (NIVELES), y
#   - el tamano del trabajo, el parametro N que recibe la tarea (TAMANOS).
#
# Un nivel alto pide mas CPU y mas memoria, y ademas manda un N mas grande.
NIVELES = {
    "baja": {
        "cpu_request": "100m",
        "cpu_limit": "500m",
        "mem_request": "64Mi",
        "mem_limit": "128Mi",
    },
    "media": {
        "cpu_request": "250m",
        "cpu_limit": "1000m",
        "mem_request": "128Mi",
        "mem_limit": "512Mi",
    },
    "alta": {
        "cpu_request": "500m",
        "cpu_limit": "2000m",
        "mem_request": "256Mi",
        "mem_limit": "1Gi",
    },
}

# Valor de N por tarea y nivel. Al agregar una tarea nueva al catalogo, agrega
# aqui su fila.
TAMANOS = {
    "hola": {"baja": 0, "media": 0, "alta": 0},
    "ordenar": {"baja": 100000, "media": 1000000, "alta": 3000000},
    "fib": {"baja": 25, "media": 30, "alta": 35},
    "matriz": {"baja": 60, "media": 120, "alta": 250},
    "primos": {"baja": 200000, "media": 2000000, "alta": 10000000},
}


def cargar_catalogo():
    """Devuelve el contenido de catalogo/tareas.json como diccionario."""
    with CATALOGO.open(encoding="utf-8") as archivo:
        return json.load(archivo)


# ---------------------------------------------------------------------------
# Utilidades del menu
# ---------------------------------------------------------------------------

def elegir_opcion(titulo, opciones):
    """Muestra una lista numerada y devuelve la opcion elegida, o None.

    `opciones` es una lista de textos. Devuelve el texto elegido. Una entrada
    vacia o un 0 significan "volver atras" y devuelven None.
    """
    print(f"\n{titulo}")
    for numero, opcion in enumerate(opciones, start=1):
        print(f"  {numero}. {opcion}")
    print("  0. Volver")

    while True:
        respuesta = input("Opcion: ").strip()
        if respuesta in ("", "0"):
            return None
        if respuesta.isdigit() and 1 <= int(respuesta) <= len(opciones):
            return opciones[int(respuesta) - 1]
        print(f"Escribe un numero entre 0 y {len(opciones)}.")


# ---------------------------------------------------------------------------
# 1. Seleccion de lenguaje, tarea y complejidad
# ---------------------------------------------------------------------------

def seleccionar(catalogo):
    """Pide lenguaje, tarea y complejidad por menu.

    Devuelve (lenguaje, tarea, complejidad, imagen, argumentos, recursos), o
    None si el usuario decide volver. `argumentos` es la lista que recibira el
    contenedor: el nombre de la tarea y el valor de N, por ejemplo
    ["fib", "30"]. `recursos` es la fila de NIVELES del nivel elegido.
    """
    lenguaje = elegir_opcion("Lenguaje:", sorted(catalogo))
    if lenguaje is None:
        return None

    definicion = catalogo[lenguaje]

    tarea = elegir_opcion("Tarea:", definicion["tasks"])

    if tarea is None:
        return None

    tamanos = TAMANOS.get(tarea)
    if not tamanos:
        print(f"La tarea {tarea} no tiene tamanos definidos en TAMANOS.")
        return None

    # El menu muestra cada nivel con el N y la memoria que implica, para que se
    # vea que la complejidad es mas que una etiqueta.
    etiquetas = [
        f"{nivel} (N={tamanos[nivel]}, memoria {NIVELES[nivel]['mem_limit']})"
        for nivel in NIVELES
    ]
    etiqueta = elegir_opcion("Complejidad:", etiquetas)
    if etiqueta is None:
        return None
    complejidad = etiqueta.split(" ")[0]

    imagen = definicion["image"]
    # Los argumentos de un contenedor son texto (como en una linea de comandos):
    # N se convierte con str(), la imagen lo vuelve a leer como numero.
    argumentos = [tarea, str(tamanos[complejidad])]
    recursos = NIVELES[complejidad]

    return lenguaje, tarea, complejidad, imagen, argumentos, recursos


def nombre_job(lenguaje, tarea, complejidad):
    """Construye un nombre de Job valido para Kubernetes.

    Reglas de Kubernetes: solo minusculas, digitos y guiones, maximo 63
    caracteres. El sufijo de tiempo permite repetir la misma tarea sin chocar
    con un Job anterior que siga en el namespace.
    """
    base = f"{lenguaje}-{tarea}-{complejidad}-{int(time.time())}".lower()
    return re.sub(r"[^a-z0-9-]", "-", base)[:63].strip("-")


# ---------------------------------------------------------------------------
# 2. Creacion del Job con el cliente Python de Kubernetes
# ---------------------------------------------------------------------------

def cliente_batch():
    """Carga la configuracion de kubeconfig y devuelve un BatchV1Api."""
    config.load_kube_config()
    return client.BatchV1Api()


def crear_job(nombre, imagen, argumentos, recursos):
    """Crea el Job en el namespace `NAMESPACE` y devuelve su nombre.

    El objeto que se arma abajo es el equivalente exacto de este YAML:

        apiVersion: batch/v1
        kind: Job
        metadata:
          name: <nombre>
          namespace: estudiantes-202630
        spec:
          backoffLimit: 0
          template:
            spec:
              restartPolicy: Never
              containers:
                - name: tarea
                  image: <imagen>
                  imagePullPolicy: Never
                  args: [<argumentos>]
                  resources:
                    requests: { cpu: <cpu_request>, memory: <mem_request> }
                    limits:   { cpu: <cpu_limit>,   memory: <mem_limit> }

    Completa los `...` comparando cada linea con ese YAML. Ojo: en el cliente
    de Python los campos van en snake_case (`image_pull_policy`,
    `restart_policy`, `backoff_limit`) y en el YAML en camelCase.
    """
    # `requests` es lo que Kubernetes reserva para programar el Pod; `limits`
    # es el tope. Si el contenedor supera el limite de memoria, lo mata con
    # OOMKilled; si supera el de CPU, lo frena.
    limites = client.V1ResourceRequirements(
        requests={"cpu": recursos["cpu_request"], "memory": recursos["mem_request"]},
        limits={"cpu": recursos["cpu_limit"], "memory": recursos["mem_limit"]},
    )

    # Never: las imagenes son locales (estan dentro de Minikube y no en un
    # registro), asi que Kubernetes no debe intentar descargarlas.
    contenedor = client.V1Container(
        name="tarea",
        image=imagen,
        image_pull_policy="Never",
        args=argumentos,
        resources=limites,
    )

    # Never: si el contenedor falla, el Pod no se reinicia; el fallo queda
    # visible en vez de repetirse dentro del mismo Pod.
    plantilla = client.V1PodTemplateSpec(
        spec=client.V1PodSpec(
            restart_policy="Never",
            containers=[contenedor],
        ),
    )

    # backoff_limit=0: el Job no crea Pods de reemplazo. Con el valor por
    # defecto (6) una tarea que falla por memoria se ejecutaria 7 veces.
    especificacion = client.V1JobSpec(
        backoff_limit=0,
        active_deadline_seconds=PLAZO_SEGUNDOS,
        template=plantilla,
    )

    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=nombre, namespace=NAMESPACE),
        spec=especificacion,
    )

    cliente_batch().create_namespaced_job(namespace=NAMESPACE, body=job)
    return nombre


# ---------------------------------------------------------------------------
# 3. Consulta de estado
# ---------------------------------------------------------------------------

def describir_estado(status):
    """Traduce el `status` de un Job a una frase corta.

    Los contadores valen None mientras Kubernetes no los ha fijado, de ahi el
    `or 0`.
    """
    activos = status.active or 0
    correctos = status.succeeded or 0
    fallidos = status.failed or 0

    # El plazo se revisa primero: cuando se vence, el Job queda como fallido
    # y la causa solo aparece en sus condiciones (tipo Failed, motivo
    # DeadlineExceeded).
    for condicion in status.conditions or []:
        if (
            condicion.type == "Failed"
            and condicion.status == "True"
            and condicion.reason == "DeadlineExceeded"
        ):
            return "fallo: tiempo agotado (DeadlineExceeded)"

    if activos > 0:
        return "en ejecucion"
    if correctos > 0:
        return "termino correctamente"
    if fallidos > 0:
        return "fallo"
    return "pendiente (el Pod todavia no ha arrancado)"


def causa_en_pod(nombre):
    """Devuelve la causa del problema leida en el Pod del Job, o "".

    El Job solo sabe que fallo o que sigue activo. Por que murio el contenedor
    (sin memoria) o por que no arranca (no hay imagen) lo sabe el Pod.
    """
    config.load_kube_config()
    core = client.CoreV1Api()

    pods = core.list_namespaced_pod(
        namespace=NAMESPACE,
        label_selector=f"job-name={nombre}",
    )
    for pod in pods.items:
        for contenedor in pod.status.container_statuses or []:
            terminado = contenedor.state.terminated
            if terminado and terminado.reason == "OOMKilled":
                return "fallo: sin memoria (OOMKilled)"

            esperando = contenedor.state.waiting
            if esperando and esperando.reason == "ErrImageNeverPull":
                return "atascado: imagen no encontrada"

    return ""


def listar_jobs():
    """Devuelve [(nombre, estado)] de todos los Jobs del namespace.

    Esta es la lista que muestra la opcion 2 del menu.
    """
    jobs = cliente_batch().list_namespaced_job(namespace=NAMESPACE)

    resultado = []
    for job in jobs.items:
        nombre = job.metadata.name
        estado = describir_estado(job.status)

        # El Job solo sabe que fallo o que sigue activo; la causa esta en el
        # Pod. Un Pod sin imagen cuenta como activo, por eso se revisa tambien
        # cuando el Job esta en ejecucion.
        if estado == "fallo":
            causa = causa_en_pod(nombre)
            if causa == "fallo: sin memoria (OOMKilled)":
                estado = causa
        elif estado == "en ejecucion":
            causa = causa_en_pod(nombre)
            if causa == "atascado: imagen no encontrada":
                estado = causa

        resultado.append((nombre, estado))

    return resultado


def consultar_estado(nombre):
    """Devuelve una descripcion legible del estado de un Job concreto."""
    job = cliente_batch().read_namespaced_job_status(name=nombre, namespace=NAMESPACE)
    return f"{nombre}: {describir_estado(job.status)}"


# ---------------------------------------------------------------------------
# 4. Consulta de logs
# ---------------------------------------------------------------------------

def consultar_logs(nombre):
    """Devuelve la salida del contenedor ejecutado por el Job.

    Los logs pertenecen al Pod, no al Job. Kubernetes etiqueta cada Pod que
    crea un Job con `job-name=<nombre del Job>`, y por ahi se le encuentra.
    """
    config.load_kube_config()
    core = client.CoreV1Api()

    pods = core.list_namespaced_pod(
        namespace=NAMESPACE,
        label_selector=f"job-name={nombre}",
    )
    if not pods.items:
        return f"El Job {nombre} todavia no tiene Pods."

    pod = pods.items[0].metadata.name

    # Los logs se piden al Pod. Sin _preload_content=False el cliente devuelve
    # el repr de los bytes y todo sale como b'...' en una sola linea.
    respuesta = core.read_namespaced_pod_log(
        name=pod, namespace=NAMESPACE, _preload_content=False
    )
    return respuesta.data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 5. Limpieza de tareas terminadas
# ---------------------------------------------------------------------------

def jobs_terminados():
    # 1. Creamos el cliente de la API de Kubernetes para acceder a los Jobs (BatchV1)
    batch_v1 = client.BatchV1Api()
    
    # 2. Pedimos la lista completa de Jobs que existen en nuestro namespace
    lista_jobs = batch_v1.list_namespaced_job(namespace="estudiantes-202630")
    
    # 3. Creamos una lista vacía donde guardaremos los nombres de los que ya acabaron
    terminados = []
    
    # 4. Recorremos cada job que nos devolvió Kubernetes
    for job in lista_jobs.items:
        estado = job.status
        
        # Kubernetes a veces devuelve 'None' si el contador está vacío.
        # Usamos "or 0" para convertir esos 'None' en un número 0 y evitar errores matemáticos.
        activos = estado.active or 0
        exitosos = estado.succeeded or 0
        fallidos = estado.failed or 0
        
        # 5. Aplicamos la regla estricta del PDF: 
        # Cero activos Y (al menos uno exitoso O al menos uno fallido)
        if activos == 0 and (exitosos > 0 or fallidos > 0):
            # Si cumple, sacamos el nombre del job y lo metemos a nuestra lista
            terminados.append(job.metadata.name)
            
    # 6. Devolvemos la lista final con los nombres
    return terminados


def eliminar_job(nombre):
    # 1. Volvemos a instanciar el cliente de la API
    batch_v1 = client.BatchV1Api()
    
    # 2. Preparamos las opciones de borrado. 
    # ¡ESTA ES LA CLAVE DEL PDF! La política "Background" le dice a Kubernetes 
    # que cuando borre el Job, también persiga y borre el Pod asociado (no dejar huérfanos).
    opciones = client.V1DeleteOptions(propagation_policy="Background")
    
    # 3. Le damos la orden a Kubernetes de borrar el Job con ese nombre
    batch_v1.delete_namespaced_job(
        name=nombre,                      # El nombre que nos llega como parámetro
        namespace="estudiantes-202630",   # Nuestro espacio de trabajo
        body=opciones                     # Le pasamos la regla de borrado en cascada
    )


# ---------------------------------------------------------------------------
# Acciones del menu
# ---------------------------------------------------------------------------

def accion_ejecutar(catalogo):
    eleccion = seleccionar(catalogo)
    if eleccion is None:
        return

    lenguaje, tarea, complejidad, imagen, argumentos, recursos = eleccion
    nombre = nombre_job(lenguaje, tarea, complejidad)
    crear_job(nombre, imagen, argumentos, recursos)

    print(f"\nJob creado: {nombre}")
    print(f"  Imagen: {imagen}")
    print(f"  Argumentos del contenedor: {argumentos}")
    print(f"  CPU: {recursos['cpu_request']} - {recursos['cpu_limit']}")
    print(f"  Memoria: {recursos['mem_request']} - {recursos['mem_limit']}")
    print("  Revisa su estado con la opcion 2 del menu.")


def accion_estado():
    jobs = listar_jobs()
    if not jobs:
        print(f"\nNo hay Jobs en el namespace {NAMESPACE}.")
        return

    print(f"\nTareas en {NAMESPACE}:")
    for nombre, estado in jobs:
        print(f"  - {nombre}: {estado}")


def accion_logs():
    jobs = listar_jobs()
    if not jobs:
        print(f"\nNo hay Jobs en el namespace {NAMESPACE}.")
        return

    nombres = [nombre for nombre, _ in jobs]
    nombre = elegir_opcion("De que tarea quieres ver los logs?", nombres)
    if nombre is None:
        return

    print(f"\nSalida de {nombre}:")
    print(consultar_logs(nombre))


def accion_limpiar():
    terminados = jobs_terminados()
    if not terminados:
        print("\nNo hay tareas terminadas que limpiar.")
        return

    print(f"\nSe eliminaran {len(terminados)} tarea(s) terminada(s):")
    for nombre in terminados:
        print(f"  - {nombre}")

    if input("Confirmas? [s/N]: ").strip().lower() not in ("s", "si"):
        print("Cancelado, no se elimino nada.")
        return

    for nombre in terminados:
        eliminar_job(nombre)
    print(f"{len(terminados)} tarea(s) eliminada(s).")


# ---------------------------------------------------------------------------
# Menu principal
# ---------------------------------------------------------------------------

def menu():
    catalogo = cargar_catalogo()

    acciones = {
        "1": ("Ejecutar una tarea nueva", lambda: accion_ejecutar(catalogo)),
        "2": ("Revisar el estado de las tareas", accion_estado),
        "3": ("Ver los logs de una tarea", accion_logs),
        "4": ("Limpiar las tareas terminadas", accion_limpiar),
    }

    while True:
        print(f"\n=== Gestor de Jobs - namespace {NAMESPACE} ===")
        for clave, (titulo, _) in acciones.items():
            print(f"  {clave}. {titulo}")
        print("  5. Salir")

        opcion = input("Opcion: ").strip()
        if opcion == "5":
            print("Hasta luego.")
            return 0
        if opcion not in acciones:
            print("Opcion no valida.")
            continue

        try:
            acciones[opcion][1]()
        except ApiException as error:
            # Errores que devuelve el API server: nombre repetido, namespace
            # inexistente, permisos insuficientes...
            print(f"\nError de Kubernetes ({error.status}): {error.reason}")
        except Exception as error:  # noqa: BLE001 - el menu no debe caerse
            print(f"\nError: {error}")


if __name__ == "__main__":
    try:
        raise SystemExit(menu())
    except KeyboardInterrupt:
        print("\nInterrumpido.")
