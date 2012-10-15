#!/usr/bin/python
# -*- coding: utf-8 -*-
'''
@date: 2012-04-27
@author: shell.xu
'''
import os, copy, time, logging
from gevent import select
from http import *

logger = logging.getLogger('proxy')
VERBOSE = False

def get_proxy_auth(users):
    def all_pass(req): return None
    def proxy_auth(req):
        auth = req.get_header('Proxy-Authorization')
        if auth:
            req.headers = [(k, v) for k, v in req.headers if k != 'Proxy-Authorization']
            username, password = base64.b64decode(auth[6:]).split(':')
            if users.get(username, None) == password: return None
        logging.info('proxy authenticate failed')
        return response_http(407, headers=[('Proxy-Authenticate', 'Basic realm="users"')])
    return proxy_auth if users else all_pass

def parse_target(url):
    r = (url.netloc or url.path).split(':', 1)
    if len(r) > 1: port = int(r[1])
    else: port = 443 if u.scheme.lower() == 'https' else 80
    return r[0], port, '%s?%s' % (u.path, u.query) if u.query else u.path

def connect(req, sock_factory):
    hostname, port, uri = parse_target(req.url)
    try:
        with sock_factory.socket() as sock:
            sock.connect((hostname, port))
            res = HttpResponse(req.version, 200, 'OK')
            res.send_header(req.stream)
            req.stream.flush()

            # WARN: maybe dangerous to ssl
            fd1, fd2 = req.stream.fileno(), sock.fileno()
            fdlist = [fd1, fd2]
            while True:
                for rfd in select.select(fdlist, [], [])[0]:
                    try: d = os.read(rfd, BUFSIZE)
                    except OSError: d = ''
                    if not d: raise EOFError()
                    try: os.write(fd2 if rfd == fd1 else fd1, d)
                    except OSError: raise EOFError()
    finally: logger.info('%s closed' % req.uri)

def http(req, sock_factory):
    t = time.time()
    hostname, port, uri = parse_target(req.url)
    reqx = copy.copy(req)
    reqx.uri = uri
    reqx.headers = [(h, v) for h, v in req.headers if not h.startswith('Proxy')]
    with sock_factory.socket() as sock:
        sock.connect((hostname, port))
        stream1 = sock.makefile()

        if VERBOSE: req.dbg_print()
        reqx.send_header(stream1)
        for d in reqx.read_chunk(req.stream, raw=True): stream1.write(d)
        stream1.flush()

        res = recv_msg(stream1, HttpResponse)
        if VERBOSE: res.dbg_print()
        res.send_header(req.stream)
        hasbody = req.method.upper() != 'HEAD' and res.code not in CODE_NOBODY
        for d in res.read_chunk(stream1, hasbody, True): req.stream.write(d)
        req.stream.flush()
    res.connection = req.get_header('Proxy-Connection', '').lower() == 'keep-alive'
    logger.debug('%s with %d in %0.2f, %s' % (
            req.uri.split('?', 1)[0], res.code, time.time() - t,
            req.get_header('Proxy-Connection', 'closed').lower()))
    return res
