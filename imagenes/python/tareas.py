#!/usr/bin/env python3
"""Ejecutor de tareas en Python.

Contrato, identico en las tres imagenes:
  entrada  : argumentos del contenedor -> <tarea> <N>
  salida   : logs libres en stdout; la ULTIMA linea es un JSON de una linea
  exit code: 0 = exito, != 0 = fallo (deja el Job en Failed)
"""
from kubernetes.client.models import v1_azure_file_persistent_volume_source
import json
import os
import platform
import random
import sys
import time


def hola(_n):
    print(f"Hola desde Python {sys.version.split()[0]}")
    print(f"Hostname   : {platform.node()}")
    print(f"CPUs vistas: {os.cpu_count()}")
    return {"mensaje": "hola mundo", "runtime": f"python {sys.version.split()[0]}"}


def ordenar(n):
    print(f"Generando {n} enteros aleatorios...")
    datos = [random.randint(0, 2**31) for _ in range(n)]
    print("Ordenando...")
    datos.sort()
    # Verificacion: nunca reportar exito sin comprobar el resultado.
    assert all(datos[i] <= datos[i + 1] for i in range(0, len(datos) - 1, 997))
    return {"n": n, "primero": datos[0], "ultimo": datos[-1]}


def fib(n):
    # Recursivo a proposito: sin memoizacion satura una CPU.
    def f(k):
        return k if k < 2 else f(k - 1) + f(k - 2)

    sys.setrecursionlimit(10000)
    print(f"Calculando fib({n}) de forma recursiva, sin memoizacion...")
    return {"n": n, "fib": f(n)}


def matriz(n):
    print(f"Multiplicando dos matrices de {n}x{n} con triple bucle...")
    a = [[random.random() for _ in range(n)] for _ in range(n)]
    b = [[random.random() for _ in range(n)] for _ in range(n)]
    c = [[0.0] * n for _ in range(n)]
    for i in range(n):
        fila_a, fila_c = a[i], c[i]
        for k in range(n):
            aik, fila_b = fila_a[k], b[k]
            for j in range(n):
                fila_c[j] += aik * fila_b[j]
        if n >= 100 and i % max(1, n // 10) == 0:
            print(f"  fila {i}/{n}")
    return {"n": n, "traza": round(sum(c[i][i] for i in range(n)), 6)}

def primos(n):
    # Regla del PDF: Para n < 2, la cantidad es 0
    if n < 2:
        return {"n": n, "cantidad": 0}
    
    # Creamos una lista para nuestra criba
    es_primo = [True] * (n + 1)
    es_primo[0] = False
    es_primo[1] = False
    
    # Calculamos algunos hitos para imprimir el progreso (25%, 50%, 75%, 100%)
    hitos = {n // 4: "25%", n // 2: "50%", (3 * n) // 4: "75%", n: "100%"}
    
    # Criba con bucles simples para cargar la CPU como pide el enunciado
    for p in range(2, int(n**0.5) + 1):
        if es_primo[p]:
            for i in range(p * p, n + 1, p):
                es_primo[i] = False
                
    # Contamos la cantidad total y mostramos progreso por stdout (logs)
    cantidad = 0
    for i in range(2, n + 1):
        if es_primo[i]:
            cantidad += 1
            
        # Imprimir progreso si llegamos a un hito
        if i in hitos:
            # flush=True es importante para que el log salga en tiempo real en Kubernetes
            print(f"Progreso: calculados hasta {i} ({hitos[i]})", flush=True)
            
    # El main del archivo se encargará de convertir esto a JSON y agregar lo que falte
    return {"n": n, "cantidad": cantidad}    


TAREAS = {
    "hola": hola,
    "ordenar": ordenar,
    "fib": fib,
    "matriz": matriz,
    "primos" : primos
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TAREAS:
        print(f"Uso: <{'|'.join(TAREAS)}> <N>", file=sys.stderr)
        return 2

    tarea = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    random.seed(42)

    print(f"--- tarea={tarea} n={n} ---")
    inicio = time.time()
    resultado = TAREAS[tarea](n)
    ms = int((time.time() - inicio) * 1000)

    # La ultima linea DEBE ser el JSON de una sola linea.
    print(json.dumps({"tarea": tarea, "lenguaje": "python", "ms": ms, **resultado}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
