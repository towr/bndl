"""
From https://github.com/douban/dpark/blob/master/dpark/portable_hash.pyx
"""

cdef long tuple_hash(tuple obj):
    cdef long mul = 1000003, l = len(obj), value = 0x345678, v
    for i in obj:
        l -= 1
        v = portable_hash(i)
        if v == -1:
            return -1
        value = (value ^ v) * mul
        mul += <long> (82520 + l * 2)
    value += 97531
    if value == -1:
        value = -2
    return value


cdef long string_hash(bytes obj):
    cdef long l = len(obj), value, i = 0, v
    if l == 0:
        return 0
    v = obj[0]
    value = v << 7
    while i < l:
        v = obj[i]
        value = (1000003 * value) ^ v
        i += 1

    value ^= l
    if value == -1:
        value = -2
    return value


cdef long unicode_hash(obj):
    cdef unicode s = obj
    cdef long l = len(obj), value, v
    if l == 0:
        return 0
    v = ord(s[0])
    value = v << 7
    for c in s:
        v = ord(c)
        value = (1000003 * value) ^ v

    value ^= l
    if value == -1:
        value = -2
    return value


cpdef long portable_hash(obj) except -1:
    if obj is None:
        return 1315925605
    t = type(obj)
    if t is bytes:
        return string_hash(obj)
    elif t is unicode:
        return unicode_hash(obj)
    elif t is tuple:
        return tuple_hash(obj)
    else:
        return hash(obj)
