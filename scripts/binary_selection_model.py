"""Experimental heuristic copied unchanged from xprobe 830568a1, not a public API."""
import math
import random

def approximate(candidates, matrix, rank, seed, scale):
    """Fit signed binary outer products to weighted case x target-pair incidence.

    Alternating sign updates (16 fixed sweeps) followed by least-squares scalar
    calibration and residual deflation. This is a heuristic, not SVD/LittleBit.
    Zero residual components are harmless; fitted rank can be lower than rank.
    """
    pairs = matrix['uncovered_pairs']
    exact = [[float(c['factor_bits'] & p['bits'] == p['bits']) for p in pairs]
             for c in candidates]
    if not candidates or not pairs:
        return exact, [], 0.0
    weights = [1 / math.sqrt(max(1, sum(row[j] for row in exact)))
               if scale == 'frequency' else 1.0 for j in range(len(pairs))]
    residual = [[v * weights[j] for j, v in enumerate(row)] for row in exact]
    fitted = [[0.0] * len(pairs) for _ in candidates]
    rng = random.Random(seed)
    coefficients = []
    for _ in range(rank):
        right = [rng.choice((-1, 1)) for _ in pairs]
        for _ in range(16):
            left = [1 if sum(a*b for a, b in zip(row, right)) >= 0 else -1
                    for row in residual]
            right = [1 if sum(residual[i][j] * left[i] for i in range(len(left))) >= 0
                     else -1 for j in range(len(pairs))]
        alpha = sum(residual[i][j] * left[i] * right[j]
                    for i in range(len(left)) for j in range(len(right))) / (len(left)*len(right))
        coefficients.append(alpha)
        for i in range(len(left)):
            for j in range(len(right)):
                value = alpha * left[i] * right[j]
                residual[i][j] -= value
                fitted[i][j] += value
    error = sum(v*v for row in residual for v in row)
    # Undo column scaling; clip only ranking weights, never oracle values.
    scores = [[max(0.0, min(1.0, v / weights[j])) for j, v in enumerate(row)]
              for row in fitted]
    return scores, coefficients, error

