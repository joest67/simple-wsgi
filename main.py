# -*- coding: utf-8 -*-
import argparse
import json
import sys
import urlparse
import httplib

from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler

request = None


class Request(object):

    chunk_size = 1024 * 10

    def __init__(self, environ):
        self.environ = environ
        self.method = environ['method']
        self._data = {}
        self._args = {}
        self._json = {}

        self.parse_request_info()

    def parse_body(self):
        content_type = self.environ['content_type']
        parser = self.content_type_parser_map.get(content_type)
        if parser:
            parser(self)

    def parse_args(self):
        if self.urlencode_string:
            self._args = dict(urlparse.parse_qsl(self.urlencode_string))

    def parse_request_info(self):
        parsed = urlparse.urlparse(self.environ['path'])
        self.path = parsed.path
        self.urlencode_string = parsed.query

        self.parse_args()
        self.parse_body()

    def _read_data(self):
        rfile = self.environ['wsgi.input']
        content_length = self.environ['content_length']

        if content_length < self.chunk_size:
            stream = rfile.read(content_length)
        else:
            length = 0
            stream = ''
            while length < content_length:
                chunk = rfile.read(self.chunk_size)
                length += self.chunk_size
                stream += chunk

        print 'read from rfile', stream
        return stream

    def _parse_form_urlencoded(self):
        stream = self._read_data()
        if not stream:
            return

        pairs = urlparse.parse_qsl(stream)
        if not pairs:
            self._data = {stream: ''}
        else:
            self._data = dict(pairs)

    def _parse_json(self):
        stream = self._read_data()
        if not stream:
            return

        try:
            json_data = json.loads(stream)
        except:
            pass
        else:
            if json_data:
                self._json = json_data

    @property
    def data(self):
        return self._data

    @property
    def args(self):
        return self._args

    @property
    def json(self):
        return self._json

    content_type_parser_map = {
        'application/x-www-form-urlencoded': _parse_form_urlencoded,
        'application/json': _parse_json,
    }


class Response(object):

    charset = 'utf-8'

    def __init__(self, status_code=httplib.OK, headers=None, data=None):
        self.status_code = status_code
        self._headers = headers
        self._data = data

    @property
    def headers(self):
        default_headers = {
            'Content-Type': 'text/html',
            'Content-Length': str(len(self.data)),
        }

        if self._headers:
            default_headers.update(self._headers)
        return default_headers

    @property
    def data(self):
        if not self._data:
            return ''

        if isinstance(self._data, dict):
            return json.dumps(self._data)

        if isinstance(self._data, unicode):
            return self._data.encode(self.charset)

        return self._data


class SimpleApp(object):

    def return_405(self):
        return None, 405

    def return_404(self):
        return None, 404

    def dispatch_request(self):
        view_func = self.url_rule_map.get(request.path)
        if not view_func:
            return self.return_404()
        else:
            return view_func(self)

    def build_request(self, environ):
        global request
        request = Request(environ)

    def __call__(self, environ, start_response):
        self.environ = environ

        self.build_request(environ)
        rv = self.dispatch_request()

        if not isinstance(rv, Response):
            try:
                data, status_code, headers = rv
            except ValueError:
                try:
                    data, status_code = rv
                    headers = None
                except ValueError:
                    data = rv
                    status_code = httplib.OK
                    headers = None

            rv = Response(status_code, headers, data)

        start_response(rv.status_code, rv.headers)
        return rv.data

    # ======= apis ========

    def ping(self):
        method = request.method.lower()
        if method == 'get':
            return 'pong'
        elif method == 'post':
            return request.json or request.data
        else:
            return self.return_405()

    url_rule_map = {
        '/ping': ping
    }


class WsgiServer(HTTPServer):

    def __init__(self, host, port, app, handler):
        self.app = app
        address_info = (host, int(port))
        HTTPServer.__init__(self, address_info, handler)


class WsgiRequestHandler(BaseHTTPRequestHandler):

    def handle_one_request(self):
        print 'new request %s:%s' % (self.client_address[0],
                                     self.client_address[1])
        self.raw_requestline = self.rfile.readline()
        if not self.raw_requestline:
            self.close_connection = 1
        elif self.parse_request():
            return self.run_wsgi()

    def run_wsgi(self):
        headers_set = []
        headers_sent = []

        def start_response(status_code, headers=None):
            headers_set[:] = status_code, headers

        def write(data):
            assert headers_set, 'need start_response first'
            if not headers_sent:
                status_code, headers = headers_sent[:] = headers_set

                self.send_response(status_code, message='')
                for k, v in headers.iteritems():
                    self.send_header(k, v)
                self.end_headers()

            self.wfile.write(data)
            self.wfile.flush()

        environ = self.build_environ()
        iter_response = self.server.app(environ, start_response)

        for i in iter_response:
            write(i)

        if not headers_sent:  # no data
            write(b'')

    def build_params(self):
        res = {}
        for param in self.headers.getparamnames():
            res[param] = self.headers.getparam(param)
        return res

    def build_environ(self):
        environ = {
            'path': self.path,
            'method': self.command,
            'params': self.build_params(),
            'content_type': self.headers.gettype(),
            'content_length': int(self.headers.get('Content-Length')),
            'wsgi.input': self.rfile,
        }
        return environ


def run_server(host, port, app):
    server = WsgiServer(host, port, app, WsgiRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print 'exit by user'
        sys.exit(0)
    except Exception as e:
        print 'system error, exit.', repr(e)
        sys.exit(0)


def main(host, port):
    print 'server start on %s %s...' % (host, port)
    app = SimpleApp()
    run_server(host, port, app)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', '-H', help='host to serve',
                        default='127.0.0.1')
    parser.add_argument('--port', '-P', help='listen port', default='8000')
    args = parser.parse_args()
    main(args.host, args.port)
