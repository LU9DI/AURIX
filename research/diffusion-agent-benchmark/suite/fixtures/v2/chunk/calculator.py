def chunk(xs, n):
    return [xs[i:i+n] for i in range(0, len(xs) - len(xs) % n, n)]
