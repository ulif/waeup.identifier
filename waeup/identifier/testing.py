#
#    waeup.identifier - identifiy WAeUP Kofa students biometrically
#    Copyright (C) 2014  Uli Fouquet, WAeUP Germany
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
import os
import shutil
import stat
import sys
import tempfile
import unittest
import xmlrpc.client
from base64 import b64decode
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler


def create_executable(path, content):
    """Create an executable in `path` with `content` as content.
    """
    open(path, 'w').write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return


def create_python_script(path, commands, ret_code=0):
    """Create a python script that executes `commands` and returns
    `ret_code`.
    """
    content = (
        '#!%s\n'
        'import sys\n'
        'import time\n'
        '%s\n'
        'sys.exit(%s)\n' % (
            sys.executable, commands, ret_code))
    create_executable(path, content)


def create_fpscan(path_dir, output, ret_code=0):
    """Helper to create a fake 'fpscan' binary.

    `path_dir` must be a directory in current $PATH.
    `output` gives the desired output produced by the script.
    `ret_code` is the return code (status) generated by the script.

    `create_fpscan` writes a fake script that only outputs the
    requested string(s) and then exits with `ret_code`.

    It can be used to fake real `fpscan` calls.
    """
    path = os.path.join(path_dir, 'fpscan')
    commands = 'print("%s")' % output
    create_python_script(path, commands, ret_code)
    return path


class VirtualHomeProvider(object):
    """A unittest mixin for tests where a virtual home is needed.
    """
    _orig_vars = {}

    def setup_virtual_home(self):
        """Setup virtual $HOME, $PATH and tempdirs.
        """
        self.path_dir = tempfile.mkdtemp()
        self.home_dir = tempfile.mkdtemp()
        for var_name in ['PATH', 'HOME']:
            self._orig_vars[var_name] = os.environ.get(var_name)
        os.environ['PATH'] = self.path_dir
        os.environ['HOME'] = self.home_dir

    def teardown_virtual_home(self):
        """Restore $HOME, $PATH and remove tempdirs.
        """
        for var_name in ['PATH', 'HOME']:
            if self._orig_vars[var_name] is None:
                del os.environ[var_name]
            else:
                os.environ[var_name] = self._orig_vars[var_name]
        if os.path.exists(self.path_dir):
            shutil.rmtree(self.path_dir)
        if os.path.exists(self.home_dir):
            shutil.rmtree(self.home_dir)


class VirtualHomingTestCase(unittest.TestCase, VirtualHomeProvider):
    """A unittest test case that sets up virtual homes.

    Provides `self.path_dir` and `self.home_dir` pointing to temporary
    directories set in ``$PATH`` and ``$HOME`` respectively.
    """
    def setUp(self):
        self.setup_virtual_home()

    def tearDown(self):
        self.teardown_virtual_home()


class AuthenticatingXMLRPCRequestHandler(SimpleXMLRPCRequestHandler):
    """XMLRPC handler providing basic auth.

    We only accept one single credentials pair: ``mgr``, ``mgrpw``.
    """
    rpc_paths = ('/RPC2',)

    def authenticate(self, headers):
        auth_header_line = headers.get('Authorization', None)
        if auth_header_line is None:
            return False
        (auth_type, trash, encoded_creds) = auth_header_line.partition(' ')
        if auth_type != 'Basic':
            return False
        decoded_creds = b64decode(encoded_creds.encode())
        (user_name, trash, password) = decoded_creds.decode().partition(':')
        if user_name == 'mgr' and password == 'mgrpw':
            return True
        return False

    def parse_request(self):
        if super(AuthenticatingXMLRPCRequestHandler, self).parse_request():
            if self.authenticate(self.headers):
                return True
            else:
                self.send_error(401, 'Unauthorized')
        return False


fake_student_db = dict()


def xmlrpc_ping(x):
    return ('pong', x)


def xmlrpc_reset_student_db():
    global fake_student_db
    fake_student_db = dict()
    return True


def xmlrpc_create_student(student_id):
    global fake_student_db
    if student_id not in fake_student_db.keys():
        fake_student_db[student_id] = dict()
    return True


def xmlrpc_put_student_fingerprints(identifier=None, fingerprints={}):
    global fake_student_db
    result = False
    if not identifier in fake_student_db.keys():
        raise xmlrpc.client.Fault(
            xmlrpc.client.INVALID_METHOD_PARAMS,
            "No such student: '%s'" % identifier)
    if not isinstance(fingerprints, dict):
        raise xmlrpc.client.Fault(
            xmlrpc.client.INVALID_METHOD_PARAMS,
            "Invalid fingerprint data: must be dict'")
    for str_key, val in fingerprints.items():
        num = 0
        try:
            num = int(str_key)
        except ValueError:
            pass
        if num < 1 or num > 10:
            continue
        if not isinstance(val, xmlrpc.client.Binary):
            raise xmlrpc.client.Fault(
                xmlrpc.client.INVALID_METHOD_PARAMS,
                "Invalid fingerprint data for finger %s" % num)
        if not val.data.startswith(b'FP1'):
            raise xmlrpc.client.Fault(
                xmlrpc.client.INVALID_METHOD_PARAMS,
                "Invalid file format for finger %s" % num)
        result = True
    return result


class AuthenticatingXMLRPCServer(SimpleXMLRPCServer):
    """An XMLRPC server that fakes WAeUP kofa XMLRPC services.
    """
    def __init__(self, host="127.0.0.1", port=14096):
        super(AuthenticatingXMLRPCServer, self).__init__(
            (host, port), requestHandler=AuthenticatingXMLRPCRequestHandler
            )
        self.register_introspection_functions()
        self.register_function(xmlrpc_ping, 'ping')  # not part of kofa
        self.register_function(xmlrpc_create_student,
                               'create_student')     # not part of kofa
        self.register_function(xmlrpc_reset_student_db,
                               'reset_student_db')   # not part of kofa
        self.register_function(xmlrpc_put_student_fingerprints,
                               'put_student_fingerprints')
        return


def start_fake_kofa():
    """Entry point to start a fake kofa server on commandline.

    The fake server provides only a copy of the XMLRPC API of WAeUP
    Kofa. Useful for testing.
    """
    server = AuthenticatingXMLRPCServer('127.0.0.1', 61616)
    print("Starting server at 127.0.0.1:61616")
    print("Press ^C (Ctrl-c) to abort.")
    server.serve_forever()
