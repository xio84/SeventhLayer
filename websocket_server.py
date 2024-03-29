import sys
import struct
from base64 import b64encode
from hashlib import sha1
import logging
from socket import error as SocketError
import errno
from socketserver import ThreadingMixIn, TCPServer, StreamRequestHandler

logger = logging.getLogger(__name__)
logging.basicConfig()

'''
+-+-+-+-+-------+-+-------------+-------------------------------+
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-------+-+-------------+-------------------------------+
|F|R|R|R| opcode|M| Payload len |    Extended payload length    |
|I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
|N|V|V|V|       |S|             |   (if payload len==126/127)   |
| |1|2|3|       |K|             |                               |
+-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
|     Extended payload length continued, if payload len == 127  |
+ - - - - - - - - - - - - - - - +-------------------------------+
|                     Payload Data continued ...                |
+---------------------------------------------------------------+
'''

FIN    = 0x80
OPCODE = 0x0f
MASKED = 0x80
PAYLOAD_LEN = 0x7f
PAYLOAD_LEN_EXT16 = 0x7e
PAYLOAD_LEN_EXT64 = 0x7f

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT         = 0x1
OPCODE_BINARY       = 0x2
OPCODE_CLOSE_CONN   = 0x8
OPCODE_PING         = 0x9
OPCODE_PONG         = 0xA


# ------------------------- Implementation -----------------------------

class WebsocketServer(ThreadingMixIn, TCPServer):
    """
	A websocket server waiting for clients to connect.

    Args:
        port(int): Port to bind to
        host(str): Hostname or IP to listen for connections. By default 127.0.0.1
            is being used. To accept connections from any client, you should use
            0.0.0.0.
        loglevel: Logging level from logging module to use for logging. By default
            warnings and errors are being logged.

    Properties:
        clients(list): A list of connected clients. A client is a dictionary
            like below.
                {
                 'id'      : id,
                 'handler' : handler,
                 'address' : (addr, port)
                }
    """

    allow_reuse_address = True
    daemon_threads = True  # comment to keep threads alive until finished

    clients = []
    id_counter = 0

    def __init__(self, port, host='0.0.0.0', loglevel=logging.WARNING):
        logger.setLevel(loglevel)
        TCPServer.__init__(self, (host, port), WebSocketHandler)
        self.port = self.socket.getsockname()[1]

    def run_forever(self):
        try:
            logger.info("Listening on port %d for clients.." % self.port)
            self.serve_forever()
        except KeyboardInterrupt:
            self.server_close()
            logger.info("Server terminated.")
        except Exception as e:
            logger.error(str(e), exc_info=True)
            exit(1)

    def _message_received_(self, handler, msg, fin):
        self.message_received(self.handler_to_client(handler), self, msg, fin)

    def _binary_received_(self, handler, msg, fin):
        self.binary_received(self.handler_to_client(handler), self, msg, fin)

    def _continuation_received_(self, handler, msg, fin):
        self.continuation_received(self.handler_to_client(handler), self, msg, fin)

    def _ping_received_(self, handler, msg):
        handler.send_pong(msg)

    def _pong_received_(self, handler, msg):
        pass

    def _new_client_(self, handler):
        self.id_counter += 1
        client = {
            'id': self.id_counter,
            'handler': handler,
            'address': handler.client_address
        }
        self.clients.append(client)
        self.new_client(client, self)

    def _client_left_(self, handler):
        client = self.handler_to_client(handler)
        self.client_left(client, self)
        if client in self.clients:
            self.clients.remove(client)        

    def handler_to_client(self, handler):
        for client in self.clients:
            if client['handler'] == handler:
                return client

    def set_new_client_handler(self, fn):
        self.new_client = fn

    def set_client_left_handler(self, fn):
        self.client_left = fn

    def set_message_received_handler(self, fn):
        self.message_received = fn

    def set_binary_received_handler(self, fn):
        self.binary_received = fn

    def set_continuation_received_handler(self, fn):
        self.continuation_received = fn

    def send_message(self, client, msg):
        client['handler'].send_message(msg)

    def send_binary(self, client, msg):
        client['handler'].send_binary(msg)

    def send_continuation(self, client, msg):
        client['handler'].continue_send_binary(msg)

    def send_message_to_all(self, msg):
        for client in self.clients:
            self._unicast_(client, msg)


class WebSocketHandler(StreamRequestHandler):

    message_or_binary = 0 # Message = 0, Binary = 1
    message_buffer = ''
    binary_buffer = bytearray()

    def __init__(self, socket, addr, server):
        self.server = server
        StreamRequestHandler.__init__(self, socket, addr, server)

    def setup(self):
        StreamRequestHandler.setup(self)
        self.keep_alive = True
        self.handshake_done = False
        self.valid_client = False

    def handle(self):
        while self.keep_alive:
            if not self.handshake_done:
                self.handshake()
            elif self.valid_client:
                self.read_next_message()

    def read_bytes(self, num):
        # python3 gives ordinal of byte directly
        bytes = self.rfile.read(num)
        return bytes

    def read_next_message(self):
        try:
            b1, b2 = self.read_bytes(2)
        except SocketError as e:  # to be replaced with ConnectionResetError for py3
            if e.errno == errno.ECONNRESET:
                logger.info("Client closed connection.")
                self.keep_alive = 0
                return
            b1, b2 = 0, 0
        except ValueError as e:
            b1, b2 = 0, 0

        fin    = b1 & FIN
        opcode = b1 & OPCODE
        masked = b2 & MASKED
        payload_length = b2 & PAYLOAD_LEN

        if opcode == OPCODE_CLOSE_CONN:
            logger.info("Client asked to close connection.")
            self.keep_alive = 0
            # self.send_close(1000)
            return
        if not masked:
            logger.warn("Client must always be masked.")
            self.keep_alive = 0
            # self.send_close(1002)
            return
        if opcode == OPCODE_CONTINUATION:
            opcode_handler = self.server._continuation_received_
        elif opcode == OPCODE_BINARY:
            opcode_handler = self.server._binary_received_
        elif opcode == OPCODE_TEXT:
            opcode_handler = self.server._message_received_
        elif opcode == OPCODE_PING:
            opcode_handler = self.server._ping_received_
        elif opcode == OPCODE_PONG:
            opcode_handler = self.server._pong_received_
        else:
            logger.warn("Unknown opcode %#x." % opcode)
            self.keep_alive = 0
            return

        if payload_length == 126:
            payload_length = struct.unpack(">H", self.rfile.read(2))[0]
        elif payload_length == 127:
            payload_length = struct.unpack(">Q", self.rfile.read(8))[0]

        masks = self.read_bytes(4)
        message_bytes = bytearray()
        for message_byte in self.read_bytes(payload_length):
            message_byte ^= masks[len(message_bytes) % 4]
            message_bytes.append(message_byte)
        opcode_handler(self, message_bytes, fin)

    def send_message(self, message):
        self.send_text(message)

    def send_pong(self, message):
        self.send_text(message, OPCODE_PONG)

    def send_text(self, message, opcode=OPCODE_TEXT):
        # Validate message
        if isinstance(message, bytes):
            message = try_decode_UTF8(message)  # this is slower but ensures we have UTF-8
            if not message:
                logger.warning("Can\'t send message, message is not valid UTF-8")
                return False
        elif isinstance(message, str):
            pass
        else:
            logger.warning('Can\'t send message, message has to be a string or bytes. Given type is %s' % type(message))
            return False

        header  = bytearray()
        payload = encode_to_UTF8(message)
        payload_length = len(payload)

        # Normal payload
        if payload_length <= 125:
            header.append(FIN | opcode)
            header.append(payload_length)

        # # Extended payload
        # elif payload_length >= 126 and payload_length <= 65535:
        #     header.append(FIN | opcode)
            # header.append(PAYLOAD_LEN_EXT16)
        #     header.extend(struct.pack(">H", payload_length))

        # # Huge extended payload
        # elif payload_length < 18446744073709551616:
        #     header.append(FIN | opcode)
        #     header.append(PAYLOAD_LEN_EXT64)
        #     header.extend(struct.pack(">Q", payload_length))

        else:
            header.append(0x00 | opcode)
            header.append(125)
            # header.extend(struct.pack(125))
            self.request.send(header + payload[:125])
            # logger.warning("Need to continue.")
            self.continue_send_text(payload[125:])
            return

        self.request.send(header + payload)

    def continue_send_text(self, message, opcode=OPCODE_CONTINUATION):
        # Validate message
        if isinstance(message, bytes):
            message = try_decode_UTF8(message)  # this is slower but ensures we have UTF-8
            if not message:
                logger.warning("Can\'t send message, message is not valid UTF-8")
                return False
        elif isinstance(message, str):
            pass
        else:
            logger.warning('Can\'t send message, message has to be a string or bytes. Given type is %s' % type(message))
            return False

        header  = bytearray()
        payload = encode_to_UTF8(message)
        payload_length = len(payload)

        # Normal payload
        if payload_length <= 125:
            header.append(FIN | opcode)
            header.append(payload_length)

        # # Extended payload
        # elif payload_length >= 126 and payload_length <= 65535:
        #     header.append(FIN | opcode)
        #     header.append(PAYLOAD_LEN_EXT16)
        #     header.extend(struct.pack(">H", payload_length))

        # # Huge extended payload
        # elif payload_length < 18446744073709551616:
        #     header.append(FIN | opcode)
        #     header.append(PAYLOAD_LEN_EXT64)
        #     header.extend(struct.pack(">Q", payload_length))

        else:
            header.append(0x00 | opcode)
            header.append(125)
            # header.extend(struct.pack(payload_length))
            self.request.send(header + payload[:125])
            self.continue_send_text(payload[125:])
            return

        self.request.send(header + payload)

    def send_binary(self, message, opcode=OPCODE_BINARY):
        header  = bytearray()
        payload = message
        payload_length = len(payload)

        # Normal payload
        if payload_length < 125:
            header.append(FIN | opcode)
            header.append(payload_length)

        # # Extended payload
        # elif payload_length >= 126 and payload_length <= 65535:
        #     header.append(FIN | opcode)
        #     header.append(PAYLOAD_LEN_EXT16)
        #     header.extend(struct.pack(">H", payload_length))

        # # Huge extended payload
        # elif payload_length < 18446744073709551616:
        #     header.append(FIN | opcode)
        #     header.append(PAYLOAD_LEN_EXT64)
        #     header.extend(struct.pack(">Q", payload_length))

        else:
            header.append(0x00 | opcode)
            header.append(125)
            # header.extend(struct.pack(payload_length))
            self.request.send(header + payload[:125])
            # self.continue_send_binary(payload[125:])
            return

        self.request.send(header + payload)

    def continue_send_binary(self, message, opcode=OPCODE_CONTINUATION):
        header  = bytearray()
        payload = message
        payload_length = len(payload)

        # Normal payload
        if payload_length < 125:
            header.append(FIN | opcode)
            header.append(payload_length)

        # # Extended payload
        # elif payload_length >= 126 and payload_length <= 65535:
        #     header.append(FIN | opcode)
        #     header.append(PAYLOAD_LEN_EXT16)
        #     header.extend(struct.pack(">H", payload_length))

        # # Huge extended payload
        # elif payload_length < 18446744073709551616:
        #     header.append(FIN | opcode)
        #     header.append(PAYLOAD_LEN_EXT64)
        #     header.extend(struct.pack(">Q", payload_length))

        else:
            header.append(0x00 | opcode)
            header.append(125)
            # header.extend(struct.pack(payload_length))
            self.request.send(header + payload[:125])
            # self.continue_send_binary(payload[125:])
            return

        self.request.send(header + payload)

    def send_close(self, message, opcode=OPCODE_CLOSE_CONN):
        header  = bytearray()
        payload = message.to_bytes(2, byteorder='big')
        payload_length = 2

        # Normal payload
        if payload_length <= 125:
            header.append(FIN | opcode)
            header.append(payload_length)

        # # Extended payload
        # elif payload_length >= 126 and payload_length <= 65535:
        #     header.append(FIN | opcode)
            # header.append(PAYLOAD_LEN_EXT16)
        #     header.extend(struct.pack(">H", payload_length))

        # # Huge extended payload
        # elif payload_length < 18446744073709551616:
        #     header.append(FIN | opcode)
        #     header.append(PAYLOAD_LEN_EXT64)
        #     header.extend(struct.pack(">Q", payload_length))

        self.request.send(header + payload)

    def read_http_headers(self):
        headers = {}
        # first line should be HTTP GET
        http_get = self.rfile.readline().decode().strip()
        assert http_get.upper().startswith('GET')
        # remaining should be headers
        while True:
            header = self.rfile.readline().decode().strip()
            if not header:
                break
            head, value = header.split(':', 1)
            headers[head.lower().strip()] = value.strip()
        return headers

    def handshake(self):
        headers = self.read_http_headers()

        # Make sure client is ready for websocket
        try:
            assert headers['upgrade'].lower() == 'websocket'
        except AssertionError:
            self.keep_alive = False
            return

        try:
            key = headers['sec-websocket-key']
        except KeyError:
            logger.warning("Client tried to connect but was missing a key")
            self.keep_alive = False
            return

        response = self.make_handshake_response(key)
        self.handshake_done = self.request.send(response.encode())
        self.valid_client = True
        self.server._new_client_(self)

    def make_handshake_response(self, key):
        return \
          'HTTP/1.1 101 Switching Protocols\r\n'\
          'Upgrade: websocket\r\n'              \
          'Connection: Upgrade\r\n'             \
          'Sec-WebSocket-Accept: %s\r\n'        \
          '\r\n' % self.calculate_response_key(key)

    def calculate_response_key(self, key):
        GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
        hash = sha1(key.encode() + GUID.encode())
        response_key = b64encode(hash.digest()).strip()
        return response_key.decode('ASCII')

    def finish(self):
        self.server._client_left_(self)


def encode_to_UTF8(data):
    try:
        return data.encode('UTF-8')
    except UnicodeEncodeError as e:
        logger.error("Could not encode data to UTF-8 -- %s" % e)
        return False
    except Exception as e:
        raise(e)
        return False


def try_decode_UTF8(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return False
    except Exception as e:
        raise(e)
