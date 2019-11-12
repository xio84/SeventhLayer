from websocket_server import *
import os

SIZE_LIMIT = 125

# Called for every client connecting (after handshake)
def new_client(client, server):
	print("New client, id:" + str(client['id']))
	# server.send_message_to_all("Hey all, a new client has joined us")


# Client disconnection warning
def client_left(client, server):
	print("Client(" + str(client['id']) + ") disconnected")


# Message handler
def message_handler(client, server, message, fin):
	message = message.decode('utf-8')
	if (fin):
		if (' ' in message):
			(command, content) = message.split(' ', 1)
			(command, content) = (command.strip(), content.strip())
			if (command == '!echo'):
				server.send_message(client, content)
			if (command == '!submission'):
				file_request = 'upload/submission.zip'
				f = open(file_request, 'rb')
				buf = f.read(SIZE_LIMIT)
				packet_data = bytearray(buf)
				server.send_binary(client, packet_data)
				while (True):
					buf = f.read(SIZE_LIMIT)
					if not buf:
						break
					packet_data = bytearray(buf)
					server.send_continuation(client, packet_data)
				f.close()
	else:
		server.message_buffer += message
		server.message_or_binary = 0

# Binary handler
def binary_handler(client, server, message, fin):
	if (fin):
		file_request = 'download/submission.zip'
		f = open(file_request, 'wb')
		f.write(message)
		f.close()
	else:
		server.binary_buffer += message
		server.message_or_binary = 1

# Continuation handler
def continuation_handler(client, server, message, fin):
	if (server.message_or_binary):
		if (fin):
			file_request = 'download/submission.zip'
			f = open(file_request, 'wb')
			f.write(message)
			f.close()
		else:
			server.binary_buffer += message
	else:
		if (fin):
			if (' ' in message):
				(command, content) = message.split(' ', 1)
				(command, content) = (command.strip(), content.strip())
				if (command == '!echo'):
					server.send_message(client, content)
		else:
			server.message_buffer += message


PORT=9001
server = WebsocketServer(PORT)
server.set_new_client_handler(new_client)
server.set_client_left_handler(client_left)
server.set_message_received_handler(message_handler)
server.set_binary_received_handler(binary_handler)
server.set_continuation_received_handler(continuation_handler)
server.run_forever()
