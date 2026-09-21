# -*- coding: utf-8 -*-
"""Clasificadores de letra, todos en numpy pelado.

No se usa scikit-learn ni torch a proposito: el equipo de la prueba no tiene
internet, y numpy y opencv ya son lo unico que el lector necesita. Un modelo
que obligue a instalar media biblioteca no se podria usar aunque ganara.

Todos exponen lo mismo:  m.predecir(V) -> (indices, confianza)

La CONFIANZA de todos es "lo que le saca el ganador al segundo", que es la
misma idea que usa el lector con las plantillas. Asi se pueden comparar por
cuantos errores dejan pasar al marcar la misma cantidad de celdas.
"""
import numpy as np


def _margen(puntos):
    """Del mejor al segundo. puntos: (n, clases)."""
    orden = np.argsort(puntos, axis=1)
    mejor = orden[:, -1]
    p1 = puntos[np.arange(len(puntos)), mejor]
    p2 = puntos[np.arange(len(puntos)), orden[:, -2]]
    return mejor, p1 - p2


class VecinoMasCercano(object):
    """1-NN por coseno. Es EXACTAMENTE lo que ya hace el lector con las
    plantillas: lo unico que cambia entre uno y otro es con que se entrena."""

    nombre = "1-vecino"

    def __init__(self, V, y, k=1):
        self.V, self.y, self.k = V, y, int(k)
        self.clases = int(y.max()) + 1
        self.nombre = "%d-vecino" % self.k

    def predecir(self, X, trozo=256):
        salida_i, salida_m = [], []
        for a in range(0, len(X), trozo):
            s = X[a:a + trozo] @ self.V.T          # coseno: todos unitarios
            if self.k == 1:
                # por clase, el mejor parecido: asi el margen es "mejor clase
                # contra la siguiente CLASE", no contra otra copia de si misma
                puntos = np.full((len(s), self.clases), -1.0, np.float32)
                for c in range(self.clases):
                    m = (self.y == c)
                    if m.any():
                        puntos[:, c] = s[:, m].max(axis=1)
            else:
                idx = np.argpartition(-s, self.k, axis=1)[:, :self.k]
                puntos = np.zeros((len(s), self.clases), np.float32)
                for f in range(len(s)):
                    for j in idx[f]:
                        puntos[f, self.y[j]] += s[f, j]
            i, m = _margen(puntos)
            salida_i.append(i); salida_m.append(m)
        return np.concatenate(salida_i), np.concatenate(salida_m)


class Centroide(object):
    """El promedio de cada letra. Mas bruto imposible, pero es el suelo."""

    nombre = "centroide"

    def __init__(self, V, y):
        clases = int(y.max()) + 1
        C = np.zeros((clases, V.shape[1]), np.float32)
        for c in range(clases):
            m = (y == c)
            if m.any():
                C[c] = V[m].mean(axis=0)
        n = np.linalg.norm(C, axis=1, keepdims=True)
        self.C = C / np.maximum(n, 1e-9)

    def predecir(self, X):
        return _margen(X @ self.C.T)


class Softmax(object):
    """Regresion logistica multiclase, a pelo con descenso de gradiente.

    Es un modelo LINEAL sobre los mismos 1024 numeros. Si esto ya gana a las
    plantillas, no hace falta nada mas complicado; y si no gana, sabemos que el
    problema no es el clasificador sino lo que entra en el.
    """

    nombre = "softmax lineal"

    def __init__(self, V, y, pasos=400, lr=0.5, l2=1e-4, semilla=0):
        rng = np.random.default_rng(semilla)
        clases = int(y.max()) + 1
        n, d = V.shape
        W = rng.normal(0, 0.01, (d, clases)).astype(np.float32)
        b = np.zeros(clases, np.float32)
        Y = np.zeros((n, clases), np.float32)
        Y[np.arange(n), y] = 1.0
        for _ in range(pasos):
            z = V @ W + b
            z -= z.max(axis=1, keepdims=True)
            e = np.exp(z)
            p = e / e.sum(axis=1, keepdims=True)
            g = (p - Y) / n
            W -= lr * (V.T @ g + l2 * W)
            b -= lr * g.sum(axis=0)
        self.W, self.b = W, b

    def predecir(self, X):
        z = X @ self.W + self.b
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return _margen(e / e.sum(axis=1, keepdims=True))


class RedChica(object):
    """Una capa escondida. Sigue siendo pequeña y sigue siendo numpy.

    Es el paso intermedio antes de pensar en una CNN: si una capa escondida no
    aporta nada sobre el modelo lineal, una CNN tampoco va a arreglar lo que
    falla, porque el problema estaria en la entrada y no en el modelo.
    """

    nombre = "red 1 capa"

    def __init__(self, V, y, escondidas=128, pasos=600, lr=0.5, l2=1e-4,
                 semilla=0, lote=512):
        rng = np.random.default_rng(semilla)
        clases = int(y.max()) + 1
        n, d = V.shape
        W1 = rng.normal(0, np.sqrt(2.0 / d), (d, escondidas)).astype(np.float32)
        b1 = np.zeros(escondidas, np.float32)
        W2 = rng.normal(0, np.sqrt(2.0 / escondidas),
                        (escondidas, clases)).astype(np.float32)
        b2 = np.zeros(clases, np.float32)
        for paso in range(pasos):
            s = rng.integers(0, n, min(lote, n))
            x, yy = V[s], y[s]
            h = np.maximum(0.0, x @ W1 + b1)
            z = h @ W2 + b2
            z -= z.max(axis=1, keepdims=True)
            e = np.exp(z); p = e / e.sum(axis=1, keepdims=True)
            g = p.copy(); g[np.arange(len(s)), yy] -= 1.0; g /= len(s)
            gW2 = h.T @ g + l2 * W2
            gb2 = g.sum(axis=0)
            gh = (g @ W2.T) * (h > 0)
            gW1 = x.T @ gh + l2 * W1
            gb1 = gh.sum(axis=0)
            W2 -= lr * gW2; b2 -= lr * gb2
            W1 -= lr * gW1; b1 -= lr * gb1
        self.W1, self.b1, self.W2, self.b2 = W1, b1, W2, b2

    def predecir(self, X):
        h = np.maximum(0.0, X @ self.W1 + self.b1)
        z = h @ self.W2 + self.b2
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return _margen(e / e.sum(axis=1, keepdims=True))
