def max_of(xs):
    best = 0
    for x in xs:
        if x > best:
            best = x
    return best
