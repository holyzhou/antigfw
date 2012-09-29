#!/usr/bin/python
# -*- coding: utf-8 -*-
'''
@date: 2012-09-27
@author: shell.xu
'''
import struct, random, logging, cStringIO, 
from gevent import socket

logger = logging.getLogger('dns')

class Meta(type):
    def __new__(cls, name, bases, attrs):
        r = dict([(v, n) for n, v in attrs.iteritems() if n.isupper()])
        attrs['__reversed__'] = r
        return type.__new__(cls, name, bases, attrs)

class DEFINE(object):
    __metaclass__ = Meta
    @classmethod
    def lookup(cls, id, default='NOT FOUND'):
        return cls.__reversed__.get(id, default)

class OPCODE(DEFINE):
    QUERY = 0
    IQUERY = 1
    STATUS = 2
    NOTIFY = 4
    UPDATE = 5

class TYPE(DEFINE):
    A = 1           # a host address
    NS = 2          # an authoritative name server
    MD = 3          # a mail destination (Obsolete - use MX)
    MF = 4          # a mail forwarder (Obsolete - use MX)
    CNAME = 5       # the canonical name for an alias
    SOA = 6         # marks the start of a zone of authority
    MB = 7          # a mailbox domain name (EXPERIMENTAL)
    MG = 8          # a mail group member (EXPERIMENTAL)
    MR = 9          # a mail rename domain name (EXPERIMENTAL)
    NULL = 10       # a null RR (EXPERIMENTAL)
    WKS = 11        # a well known service description
    PTR = 12        # a domain name pointer
    HINFO = 13      # host information
    MINFO = 14      # mailbox or mail list information
    MX = 15         # mail exchange
    TXT = 16        # text strings
    AAAA = 28       # IPv6 AAAA records (RFC 1886)
    SRV = 33        # DNS RR for specifying the location of services (RFC 2782)
    SPF = 99        # TXT RR for Sender Policy Framework
    UNAME = 110
    MP = 240

class QTYPE(DEFINE):
    AXFR = 252      # A request for a transfer of an entire zone
    MAILB = 253     # A request for mailbox-related records (MB, MG or MR)
    MAILA = 254     # A request for mail agent RRs (Obsolete - see MX)
    ANY = 255       # A request for all records

class CLASS(DEFINE):
    IN = 1          # the Internet
    CS = 2          # the CSNET class (Obsolete - used only for examples in
                    # some obsolete RFCs)
    CH = 3          # the CHAOS class. When someone shows me python running on
                    # a Symbolics Lisp machine, I'll look at implementing this.
    HS = 4          # Hesiod [Dyer 87]
    ANY = 255       # any class

class Record(object):
    
    def __init__(self, id, qr, opcode, auth, truncated, rd, ra, rcode):
        self.id, self.qr, self.opcode, self.authans = id, qr, opcode, auth
        self.truncated, self.rd, self.ra, self.rcode = truncated, rd, ra, rcode
        self.quiz, self.ans, self.auth, self.ex = [], [], [], []

    def show(self, stream):
        print >>stream, 'quiz'
        for name, qtype, cls in self.quiz:
            print >>stream,  '\t', name, '\t', TYPE.lookup(qtype),\
                '\t', CLASS.lookup(cls)
        print >>stream, 'answer'
        for name, type, cls, ttl, rdata in self.ans:
            print >>stream, '\t', name, '\t', TYPE.lookup(type),\
                '\t', CLASS.lookup(cls), '\t', ttl, '\t', rdata

def packbit(r, bit, dt): return r << bit | (dt & (2**bit - 1))
def unpack(r, bit): return r & (2**bit - 1), r >> bit

def packflag(qr, opcode, auth, truncated, rd, ra, rcode):
    r = packbit(packbit(0, 1, qr), 4, opcode)
    r = packbit(packbit(r, 1, auth), 1, truncated)
    r = packbit(packbit(r, 1, rd), 1, ra)
    r = packbit(packbit(r, 3, 0), 4, rcode)
    return r

def unpackflag(r):
    r, qr = unpack(r, 1)
    r, opcode = unpack(r, 4)
    r, auth = unpack(r, 1)
    r, truncated = unpack(r, 1)
    r, rd = unpack(r, 1)
    r, ra = unpack(r, 1)
    r, rv = unpack(r, 3)
    r, rcode = unpack(r, 4)
    assert rv == 0
    return qr, opcode, auth, truncated, rd, ra, rcode

def packname(name):
    return ''.join([chr(len(i))+i for i in name.split('.')]) + '\x00'

def unpackname(s, o):
    r = []
    c = ord(s.read(1))
    if c & 0xC0 == 0xC0:
        c = (c << 8) + ord(s.read(1)) & 0x3FFF
        return unpackname(cStringIO.StringIO(o[c:]), o)
    while c != 0:
        r.append(s.read(c))
        c = ord(s.read(1))
    return '.'.join(r)

def packquiz(name, qtype, cls):
    return packname(name) + struct.pack('>HH', qtype, cls)

def unpackquiz(s, o):
    name, r = unpackname(s, o), struct.unpack('>HH', s.read(4))
    return name, r[0], r[1]

# def packRR(name, type, cls, ttl, res):
#     return packname(name) + struct.pack('>HHIH', type, cls, ttl, len(res)) + res

def unpackRR(s, o):
    n = unpackname(s, o)
    r = struct.unpack('>HHIH', s.read(10))
    if r[0] == TYPE.A:
        return n, r[0], r[1], r[2], socket.inet_ntoa(s.read(r[3]))
    elif r[0] == TYPE.CNAME:
        return n, r[0], r[1], r[2], unpackname(s, o)
    else: raise Exception("don't know howto handle type")

def pack_record(rec):
    r = struct.pack(
        '>HHHHHH', rec.id, packflag(rec.qr, rec.opcode, rec.authans,
                                    rec.truncated, rec.rd, rec.ra, rec.rcode),
        len(rec.quiz), len(rec.ans), len(rec.auth), len(rec.ex))
    for i in rec.quiz: r += packquiz(*i)
    for i in rec.ans: r += packRR(*i)
    for i in rec.auth: r += packRR(*i)
    for i in rec.ex: r += packRR(*i)
    return ''.join(r)

def unpack_record(dt):
    s = cStringIO.StringIO(dt)
    id, flag, lquiz, lans, lauth, lex = struct.unpack('>HHHHHH', s.read(12))
    rec = Record(id, *unpackflag(flag))
    rec.quiz = [unpackquiz(s, dt) for i in xrange(lquiz)]
    rec.ans = [unpackRR(s, dt) for i in xrange(lans)]
    rec.auth = [unpackRR(s, dt) for i in xrange(lauth)]
    rec.ex = [unpackRR(s, dt) for i in xrange(lex)]
    return rec

def mkquery(*ntlist):
    rec = Record(random.randint(0, 65536), 0, OPCODE.QUERY, 0, 0, 1, 0, 0)
    for name, type in ntlist: rec.quiz.append((name, type, CLASS.IN))
    return pack_record(rec)

def query_by_udp(q, server, sock=None):
    if sock is None: sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(q, (server, 53))
    return sock.recvfrom(1024)[0]

def query_by_tcp(q, server, stream=None):
    sock = None
    if stream is None:
        sock = socket.socket()
        sock.connect((server, 53))
        stream = sock.makefile()
    try:
        stream.write(struct.pack('>H', len(q)) + q)
        stream.flush()
        d = stream.read(2)
        if len(d) == 0: raise EOFError()
        reply = stream.read(struct.unpack('>H', d)[0])
        if len(reply) == 0: raise EOFError()
        return reply
    finally:
        if sock is not None: sock.close()

def query(name, type=TYPE.A, server='127.0.0.1', protocol='udp'):
    q = mkquery((name, type))
    func = globals().get('query_by_%s' % protocol)
    if not func: raise Exception('protocol not found')
    return unpack_record(func(q, server))

def nslookup(name):
    r = query(name)
    return [rdata for name, type, cls, ttl, rdata in r.ans if type == TYPE.A]

def nslookup_s(name, sock, type=TYPE.A):
    q = mkquery((name, type))
    r = unpack_record(query_by_tcp(q, None, sock.makefile()))
    return [rdata for name, type, cls, ttl, rdata in r.ans if type == TYPE.A]
